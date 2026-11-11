param([switch]$NoBrowser, [switch]$Restart, [int]$Port = 8501)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $projectRoot
$runtime = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path $runtime)) { throw '请先运行 scripts/setup-local.ps1。' }
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $projectRoot 'src'
New-Item -ItemType Directory -Force work/temp | Out-Null
$env:TEMP = Join-Path $projectRoot 'work/temp'
$env:TMP = $env:TEMP
$basePrefix = & $runtime -c 'import sys; print(sys.base_prefix)'
$gdalPath = Join-Path $basePrefix 'Library/share/gdal'
$projPath = Join-Path $basePrefix 'Library/share/proj'
if (Test-Path $gdalPath) { $env:GDAL_DATA = $gdalPath }
if (Test-Path $projPath) { $env:PROJ_LIB = $projPath }
$url = "http://127.0.0.1:$Port"
if ($Restart -and (Test-Path work/server.pid)) {
    $serverProcessId = [int](Get-Content work/server.pid)
    $existing = Get-Process -Id $serverProcessId -ErrorAction SilentlyContinue
    if ($existing -and $existing.Path -eq $runtime) { Stop-Process -Id $serverProcessId }
}
$running = $false
try { $running = (Invoke-WebRequest "$url/_stcore/health" -TimeoutSec 2 -UseBasicParsing).Content -eq 'ok' } catch { }
if (-not $running) {
    $server = Start-Process -FilePath $runtime -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -ArgumentList @(
        '-X','utf8','-m','streamlit','run','app/main.py','--server.address','127.0.0.1',
        '--server.port', $Port, '--server.headless','true','--browser.gatherUsageStats','false'
    ) -RedirectStandardOutput (Join-Path $projectRoot 'work/server.stdout.log') -RedirectStandardError (Join-Path $projectRoot 'work/server.stderr.log')
    $server.Id | Set-Content work/server.pid
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { if ((Invoke-WebRequest "$url/_stcore/health" -TimeoutSec 1 -UseBasicParsing).Content -eq 'ok') { $running=$true; break } } catch { }
    }
    if (-not $running) { throw '网页服务启动失败，请查看 work/server.stderr.log。' }
}
Write-Output $url
if (-not $NoBrowser) { Start-Process $url }
