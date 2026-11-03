# Load once in each PowerShell terminal: . .\run.ps1
function run {
    param(
        [Parameter(Mandatory=$true,Position=0)]
        [ValidateSet('gemini','embedder')][string]$Target,
        [switch]$Once,
        [switch]$Check,
        [ValidateSet('Forward','Reverse')][string]$KeyOrder = 'Forward',
        [ValidateRange(1,2147483647)][int]$StartKey,
        [ValidateRange(1,2147483647)][int]$EndKey
    )
    $projectRoot = $PSScriptRoot
    # This existing environment includes the Gemini SDK/pandas as well as BGE-M3.
    $python = Join-Path $projectRoot 'annotation\.venv-qwen-cuda\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw "Required environment missing: $python" }
    $arguments = @('-B','-u','-m','backend.processing.cli',$Target)
    if ($Once) { $arguments += '--once' }
    if ($Check) { $arguments += '--check' }
    if ($Target -ne 'gemini' -and ($PSBoundParameters.ContainsKey('KeyOrder') -or $PSBoundParameters.ContainsKey('StartKey') -or $PSBoundParameters.ContainsKey('EndKey'))) {
        throw 'Key ordering options apply only to Gemini.'
    }
    if ($Target -eq 'gemini') {
        $arguments += @('--key-order', $KeyOrder.ToLowerInvariant())
        if ($PSBoundParameters.ContainsKey('StartKey')) { $arguments += @('--start-key', "$StartKey") }
        if ($PSBoundParameters.ContainsKey('EndKey')) { $arguments += @('--end-key', "$EndKey") }
    }
    Push-Location $projectRoot
    try { & $python @arguments } finally { Pop-Location }
}
