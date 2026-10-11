[CmdletBinding()]
param(
    [string]$RunDir = 'pilot_50_reels_30h/results/pilot50_cuda_nf4_qwen32_intern16_limit15p8_v5',
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_vlm_cuda.ps1 first.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:HF_HOME = Join-Path (Join-Path $PSScriptRoot '..') '.cache/huggingface'
$env:HF_HUB_DISABLE_XET = '1'
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$RunDir = (Resolve-Path -LiteralPath $RunDir).Path
$common = @('--phase', 'pilot', '--fps', '1.0', '--max-new-tokens', '1200', '--max-device-gib', '15.8', '--offline')
$qwenArgs = @('src/annotate_qwen_cuda.py', '--run-dir', (Join-Path $RunDir 'qwen'),
    '--max-frames', '32', '--max-pixels', '262144', '--total-pixels', '0', '--allow-unbenchmarked-pilot') + $common
$internArgs = @('src/annotate_internvl_cuda.py', '--run-dir', (Join-Path $RunDir 'internvl'),
    '--max-frames', '16') + $common

function Invoke-LoggedRunner {
    param([string[]]$RunnerArgs, [string]$LogName)
    $logPath = Join-Path $RunDir $LogName
    # Stream to the console and append a durable log. Nonzero model exits do not skip the other model.
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $pythonPath @RunnerArgs 2>&1 | Tee-Object -FilePath $logPath -Append | Out-Host
    $runnerExit = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    return $runnerExit
}

$startTime = Get-Date
Write-Output "Results: $RunDir"
Write-Output 'Qwen: NF4, 1 FPS capped at 32 uniform full-clip frames. InternVL: NF4, 1 FPS capped at 16 uniform full-clip frames, vision microbatch 1.'
Write-Output 'This research run continues after individual video failures; memory-gate failures remain recorded.'
$qwenPreflight = Invoke-LoggedRunner -RunnerArgs ($qwenArgs + '--preflight') -LogName 'qwen_preflight.log'
$internPreflight = Invoke-LoggedRunner -RunnerArgs ($internArgs + '--preflight') -LogName 'internvl_preflight.log'
if ($qwenPreflight -ne 0 -or $internPreflight -ne 0) {
    throw 'Media/processor preflight failed. Inspect the preflight logs; inference was not started.'
}
if ($PreflightOnly) { Write-Output 'Both 50-video preflights passed; no model inference performed.'; exit 0 }

$qwenExit = Invoke-LoggedRunner -RunnerArgs $qwenArgs -LogName 'qwen.log'
$internExit = Invoke-LoggedRunner -RunnerArgs $internArgs -LogName 'internvl.log'
$summary = [ordered]@{
    started=$startTime.ToString('o'); finished=(Get-Date).ToString('o'); expected_per_model=50
    qwen_exit=$qwenExit; internvl_exit=$internExit; passed=($qwenExit -eq 0 -and $internExit -eq 0)
    qwen_status=$null; internvl_status=$null
}
foreach ($modelName in @('qwen', 'internvl')) {
    $statusPath = Join-Path $RunDir "$modelName/pilot/status.json"
    if (Test-Path -LiteralPath $statusPath) {
        $summary["${modelName}_status"] = Get-Content -Raw -LiteralPath $statusPath | ConvertFrom-Json
    }
}
$summary | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $RunDir 'summary.json')
& $pythonPath -m pip freeze | Set-Content -Encoding utf8 (Join-Path $RunDir 'requirements.txt')
Write-Output "Finished. Inspect $RunDir/summary.json. Rerun this same command to resume validated annotations."
if (-not $summary.passed) { exit 1 }
