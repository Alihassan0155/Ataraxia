$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$taskPython = Join-Path $PSScriptRoot '../.venv-qwen-cuda/Scripts/python.exe'
& $taskPython (Join-Path $PSScriptRoot 'scripts/evaluate.py')
if ($LASTEXITCODE -eq 2) { Write-Output 'Evaluation is waiting for complete independent human annotations; see reports/input_status.json.'; exit 2 }
if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed; inspect heldout_50_evaluation/reports.' }
