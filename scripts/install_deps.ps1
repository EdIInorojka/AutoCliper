# StreamCuter: Python deps (local file pipeline) + FFmpeg via winget
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "== 1) Python venv + requirements-local.txt ==" -ForegroundColor Cyan
if (-not (Test-Path "venv\Scripts\python.exe")) {
  py -3.12 -m venv venv
}
& .\venv\Scripts\pip.exe install --upgrade pip
& .\venv\Scripts\pip.exe install -r requirements-local.txt

Write-Host "`n== 2) FFmpeg (winget) ==" -ForegroundColor Cyan
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements

Write-Host "`nDone. New PowerShell window may be needed for PATH." -ForegroundColor Green
Write-Host "E2E:  `$env:STREAMCUTER_RUN_E2E='1'; .\venv\Scripts\python.exe -m unittest -v tests.test_integration_e2e" -ForegroundColor Gray
