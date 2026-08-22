# Fetch + verify the bundled hardware drivers into drivers\.
#   powershell -ExecutionPolicy Bypass -File fetch_drivers.ps1
#
# Downloads from official sources and verifies each is genuine (Authenticode
# publisher and/or SHA256). Run this on a normal network — FTDI's CDN blocks some
# datacenter/VPN IPs with HTTP 403, in which case fetch FTDI on a plain connection.
# Idempotent: re-running re-verifies existing files.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$ProgressPreference = "SilentlyContinue"
$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

function Grab($url, $out, $expectSubject, $expectSha) {
    New-Item -ItemType Directory -Force -Path (Split-Path $out) | Out-Null
    Write-Host "-> $out" -ForegroundColor Cyan
    try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 180 -Headers @{ "User-Agent" = $UA } }
    catch { Write-Host "   DOWNLOAD FAILED: $($_.Exception.Message)" -ForegroundColor Red; return $false }
    if ($expectSha) {
        $sha = (Get-FileHash $out -Algorithm SHA256).Hash
        if ($sha -ne $expectSha) { Write-Host "   SHA256 MISMATCH! got $sha" -ForegroundColor Red; return $false }
        Write-Host "   sha256 ok" -ForegroundColor Green
    }
    if ($expectSubject) {
        $s = Get-AuthenticodeSignature $out
        if ($s.Status -ne "Valid" -or $s.SignerCertificate.Subject -notlike "*$expectSubject*") {
            Write-Host "   SIGNATURE CHECK FAILED: $($s.Status) / $($s.SignerCertificate.Subject)" -ForegroundColor Red; return $false
        }
        Write-Host "   signed by $expectSubject ($($s.Status))" -ForegroundColor Green
    }
    return $true
}

# 1. Edge WebView2 evergreen bootstrapper (Microsoft)
Grab "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "drivers\webview2\MicrosoftEdgeWebview2Setup.exe" "Microsoft Corporation" $null | Out-Null

# 2. Zadig — WinUSB installer for the CANtact Pro (Akeo / Pete Batard, embeds libwdi)
Grab "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe" "drivers\canable\zadig.exe" "Akeo Consulting" $null | Out-Null

# 3. FTDI CDM (Tactrix OpenPort 2.0 serial). URL + checksum per the Chocolatey ftdi-drivers pkg.
$ftZip = "drivers\ftdi\CDM_Setup.zip"
if (Grab "https://ftdichip.com/wp-content/uploads/2021/08/CDM212364_Setup.zip" $ftZip $null `
         "10C399AC784D2B68B1BB2BA598BAB7FE00CFDFD267B4CC14A3E3240FE9499FB1") {
    Expand-Archive $ftZip "drivers\ftdi\_x" -Force
    $exe = Get-ChildItem "drivers\ftdi\_x" -Recurse -Filter *.exe | Select-Object -First 1
    Copy-Item $exe.FullName "drivers\ftdi\ftdi_setup.exe" -Force
    $s = Get-AuthenticodeSignature "drivers\ftdi\ftdi_setup.exe"
    Write-Host "   FTDI setup signed by $(($s.SignerCertificate.Subject -split ',')[0]) ($($s.Status))" -ForegroundColor Green
    Remove-Item $ftZip, "drivers\ftdi\_x" -Recurse -Force
} else {
    Write-Host "   FTDI not fetched here (Cloudflare 403 on some IPs). Run this script on a" -ForegroundColor Yellow
    Write-Host "   normal connection, or grab it from https://ftdichip.com/drivers/vcp-drivers/" -ForegroundColor Yellow
    Write-Host "   Note: Windows 10/11 usually auto-installs an in-box FTDI driver anyway." -ForegroundColor Yellow
}

Write-Host "== staged drivers ==" -ForegroundColor Green
Get-ChildItem drivers -Recurse -File -Exclude *.md | Select-Object FullName, @{n='KB';e={[int]($_.Length/1KB)}} | Format-Table -AutoSize
