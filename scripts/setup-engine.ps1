$ErrorActionPreference = 'Stop'
$platformRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $platformRoot
$engineCheckout = Join-Path $platformRoot 'ai-engine-upstream'
$expectedRevision = '0224719c29cc47cde7607a376c8b511a1ee05da2'
if (-not (Test-Path -LiteralPath $engineCheckout)) {
    git clone --single-branch --branch claude/keen-shannon-qawv3n https://github.com/Bigfigboy/marketplace-ai-engine.git $engineCheckout
    if ($LASTEXITCODE -ne 0) { throw 'Failed to clone AI Engine' }
    git -C $engineCheckout checkout $expectedRevision
    if ($LASTEXITCODE -ne 0) { throw 'Failed to select the tested AI Engine revision' }
}
$actualRevision = git -C $engineCheckout rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $expectedRevision) {
    throw 'AI Engine checkout differs from the tested revision. Review it before running.'
}
if (-not (Test-Path -LiteralPath '.engine-venv\Scripts\python.exe')) {
    python -m venv .engine-venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the engine environment' }
}
& '.\.engine-venv\Scripts\python.exe' -m pip install -r runtime/engine-requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Failed to install engine dependencies' }
& '.\.engine-venv\Scripts\python.exe' scripts/configure_local_engine.py
