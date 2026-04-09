Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyInstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
$downloadsDir = Join-Path $projectRoot "downloads"
$releaseDir = Join-Path $projectRoot "release\Music Mastery"
$zipPath = Join-Path $downloadsDir "Music-Mastery-win64.zip"

$env:PYTHONPATH = "src"

& $pyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --name "Music Mastery" `
  --paths src `
  --distpath release `
  --workpath build-pyinstaller `
  --specpath build-pyinstaller `
  --collect-all matchering `
  --collect-all ffmpeg_normalize `
  --add-binary "$ffmpeg;." `
  src\mastery_native\main.py

New-Item -ItemType Directory -Path $downloadsDir -Force | Out-Null
if (Test-Path -LiteralPath $zipPath) {
  Remove-Item -LiteralPath $zipPath -Force
}

Compress-Archive -Path (Join-Path $releaseDir '*') -DestinationPath $zipPath -CompressionLevel Optimal
