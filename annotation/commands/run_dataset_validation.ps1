param([ValidateSet('media','language','all')][string]$Phase = 'all', [int]$Limit = 0,
      [string]$Output = 'data/normalized/audit_merged',
      [string]$ResumeMediaFrom = '',
      [string]$Metadata = 'data/normalized/merged/local_candidates.csv')
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the CUDA Python environment first.' }
if ($Phase -ne 'media') {
    & $pythonPath -c 'import faster_whisper'
    if ($LASTEXITCODE -ne 0) {
        & $pythonPath -m pip install 'faster-whisper>=1.2,<2'
        if ($LASTEXITCODE -ne 0) { throw 'faster-whisper installation failed' }
    }
}
$runnerArgs = @('src/validate_normalized_dataset.py', '--phase', $Phase, '--limit', $Limit, '--output', $Output, '--metadata', $Metadata)
if ($ResumeMediaFrom -and (Test-Path -LiteralPath (Join-Path $ResumeMediaFrom 'checkpoint.jsonl'))) {
    $runnerArgs += @('--resume-media-from', $ResumeMediaFrom)
}
& $pythonPath @runnerArgs
if ($LASTEXITCODE -ne 0) { throw 'Dataset validation stopped; review the error before resuming.' }
