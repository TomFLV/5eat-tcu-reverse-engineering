# Build the standalone TCU Simulator: PyInstaller one-folder .exe + portable zip,
# then (if Inno Setup is present) the driver-bundling installer.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Produces:
#   dist\TCUSimulator\                     one-folder app
#   dist\TCUSimulator_portable.zip         portable zip (no drivers)
#   dist\TCUSimulator-Setup.exe            installer (app + drivers), if ISCC found
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== installing build deps ==" -ForegroundColor Cyan
python -m pip install -q -r requirements.txt
python -m pip install -q pyinstaller

Write-Host "== building app (PyInstaller) ==" -ForegroundColor Cyan
python -m PyInstaller TCUSimulator.spec --noconfirm --clean

if (-not (Test-Path "dist\TCUSimulator\TCUSimulator.exe")) {
    throw "build failed: dist\TCUSimulator\TCUSimulator.exe not found"
}

Write-Host "== zipping portable build ==" -ForegroundColor Cyan
$zip = "dist\TCUSimulator_portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\TCUSimulator\*" -DestinationPath $zip
Write-Host "portable zip: $zip"

# Optional installer (needs Inno Setup's ISCC.exe on PATH or default location)
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                     "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if ($iscc) {
    Write-Host "== building installer (Inno Setup) ==" -ForegroundColor Cyan
    & $iscc "installer.iss"
    Write-Host "installer: dist\TCUSimulator-Setup.exe"
} else {
    Write-Host "Inno Setup (ISCC.exe) not found - skipped installer. Install from" -ForegroundColor Yellow
    Write-Host "https://jrsoftware.org/isdl.php to build dist\TCUSimulator-Setup.exe" -ForegroundColor Yellow
}
Write-Host "== done ==" -ForegroundColor Green
