[CmdletBinding()]
param(
    [ValidateSet(16,24,32)][int]$NumFrames = 32,
    [string]$RunDir = '',
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_vlm_cuda.ps1 first.' }
if (-not $RunDir) { $RunDir = "pilot_50_reels_30h/results/pilot50_internvl_nf4_fixed${NumFrames}_v1" }
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$env:HF_HOME = Join-Path (Join-Path $PSScriptRoot '..') '.cache/huggingface'
$env:HF_HUB_DISABLE_XET = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$settings = @('src/annotate_internvl_cuda.py', '--phase', 'pilot', '--run-dir',
    (Join-Path $RunDir 'internvl'), '--num-frames', "$NumFrames", '--max-new-tokens', '1200', '--offline')
Write-Output "InternVL only: $NumFrames fixed uniform full-clip frames. Results: $RunDir"
$ErrorActionPreference = 'Continue'
& $pythonPath @settings --preflight 2>&1 | Tee-Object -FilePath (Join-Path $RunDir 'preflight.log') -Append | Out-Host
$preflightExit = $LASTEXITCODE
if ($preflightExit -ne 0) { throw 'Processor preflight failed; inference was not started.' }
if ($PreflightOnly) { exit 0 }
& $pythonPath @settings 2>&1 | Tee-Object -FilePath (Join-Path $RunDir 'internvl.log') -Append | Out-Host
$runnerExit = $LASTEXITCODE
Write-Output "Finished with exit $runnerExit. Inspect internvl/pilot/status.json. Repeat to resume this same sampling policy."
exit $runnerExit
