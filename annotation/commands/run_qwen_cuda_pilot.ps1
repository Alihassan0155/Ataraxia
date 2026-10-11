$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$pythonPath = Join-Path (Join-Path $PSScriptRoot '..') '.venv-qwen-cuda/Scripts/python.exe'
$runDir = 'pilot_50_reels_30h/results/pilot50_qwen_nf4_max32_limit15p8_v5/qwen'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
$env:HF_HOME = Join-Path (Join-Path $PSScriptRoot '..') '.cache/huggingface'
$env:HF_HUB_DISABLE_XET = '1'
$settings = @('--max-frames', '32', '--fps', '1.0', '--max-new-tokens', '1200', '--max-device-gib', '15.8', '--max-pixels', '262144', '--total-pixels', '0', '--offline')
& $pythonPath src/annotate_qwen_cuda.py --phase benchmark --run-dir $runDir --preflight @settings
if ($LASTEXITCODE -ne 0) { throw 'Pilot media preflight failed' }
& $pythonPath src/annotate_qwen_cuda.py --phase benchmark --run-dir $runDir @settings
if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed; full pilot was not started' }
& $pythonPath src/annotate_qwen_cuda.py --phase pilot --run-dir $runDir @settings
if ($LASTEXITCODE -ne 0) { throw 'Pilot has unresolved failures; inspect failures.jsonl' }
& $pythonPath -m pip freeze | Set-Content -Encoding utf8 (Join-Path $runDir 'requirements.txt')
Write-Output 'Qwen CUDA NF4 pilot complete: 50 validated annotations.'
