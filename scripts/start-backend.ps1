param([int]$Port = 8001)

$ErrorActionPreference = 'Stop'
$platformRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $platformRoot
$backendPython = Join-Path $platformRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    $backendPython = (Get-Command python -ErrorAction Stop).Source
}
# .run-deps is only used by the local Codex test environment, if present.
$env:PYTHONPATH = (Join-Path $platformRoot '.run-deps') + ';' + $platformRoot
& $backendPython -m uvicorn backend.app.main:create_app --factory --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
