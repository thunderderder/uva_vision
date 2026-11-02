# UVA 内核 CLI — 单体仓库入口
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $VenvPy = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPy) { throw "找不到 Python。请先 python -m venv .venv" }
}
$env:PYTHONPATH = Join-Path $Root "src"
Set-Location $Root
& $VenvPy -m uva @args
