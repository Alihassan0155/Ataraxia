[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('init','run','resume','status','stop','abort','health','verify-smoke')][string]$Action,
    [string]$Config = '',
    [string]$Run = 'smoke_6',
    [int]$Limit = 6,
    [string]$Python = '',
    [string]$Manifest = '',
    [string]$SmokeRun = '',
    [ValidateSet('qwen','internvl')][string[]]$Models = @('qwen','internvl')
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $Config) { $Config = Join-Path $projectRoot 'configs/distributed.local.json' }
if (-not $Python) { $Python = Join-Path $projectRoot '.venv-qwen-cuda/Scripts/python.exe' }
$runnerArgs = @((Join-Path $PSScriptRoot 'distributed_entry.py'), $Action, '--config', $Config, '--run', $Run, '--limit', $Limit, '--models') + $Models
if ($Manifest) { $runnerArgs += @('--manifest', $Manifest) }
if ($SmokeRun) { $runnerArgs += @('--smoke-run', $SmokeRun) }
& $Python @runnerArgs
if ($LASTEXITCODE -ne 0) { throw "Distributed command failed: $LASTEXITCODE" }
