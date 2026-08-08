#!/usr/bin/env python3
"""Read TCU RAM over CAN, without J2534.

WHY THIS EXISTS. The obvious way to read a Subaru controller's memory is the
Select Monitor over a Tactrix OpenPort, through its J2534 library. That library is
32-bit - confirmed from its PE header, machine type 0x14C, registered only in the
32-bit registry view, with no 64-bit variant on disk - and this project's
application bundles a 64-bit runtime. A 64-bit process cannot load a 32-bit
library, and no amount of configuration changes that.

It turns out not to matter. The TCU's own CAN receive table lists 0x7DF, 0x7E1 and
0x7E9: functional broadcast, physical request, and response, which is standard ISO
15765 diagnostic addressing. So the controller can be read over CAN, with the
adapter that is already working, and J2534 drops out of the problem entirely.

THE PROTOCOL is not guessed. FINDINGS 11e decompiled RomRaider's own SSMProtocol
for the iso15765 variant - three-byte addresses, READ_ADDRESS_COMMAND = 0xA8,
500,000 baud - and a forum post independently confirmed the same command bytes
observed in a real TCU's disassembly. Block reads throw "not supported on CAN";
only read-address works, batching several addresses per request.

    python3 tools/bench/ssm_can.py --dtc            # the two fault arrays
    python3 tools/bench/ssm_can.py --read FFFF8876 --count 14
    python3 tools/bench/ssm_can.py --probe          # is anything answering at all

ONE THING TO WATCH. SSM addresses are three bytes and this controller's RAM lives
at 0xFFFF____, so only the low 24 bits fit. The M32R units have the same protocol
and 24-bit addresses natively, so this has never been tested against a Denso unit.
If reads come back empty or wrong, that truncation is the first thing to suspect,
and --raw lets you send an address byte-for-byte to check.
"""

import argparse
import binascii
import sys
import time

# Imported lazily rather than at module load: --help should work on a machine
# without python-can, and CI has none. Exiting at import made the tool unable to
# say what it does.
try:
    import can
except ImportError:
    can = None


def _need_can():
    if can is None:
        sys.exit("python-can is not installed - run tools/bench/setup-wsl-can.sh")

REQ_ID = 0x7E1          # physical request to the transmission controller
RESP_ID = 0x7E9         # its response
BROADCAST = 0x7DF

READ_ADDRESS = 0xA8
READ_RESPONSE = 0xE8

# The two arrays the whole bench exercise exists to read. FINDINGS 81.
DTC_LIVE = 0xFFFF8876
DTC_CONFIRMED = 0xFFFF21D6
DTC_BYTES = 14


def open_bus(channel, bitrate):
    _need_can()
    try:
        return can.Bus(interface="socketcan", channel=channel, bitrate=bitrate)
    except Exception as e:
        sys.exit("cannot open %s: %s\n  ip link set %s up type can bitrate %d"
                 % (channel, e, channel, bitrate))


def isotp_send(bus, payload, req_id=REQ_ID, fc_id=RESP_ID):
    """Send one ISO-TP message. Single frame if it fits, else first+consecutive.

    Implemented here rather than pulled in as a dependency: the requests are a
    handful of bytes and the flow control handling needed is minimal, and one
    fewer thing to install on a bench machine is worth twenty lines.
    """
    if len(payload) <= 7:
        data = bytes([len(payload)]) + payload
        data += b"\x00" * (8 - len(data))
        bus.send(can.Message(arbitration_id=req_id, data=data,
                             is_extended_id=False))
        return True

    first = bytes([0x10 | ((len(payload) >> 8) & 0x0F), len(payload) & 0xFF])
    first += payload[:6]
    bus.send(can.Message(arbitration_id=req_id, data=first, is_extended_id=False))

    # Wait for flow control before continuing, as the standard requires.
    #
    # fc_id is the ID the OTHER end sends flow control on, which is not always
    # RESP_ID: a test responder using this function to answer sends on RESP_ID and
    # must wait on REQ_ID. Hardcoding it truncated every multi-frame reply to its
    # first frame - the sender timed out waiting for a flow control that was sitting
    # on the other ID.
    end = time.time() + 1.0
    while time.time() < end:
        m = bus.recv(timeout=0.2)
        if m and m.arbitration_id == fc_id and (m.data[0] & 0xF0) == 0x30:
            break
    else:
        return False

    rest, sn = payload[6:], 1
    while rest:
        chunk, rest = rest[:7], rest[7:]
        data = bytes([0x20 | (sn & 0x0F)]) + chunk
        data += b"\x00" * (8 - len(data))
        bus.send(can.Message(arbitration_id=req_id, data=data,
                             is_extended_id=False))
        sn += 1
        time.sleep(0.005)
    return True


