# Ask the TCU for its ROM ID over K-line SSM, through a Tactrix OpenPort.
#
# MUST RUN 32-BIT. op20pt32.dll is a 32-bit library - PE machine type 0x14C,
# registered only under WOW6432Node - and a 64-bit process cannot load it at any
# price. There is no 64-bit build of it on disk. So this is launched with
# C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe, which is the 32-bit
# host, and it refuses to run rather than fail confusingly if that is not where it
# finds itself. Nothing needs installing: the 32-bit host ships with Windows.
#
# WHY K-LINE AND NOT CAN. FINDINGS 11e: this TCU family flashes over CAN but LOGS
# over classic K-line SSM - the working tool's own configuration says
# log_transport K-Line, log_protocol SSM, while flash_transport is iso15765. So the
# identification request goes down K-line at 4800 8N1.
#
# THE REQUEST. Classic SSM framing is 0x80, destination, source, length, payload,
# then a checksum that is the low byte of the sum of everything before it.
#
#     80 18 F0 01 BF 48
#     |  |  |  |  |  +-- checksum: 80+18+F0+01+BF = 0x248, low byte 0x48
#     |  |  |  |  +----- 0xBF, identification request
#     |  |  |  +-------- one payload byte
#     |  |  +----------- source: 0xF0, the diagnostic tool
#     |  +-------------- destination: 0x18, the transmission. 0x10 is the engine.
#     +----------------- start of frame
#
# The reply carries a five-byte ROM ID, which is the same identifier the ROM images
# in this repository are named by - 91A0217300 and the like.

param(
    [int]$Dest = 0x18,       # 0x18 transmission, 0x10 engine
    [int]$Baud = 4800,
    [int]$TimeoutMs = 3000
)

if ([IntPtr]::Size -ne 4) {
    Write-Host "This must run 32-bit. Re-launch with:" -ForegroundColor Yellow
    Write-Host "  C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe -File $PSCommandPath"
    exit 2
}

$sig = @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct PASSTHRU_MSG {
    public uint ProtocolID;
    public uint RxStatus;
    public uint TxFlags;
    public uint Timestamp;
    public uint DataSize;
    public uint ExtraDataIndex;
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=4128)]
    public byte[] Data;
}

public static class J {
    const string D = @"C:\Windows\SysWOW64\op20pt32.dll";
    [DllImport(D)] public static extern int PassThruOpen(IntPtr n, out uint dev);
    [DllImport(D)] public static extern int PassThruClose(uint dev);
    [DllImport(D)] public static extern int PassThruConnect(uint dev, uint prot, uint flags, uint baud, out uint chan);
    [DllImport(D)] public static extern int PassThruDisconnect(uint chan);
    [DllImport(D)] public static extern int PassThruReadMsgs(uint chan, [In,Out] PASSTHRU_MSG[] m, ref uint num, uint timeout);
    [DllImport(D)] public static extern int PassThruWriteMsgs(uint chan, [In,Out] PASSTHRU_MSG[] m, ref uint num, uint timeout);
    [DllImport(D)] public static extern int PassThruStartMsgFilter(uint chan, uint type, [In] PASSTHRU_MSG[] mask, [In] PASSTHRU_MSG[] pat, IntPtr fc, out uint fid);
    [DllImport(D)] public static extern int PassThruIoctl(uint chan, uint id, IntPtr inp, IntPtr outp);
    [DllImport(D, CharSet=CharSet.Ansi)] public static extern int PassThruGetLastError(System.Text.StringBuilder s);
}
'@
Add-Type -TypeDefinition $sig -ErrorAction Stop

function New-Msg([byte[]]$data, [uint32]$prot) {
    $m = New-Object PASSTHRU_MSG
    $m.ProtocolID = $prot
    $m.Data = New-Object byte[] 4128
    if ($data) { [Array]::Copy($data, $m.Data, $data.Length); $m.DataSize = [uint32]$data.Length }
    return $m
}

function Get-J2534Error {
    $sb = New-Object System.Text.StringBuilder 512
    [void][J]::PassThruGetLastError($sb)
    return $sb.ToString()
}

$ISO9141 = 3
$NO_CHECKSUM = 0x200        # we build the SSM checksum ourselves
$PASS_FILTER = 1

$dev = 0; $chan = 0
$r = [J]::PassThruOpen([IntPtr]::Zero, [ref]$dev)
if ($r -ne 0) { Write-Host "PassThruOpen failed ($r): $(Get-J2534Error)" -ForegroundColor Red; exit 1 }
Write-Host "opened device $dev"

