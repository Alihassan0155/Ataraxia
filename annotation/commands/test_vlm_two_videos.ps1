[CmdletBinding()]
param(
    [string]$VideoIds = 'FV000662,FV000012',
    [string]$RunDir = '',
    [switch]$Offline,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_vlm_cuda.ps1 first' }
$ids = @($VideoIds.Split(',') | ForEach-Object { $_.Trim() })
if ($ids.Count -ne 2 -or ($ids | Select-Object -Unique).Count -ne 2) { throw 'Specify two distinct comma-separated pilot IDs' }
if (-not $RunDir) { $RunDir = 'outputs/vlm_smoke/' + (Get-Date -Format 'yyyyMMdd_HHmmss') }
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:HF_HOME = Join-Path (Join-Path $PSScriptRoot '..') '.cache/huggingface'
$env:HF_HUB_DISABLE_XET = '1'
$settings = @('--fps', '1.0', '--max-new-tokens', '1200', '--video-ids') + $ids
if ($Offline) { $settings += '--offline' }
if ($PreflightOnly) { $settings += '--preflight' }
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
Write-Output "Testing $($ids -join ', ') sequentially. Outputs: $RunDir"
& $pythonPath src/annotate_qwen_cuda.py --phase smoke --run-dir (Join-Path $RunDir 'qwen') --max-pixels 262144 --total-pixels 0 @settings
$qwenExit = $LASTEXITCODE
# Separate subprocesses release Qwen before loading InternVL, even if Qwen failed.
& $pythonPath src/annotate_internvl_cuda.py --run-dir (Join-Path $RunDir 'internvl') @settings
$internExit = $LASTEXITCODE
$summary = [ordered]@{video_ids=$ids;fps=1.0;max_new_tokens=1200;batch_size=1;temperature=0;
    preflight_only=[bool]$PreflightOnly;qwen_exit=$qwenExit;internvl_exit=$internExit;
    passed=($qwenExit -eq 0 -and $internExit -eq 0)}
$summary | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $RunDir 'summary.json')
if ($qwenExit -ne 0 -or $internExit -ne 0) { throw "Smoke test failed or exceeded headroom. Inspect $RunDir" }
if ($PreflightOnly) {
    Write-Output 'Both input preflights passed. No model inference was performed.'
} else {
    Write-Output 'Both model smoke tests passed. This does not validate longest-video memory or annotation accuracy.'
}
