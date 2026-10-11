[CmdletBinding()]
param(
    [string]$Python = 'C:\Program Files\Python312\python.exe',
    [switch]$DownloadWeights
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path (Join-Path $PSScriptRoot '..') '.cache/huggingface'
$env:HF_HUB_DISABLE_XET = '1'
$venvPython = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv (Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda')
    if ($LASTEXITCODE -ne 0) { throw 'Creating the CUDA environment failed' }
}
& $venvPython -m pip install 'torch==2.11.0' 'torchvision==0.26.0' --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw 'CUDA PyTorch installation failed' }
& $venvPython -m pip install -r requirements-vlm-cuda.txt
if ($LASTEXITCODE -ne 0) { throw 'VLM dependency installation failed' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed' }
& $venvPython src/check_vlm_cuda.py
if ($LASTEXITCODE -ne 0) { throw 'CUDA/import checks failed' }
if ($DownloadWeights) {
    & $venvPython src/check_vlm_cuda.py --download
    if ($LASTEXITCODE -ne 0) { throw 'Model download failed; rerun to resume' }
}
& $venvPython -m pip freeze | Set-Content -Encoding utf8 requirements-vlm-cuda-installed.txt
Write-Output 'Environment ready. Run test_vlm_two_videos.ps1 for inference.'
