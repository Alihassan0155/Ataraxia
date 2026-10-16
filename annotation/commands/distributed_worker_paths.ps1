function Get-AtaraxiaWorkerPaths {
    param([string]$LocalRoot, [string]$StateRoot = '')
    foreach ($value in @($LocalRoot, $StateRoot) | Where-Object { $_ }) {
        if ($value -notmatch '^[A-Za-z]:[\\/]' -or $value.Contains('"')) {
            throw 'Worker installation/state paths must be absolute local drive paths.'
        }
    }
    $base = [System.IO.Path]::GetFullPath($LocalRoot)
    if (-not $StateRoot) { $StateRoot = Join-Path $base 'state' }
    return @{
        installation_root = $base
        python = Join-Path $base 'venv/Scripts/python.exe'
        local_root = [System.IO.Path]::GetFullPath($StateRoot)
        cache = Join-Path $base 'cache/huggingface'
        logs = Join-Path $base 'logs'
        dependencies = Join-Path $base 'dependencies'
        bootstrap = Join-Path $base 'distributed_worker.py'
        task_bootstrap = Join-Path $base 'distributed_task_bootstrap.py'
    }
}
