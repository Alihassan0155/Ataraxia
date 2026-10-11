param([ValidateSet('review','select','preprocess','heldout')][string]$Phase = 'review', [int]$Limit = 0)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda\Scripts\python.exe'
if ($Phase -eq 'preprocess') {
    & $pythonPath -c 'import opensmile'
    if ($LASTEXITCODE -ne 0) {
        & $pythonPath -m pip install 'opensmile>=2.6,<3'
        if ($LASTEXITCODE -ne 0) { throw 'openSMILE installation failed' }
    }
    & $pythonPath src/preprocess_normalized_dataset.py --limit $Limit
} else {
    & $pythonPath src/prepare_normalized_dataset.py $Phase
}
if ($LASTEXITCODE -ne 0) { throw 'Stage stopped; inspect the error before continuing.' }
