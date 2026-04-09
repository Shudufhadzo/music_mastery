Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$pathsToRemove = @(
    ".pytest_cache",
    "artifacts",
    "build",
    "build-pyinstaller",
    "release"
)

foreach ($relativePath in $pathsToRemove) {
    $absolutePath = Join-Path $projectRoot $relativePath
    if (Test-Path -LiteralPath $absolutePath) {
        Remove-Item -LiteralPath $absolutePath -Recurse -Force
    }
}

Get-ChildItem -Path $projectRoot -Recurse -Directory -Force |
    Where-Object {
        $_.Name -eq "__pycache__" -and
        $_.FullName -notlike "*\.venv\*"
    } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }

Get-ChildItem -Path $projectRoot -Recurse -File -Force |
    Where-Object {
        $_.Extension -in @(".pyc", ".pyo") -and
        $_.FullName -notlike "*\.venv\*"
    } |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force
    }
