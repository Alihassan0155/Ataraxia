[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [string]$LocalRoot = (Join-Path $env:SystemDrive 'AtaraxiaWorker'),
    [string]$StateRoot = '',
    [string]$BootstrapPython = 'python',
    [switch]$InstallDependencies,
    [switch]$DownloadModels,
    [switch]$LocalBootstrap
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'distributed_worker_paths.ps1')
$paths = Get-AtaraxiaWorkerPaths -LocalRoot $LocalRoot -StateRoot $StateRoot
$LocalRoot = $paths.installation_root
$workerPython = $paths.python
if (-not $InstallDependencies -and -not (Test-Path -LiteralPath $workerPython)) {
    throw 'No existing environment at the selected location. For initial installation explicitly pass -InstallDependencies.'
}
foreach ($directory in @($LocalRoot, $paths.local_root, $paths.cache, $paths.logs, $paths.dependencies)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}
if ($InstallDependencies -and -not (Test-Path -LiteralPath $workerPython)) {
    & $BootstrapPython -m venv (Join-Path $LocalRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
}
$requirements = Join-Path $paths.dependencies 'requirements-vlm-cuda.txt'
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'requirements-vlm-cuda.txt') -Destination $requirements
if ($InstallDependencies) {
    $pipLog = Join-Path $paths.logs 'dependency_install.log'
    & $workerPython -m pip --log $pipLog install 'torch==2.11.0' 'torchvision==0.26.0' --index-url https://download.pytorch.org/whl/cu128
    if ($LASTEXITCODE -ne 0) { throw 'CUDA dependency installation failed' }
    & $workerPython -m pip --log $pipLog install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency installation failed' }
}
& $workerPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
$env:HF_HOME = $paths.cache
$env:HF_HUB_CACHE = Join-Path $paths.cache 'hub'
$env:HF_ASSETS_CACHE = Join-Path $paths.cache 'assets'
$env:HF_HUB_DISABLE_XET = '1'
if ($LocalBootstrap) {
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'commands/distributed_worker.py') -Destination $paths.bootstrap
}
if ($DownloadModels) {
    & $workerPython (Join-Path $ProjectRoot 'commands/download_distributed_models.py') --root $ProjectRoot 2>&1 | Tee-Object -FilePath (Join-Path $paths.logs 'model_download.log')
    if ($LASTEXITCODE -ne 0) { throw 'Checkpoint download failed' }
}
$paths | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LocalRoot 'worker_paths.json') -Encoding UTF8
& $workerPython (Join-Path $ProjectRoot 'commands/distributed_worker.py') --root $ProjectRoot --local-root $paths.local_root --cache $env:HF_HOME --health 2>&1 | Tee-Object -FilePath (Join-Path $paths.logs 'health.log')
if ($LASTEXITCODE -ne 0) { throw 'GPU/share health check failed' }
