param(
  [string]$ProjectDir = (Resolve-Path ".").Path
)

$ErrorActionPreference = "Stop"

function Ensure-Dir($p) {
  if (!(Test-Path $p)) { New-Item -ItemType Directory -Force -Path $p | Out-Null }
}

Write-Host "== StreamCuter bootstrap ==" -ForegroundColor Cyan
Write-Host "ProjectDir: $ProjectDir"

$toolsDir = Join-Path $ProjectDir "tools"
$ffDir = Join-Path $toolsDir "ffmpeg"
$ffBin = Join-Path $ffDir "bin"
$ffmpegExe = Join-Path $ffBin "ffmpeg.exe"
$ffprobeExe = Join-Path $ffBin "ffprobe.exe"

Ensure-Dir $toolsDir
Ensure-Dir $ffDir
Ensure-Dir $ffBin

if (!(Test-Path $ffmpegExe) -or !(Test-Path $ffprobeExe)) {
  Write-Host "Downloading ffmpeg..." -ForegroundColor Yellow
  $zip = Join-Path $ffDir "ffmpeg.zip"
  $url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
  Invoke-WebRequest -Uri $url -OutFile $zip

  $extract = Join-Path $ffDir "_extract"
  if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
  Expand-Archive -Path $zip -DestinationPath $extract -Force

  $root = Get-ChildItem $extract | Where-Object { $_.PSIsContainer } | Select-Object -First 1
  if (-not $root) { throw "ffmpeg zip structure unexpected" }

  Copy-Item -Force (Join-Path $root.FullName "bin\\ffmpeg.exe") $ffmpegExe
  Copy-Item -Force (Join-Path $root.FullName "bin\\ffprobe.exe") $ffprobeExe

  Remove-Item -Force $zip
  Remove-Item -Recurse -Force $extract
  Write-Host "ffmpeg ready: $ffmpegExe" -ForegroundColor Green
} else {
  Write-Host "ffmpeg already present in tools/" -ForegroundColor Green
}

Write-Host ""
Write-Host "Python deps:" -ForegroundColor Cyan
Write-Host "If you have internet access, run:" -ForegroundColor Gray
Write-Host "  py -3.12 -m venv venv" -ForegroundColor Gray
Write-Host "  .\\venv\\Scripts\\pip install -r requirements.txt" -ForegroundColor Gray

