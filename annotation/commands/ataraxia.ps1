[CmdletBinding()]
param(
    [string]$Python = '',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $projectRoot '.venv-qwen-cuda/Scripts/python.exe' }
$env:PYTHONUTF8 = '1'
& $Python -m ataraxia --project-root $projectRoot @CliArgs
if ($LASTEXITCODE -ne 0) { throw "Ataraxia exited with code $LASTEXITCODE" }
