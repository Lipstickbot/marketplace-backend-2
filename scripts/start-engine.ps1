param([int]$Port = 8002)
$ErrorActionPreference = 'Stop'
$platformRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $platformRoot
if (-not (Test-Path -LiteralPath '.engine-venv\Scripts\python.exe')) {
    throw 'Run scripts/setup-engine.ps1 first'
}
$env:PYTHONPATH = $platformRoot
& '.\.engine-venv\Scripts\python.exe' scripts/configure_local_engine.py
& '.\.engine-venv\Scripts\python.exe' -m uvicorn scripts.local_engine:create_app --factory --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
