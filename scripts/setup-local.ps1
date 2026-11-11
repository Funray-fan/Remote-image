param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force work/temp | Out-Null
$env:TEMP = Join-Path $projectRoot 'work/temp'
$env:TMP = $env:TEMP
& $Python -m venv --system-site-packages .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 环境创建失败，请指定可用的 Anaconda python.exe。' }
$runtime = Join-Path $projectRoot '.venv/Scripts/python.exe'
& $runtime -c "import streamlit,rasterio,geopandas,scipy,jsonschema,pytest"
if ($LASTEXITCODE -ne 0) {
    & $runtime -m pip install -e '.[r2,ui,dev]'
} else {
    & $runtime -m pip install --no-build-isolation --no-deps -e .
}
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
Write-Output '环境准备完成。运行 scripts/start-local.ps1 启动网页。'
