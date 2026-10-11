[CmdletBinding()]
param([switch]$PreflightOnly)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '../.venv-qwen-cuda/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The existing .venv-qwen-cuda environment is required.' }
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
& $taskPython (Join-Path $PSScriptRoot 'scripts/prepare.py')
if ($LASTEXITCODE -ne 0) { throw 'Held-out preparation/freeze verification failed.' }
$taskArguments = @((Join-Path $PSScriptRoot 'scripts/run_inference.py'))
if ($PreflightOnly) { $taskArguments += '--preflight-only' }
& $taskPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'One or more models failed; inspect heldout_50_evaluation/logs and rerun to resume.' }
