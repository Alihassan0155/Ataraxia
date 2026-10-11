$ErrorActionPreference = 'Stop'
$taskBootstrap = Join-Path $PSScriptRoot '../.venv-qwen-cuda/Scripts/python.exe'
$taskEnvironment = Join-Path $PSScriptRoot '.venv-gemini'
if (-not (Test-Path -LiteralPath (Join-Path $taskEnvironment 'Scripts/python.exe'))) {
    & $taskBootstrap -m venv $taskEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Gemini environment creation failed.' }
}
$taskPython = Join-Path $taskEnvironment 'Scripts/python.exe'
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-gemini.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the recorded Gemini package versions. Resolve package availability explicitly; do not silently change the frozen SDK.' }
& $taskPython -m pip freeze | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'config/gemini_environment.txt') -Encoding UTF8
