<#
.SYNOPSIS
    Hand the CANtact Pro to WSL so Linux CAN tooling can use it.

.DESCRIPTION
    WSL2 is a virtual machine and has no USB access of its own. usbipd-win forwards
    a device over USB/IP; the WSL kernel already has the gs_usb driver the CANtact
    Pro speaks, so once it is attached it appears as a normal CAN interface.

    Run from an ADMIN PowerShell:

        powershell -ExecutionPolicy Bypass -File tools\bench\attach-cantact.ps1

    The bind step is persistent - do it once. The attach step is not: it has to be
    repeated after a reboot, after unplugging the adapter, and after WSL shuts down.
    Run this script again for that; it skips whatever is already done.

    The OpenPort 2.0 is deliberately NOT forwarded. It uses a Windows-only J2534
    driver, and moving it to WSL would take it away from the Windows tools that can
    actually use it while giving Linux a device it has no driver for.
#>

$ErrorActionPreference = 'Stop'
$VID_PID = '1d50:606f'   # CANtact Pro, candleLight/gs_usb firmware

function Info($m) { Write-Host "  $m" }

# --- admin ------------------------------------------------------------------
$admin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "This needs an elevated PowerShell - binding a USB device is a"
    Write-Host "system-wide change. Re-run it from an admin prompt."
    exit 1
}

# --- usbipd -----------------------------------------------------------------
Write-Host "=== usbipd-win"
if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
    Info "not installed - installing via winget"
    winget install --exact --id dorssel.usbipd-win `
        --accept-source-agreements --accept-package-agreements
    # winget puts it on PATH for new processes only.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Get-Command usbipd -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "usbipd installed but is not on PATH in this session."
        Write-Host "Open a new admin PowerShell and run this script again."
        exit 0
    }
} else {
    Info ("present: " + (usbipd --version))
}

# --- find the adapter -------------------------------------------------------
Write-Host ""
Write-Host "=== finding the CANtact Pro"
$line = usbipd list | Where-Object { $_ -match [regex]::Escape($VID_PID) }
if (-not $line) {
    Write-Host "  not found. Is it plugged in?"
    Write-Host "  Devices seen by usbipd:"
    usbipd list | Select-Object -Skip 1 | ForEach-Object { "    $_" }
    exit 1
}
$busid = ($line -split '\s+')[0]
Info "found at busid $busid"
Info $line.Trim()

# --- bind (persistent) ------------------------------------------------------
Write-Host ""
Write-Host "=== bind"
if ($line -match 'Shared|Attached') {
    Info "already bound"
} else {
    usbipd bind --busid $busid
    Info "bound - this survives reboots"
}

# --- attach (per session) ---------------------------------------------------
Write-Host ""
Write-Host "=== attach to WSL"
if ($line -match 'Attached') {
    Info "already attached"
} else {
    usbipd attach --wsl --busid $busid
    Info "attached - repeat after a reboot, replug, or WSL shutdown"
}

Write-Host ""
Write-Host "=== what WSL sees now"
wsl -- bash -c "lsusb 2>/dev/null | grep -i '1d50:606f' || echo '  not visible to WSL yet'"
wsl -- bash -c "ip -brief link show 2>/dev/null | grep -E '^can' || echo '  no can interface yet - run: sudo ip link set can0 up type can bitrate 500000'"
