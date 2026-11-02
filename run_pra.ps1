# UVA Vision 工作台
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $VenvPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPy) { throw "找不到 Python。请先 python -m venv .venv" }
}
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location $Root
& $VenvPy -m uva_pra @args
