# Load once in each PowerShell terminal: . .\run.ps1
function run {
    param(
        [Parameter(Mandatory=$true,Position=0)]
        [ValidateSet('gemini','embedder')][string]$Target,
        [switch]$Once,
        [switch]$Check
    )
    $projectRoot = $PSScriptRoot
    # This existing environment includes the Gemini SDK/pandas as well as BGE-M3.
    $python = Join-Path $projectRoot 'annotation\.venv-qwen-cuda\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw "Required environment missing: $python" }
    $arguments = @('-B','-u','-m','backend.processing.cli',$Target)
    if ($Once) { $arguments += '--once' }
    if ($Check) { $arguments += '--check' }
    Push-Location $projectRoot
    try { & $python @arguments } finally { Pop-Location }
}