try {
    # Is there battery voltage on the connector at all? READ_VBATT is ioctl 3 on the
    # DEVICE handle, with an OUTPUT pointer to a millivolt value and no input. It
    # settles the question the rest of this script cannot: K-line is pulled up from
    # the controller side, so with nothing powered the bus is dead and even our own
    # transmission does not echo back - which looks identical to a wiring fault.
    $vb = [Runtime.InteropServices.Marshal]::AllocHGlobal(4)
    [Runtime.InteropServices.Marshal]::WriteInt32($vb, 0)
    $rv = [J]::PassThruIoctl($dev, 3, [IntPtr]::Zero, $vb)
    if ($rv -eq 0) {
        $mv = [Runtime.InteropServices.Marshal]::ReadInt32($vb)
        $colour = if ($mv -ge 9000) { "Green" } else { "Yellow" }
        Write-Host ("battery at the connector: {0:N2} V" -f ($mv / 1000.0)) -ForegroundColor $colour
        if ($mv -lt 9000) {
            Write-Host "  Under 9 V. The controller will not run, and K-line has no pull-up," -ForegroundColor Yellow
            Write-Host "  so nothing will answer and nothing will echo." -ForegroundColor Yellow
        }
    } else {
        Write-Host "could not read battery voltage ($rv): $(Get-J2534Error)" -ForegroundColor DarkGray
    }
    [Runtime.InteropServices.Marshal]::FreeHGlobal($vb)

    $r = [J]::PassThruConnect($dev, $ISO9141, $NO_CHECKSUM, $Baud, [ref]$chan)
    if ($r -ne 0) { Write-Host "PassThruConnect failed ($r): $(Get-J2534Error)" -ForegroundColor Red; exit 1 }
    Write-Host ("connected: K-line ISO9141, {0} baud, channel {1}" -f $Baud, $chan)

    # A pass filter with a zero mask matches everything. Without any filter an
    # ISO9141 channel reports nothing at all, which looks exactly like silence from
    # an unpowered controller.
    # Filter width is not negotiable and not documented consistently: this device
    # rejected a one-byte mask with ERR_INVALID_MSG, so try the plausible widths
    # rather than assume. Without an accepted filter an ISO9141 channel delivers
    # nothing, which is indistinguishable from a controller that is not powered -
    # so a failure here has to be loud.
    $fid = 0; $filtered = $false
    foreach ($w in 1,2,4,5) {
        $zeros = New-Object byte[] $w
        $mask = @(New-Msg $zeros $ISO9141)
        $pat  = @(New-Msg $zeros $ISO9141)
        $r = [J]::PassThruStartMsgFilter($chan, $PASS_FILTER, $mask, $pat, [IntPtr]::Zero, [ref]$fid)
        if ($r -eq 0) { Write-Host "pass filter accepted at $w byte(s), id $fid"; $filtered = $true; break }
        Write-Host ("  filter width {0} rejected ({1}: {2})" -f $w, $r, (Get-J2534Error)) -ForegroundColor DarkGray
    }
    if (-not $filtered) {
        Write-Host "No pass filter was accepted - reads will return nothing." -ForegroundColor Red
    }

    # No loopback ioctl here. Ioctl 3 is SET_CONFIG and takes an SCONFIG_LIST, not
    # a pointer to an int - handing it one crashed the process with an access
    # violation inside the vendor library. Loopback is a PARAMETER within SET_CONFIG
    # rather than an ioctl of its own. The echo is not needed: the OpenPort echoes
    # K-line transmissions anyway, so seeing our own request come back already
    # proves the transmit path.

    $req = [byte[]](0x80, $Dest, 0xF0, 0x01, 0xBF)
    $sum = 0; foreach ($b in $req) { $sum += $b }
    $req += [byte]($sum -band 0xFF)
    Write-Host ("request: {0}" -f (($req | ForEach-Object { $_.ToString('X2') }) -join ' '))

    $tx = @(New-Msg $req $ISO9141)
    $n = [uint32]1
    $r = [J]::PassThruWriteMsgs($chan, $tx, [ref]$n, 1000)
    if ($r -ne 0) { Write-Host "write failed ($r): $(Get-J2534Error)" -ForegroundColor Red; exit 1 }

    $deadline = (Get-Date).AddMilliseconds($TimeoutMs)
    $frames = @()
    while ((Get-Date) -lt $deadline) {
        $rx = @(New-Msg $null $ISO9141)
        $n = [uint32]1
        $r = [J]::PassThruReadMsgs($chan, $rx, [ref]$n, 500)
        if ($r -ne 0 -or $n -eq 0) { continue }
        $len = [int]$rx[0].DataSize
        if ($len -le 0) { continue }
        $b = $rx[0].Data[0..($len-1)]
        $hex = ($b | ForEach-Object { $_.ToString('X2') }) -join ' '
        # The interface echoes what we sent; that is the loopback, not an answer.
        if ($len -ge 3 -and $b[0] -eq 0x80 -and $b[2] -eq 0xF0) {
            Write-Host "  (loopback) $hex" -ForegroundColor DarkGray
            continue
        }
        Write-Host "  received: $hex" -ForegroundColor Green
        $frames += ,$b
    }

    if ($frames.Count -eq 0) {
        Write-Host ""
        Write-Host "Nothing answered." -ForegroundColor Yellow
        Write-Host "In the order worth checking:"
        Write-Host "  1. Is the TCU powered? The cable does not power it. It needs 12 V on"
        Write-Host "     B54 pins 7, 8 and 10, and ground on B55 pin 21. Unpowered is by far"
        Write-Host "     the most likely cause of exactly this silence."
        Write-Host "  2. Is the ignition line high? The unit stays asleep without it."
        Write-Host "  3. Is K-line actually wired through to the OpenPort's pin 7?"
        Write-Host "  4. Try the engine address instead:  -Dest 0x10"
        exit 1
    }

    foreach ($f in $frames) {
        if ($f.Length -ge 13 -and $f[4] -eq 0xFF) {
            $ssm = ($f[5..7]   | ForEach-Object { $_.ToString('X2') }) -join ''
            $rom = ($f[8..12]  | ForEach-Object { $_.ToString('X2') }) -join ''
            Write-Host ""
            Write-Host "  SSM ID : $ssm"
            Write-Host "  ROM ID : $rom" -ForegroundColor Cyan
        }
    }
}
finally {
    if ($chan) { [void][J]::PassThruDisconnect($chan) }
    if ($dev)  { [void][J]::PassThruClose($dev) }
}