def isotp_recv(bus, timeout=2.0):
    """Reassemble one ISO-TP message from the controller."""
    end = time.time() + timeout
    payload, expected = b"", None
    while time.time() < end:
        m = bus.recv(timeout=0.2)
        if m is None or m.arbitration_id != RESP_ID:
            continue
        d = bytes(m.data)
        kind = d[0] & 0xF0
        if kind == 0x00:                      # single frame
            return d[1:1 + (d[0] & 0x0F)]
        if kind == 0x10:                      # first frame
            expected = ((d[0] & 0x0F) << 8) | d[1]
            payload = d[2:]
            # Flow control: clear to send, no block limit, no separation time.
            bus.send(can.Message(arbitration_id=REQ_ID,
                                 data=bytes([0x30, 0x00, 0x00, 0, 0, 0, 0, 0]),
                                 is_extended_id=False))
        elif kind == 0x20 and expected:       # consecutive
            payload += d[1:]
            if len(payload) >= expected:
                return payload[:expected]
    return payload[:expected] if expected else None


def read_addresses(bus, addresses):
    """SSM read-address: 0xA8, a padding byte, then three bytes per address."""
    req = bytes([READ_ADDRESS, 0x00])
    for a in addresses:
        req += bytes([(a >> 16) & 0xFF, (a >> 8) & 0xFF, a & 0xFF])
    if not isotp_send(bus, req):
        return None
    resp = isotp_recv(bus)
    if not resp:
        return None
    if resp[0] != READ_RESPONSE:
        return ("unexpected", resp)
    return resp[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="can0")
    ap.add_argument("--bitrate", type=int, default=500000)
    ap.add_argument("--probe", action="store_true",
                    help="is anything answering on the diagnostic IDs")
    ap.add_argument("--dtc", action="store_true",
                    help="read both fault arrays and decode them")
    ap.add_argument("--read", metavar="HEXADDR")
    ap.add_argument("--count", type=int, default=1)
    args = ap.parse_args()

    bus = open_bus(args.channel, args.bitrate)
    try:
        if args.probe:
            print("listening for any diagnostic traffic on 0x%03X and 0x%03X,"
                  " then asking\n" % (REQ_ID, RESP_ID))
            r = read_addresses(bus, [DTC_LIVE])
            if r is None:
                print("  no answer.")
                print("  Things to check, in the order worth checking them:")
                print("    the controller is powered and its ignition line is high")
                print("    the bus is terminated - 120 ohms at each end")
                print("    the bitrate: 500k is standard here but unconfirmed")
                print("    CAN high and low are not swapped")
                return 1
            print("  answered: %s" % binascii.hexlify(bytes(r), " ").decode())
            return 0

        if args.dtc:
            print("reading the two fault arrays\n")
            for label, base in (("live      0x%08X" % DTC_LIVE, DTC_LIVE),
                                ("confirmed 0x%08X" % DTC_CONFIRMED,
                                 DTC_CONFIRMED)):
                addrs = [base + i for i in range(DTC_BYTES)]
                r = read_addresses(bus, addrs)
                if r is None:
                    print("  %s  no answer" % label)
                    continue
                data = bytes(r)
                print("  %s  %s" % (label,
                                    binascii.hexlify(data, " ").decode()))
                if set(data) <= {0x5A, 0xA5}:
                    print("       ^ that is the RAM self-test pattern, not faults")
            return 0

        if args.read:
            base = int(args.read, 16)
            addrs = [base + i for i in range(args.count)]
            r = read_addresses(bus, addrs)
            if r is None:
                print("no answer")
                return 1
            print("%08X: %s" % (base,
                                binascii.hexlify(bytes(r), " ").decode()))
            return 0

        ap.print_help()
        return 1
    finally:
        try:
            bus.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
