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

    python3 tools/bench/ssm_can.py --dtc            # faults, decoded to P-codes
    python3 tools/bench/ssm_can.py --adjustments    # the writable trim values
    python3 tools/bench/ssm_can.py --read 00009C --count 4
    python3 tools/bench/ssm_can.py --probe          # is anything answering at all

ADDRESSES HERE ARE LOGICAL, NOT RAM. This is the thing most likely to trip someone
up, and it tripped this tool up for a long time. An SSM address is a logical one
Subaru keeps stable across control units and model years; the controller translates
it to wherever that datum lives in its own RAM. So 0x00009C is the first fault byte
on every Subaru TCU, whatever the CPU and whether or not its ROM is one of the 25 in
this repository.

Reading a firmware RAM address instead does not work, and fails quietly rather than
loudly: an SSM address is three bytes, so 0xFFFF8876 goes out as 0xFF8876 and returns
whatever happens to live there.
"""

import argparse
import binascii
import json
import os
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

# The fault arrays, addressed the way a scan tool has to address them.
#
# Earlier revisions sent 0xFFFF8876 and 0xFFFF21D6, the Denso internal record
# addresses from FINDINGS 81. That was wrong twice: an SSM address is three bytes, so
# those truncate to 0xFF8876 and 0xFF21D6 and ask for somewhere unrelated, and the
# internal records are not what the controller serves anyway - it serves the output
# mirror they get gathered into.
#
# These are SSM LOGICAL addresses, resolved from the firmware's own 512-entry
# translation table. Addressing logically needs no per-firmware map: the controller
# does the translation, so 0x00009C is the first fault byte on every Subaru TCU,
# including units whose ROM is not among the 25 in this repository. The historic
# block for each sits at the paired address.
DTC_BLOCKS = [(0x00009C, 0x0000BC), (0x00009D, 0x0000BD), (0x0000A6, 0x0000C6),
              (0x0000F1, 0x0000F5), (0x0000F2, 0x0000F6), (0x0000F3, 0x0000F7),
              (0x000123, 0x00012B), (0x000124, 0x00012C), (0x000125, 0x00012D),
              (0x00012A, 0x000132), (0x000175, 0x00017C)]

TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)


def _load(name, default=None):
    try:
        with open(os.path.join(TOOLS, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        if default is None:
            raise
        return default


#: Typographic punctuation the manual uses, and its plain equivalent. The extracted
#: data is correct and stays that way - this is only for printing. A Windows console
#: in its default code page renders a curly quote as a replacement character, which
#: on a bench looks exactly like corrupted data at the moment you least want doubt.
_PUNCT = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
          0x2013: "-", 0x2014: "-", 0x2026: "...", 0x00B0: " deg"}


def plain(text):
    return (text or "").translate(_PUNCT)


def scale(raw, formula, width):
    """Apply a scaling expression to a raw reading.

    The expressions are a tiny language applied to an implicit x, and only the forms
    the transmission adjustments actually use are handled: an offset (-100), an
    offset then a divisor (-100/50), a multiplier (*1), and a signed reinterpretation
    (s16/50). Anything else returns None and the caller shows the raw value, which is
    the honest outcome - a wrong number here would be believed.

    s16 is not decoration. 0x171 is a signed torque correction whose stated minimum
    is 63535, which is -2001 as a signed 16-bit value. Compared unsigned it looks
    like a minimum above its own maximum, and every reading looks out of range.
    """
    if not formula:
        return None
    f = formula.strip()
    if f.startswith("s"):
        bits = 16 if f.startswith("s16") else 8
        if raw >= 1 << (bits - 1):
            raw -= 1 << bits
        f = f[3:] if f.startswith("s16") else f[2:]
        if not f:
            return float(raw)
    try:
        if f.startswith("-"):
            off, _, div = f[1:].partition("/")
            v = raw - float(off)
            return v / float(div) if div else v
        if f.startswith("*"):
            mul, _, div = f[1:].partition("/")
            v = raw * float(mul)
            return v / float(div) if div else v
        if f.startswith("/"):
            return raw / float(f[1:])
    except ValueError:
        return None
    return None


def signed_range(lo, hi, formula, width):
    """A stated min/max, reinterpreted signed when the formula says it is."""
    if formula and formula.strip().startswith("s"):
        bits = 16 if formula.strip().startswith("s16") else 8
        lo = lo - (1 << bits) if lo >= 1 << (bits - 1) else lo
        hi = hi - (1 << bits) if hi >= 1 << (bits - 1) else hi
    return (lo, hi) if lo <= hi else (hi, lo)


def _bit_map():
    """Which bit of each fault block is which code, from the work directory.

    Not shipped in this repository. The block ADDRESSES are this project's own, out
    of the firmware's translation table, so they stay. Which bit within a block
    carries which code is derived from a third-party definition set, so it lives in
    the work directory and the tool degrades to printing raw bytes without it.
    """
    sys.path.insert(0, os.path.abspath(TOOLS))
    try:
        from workdir import WORK
    except ImportError:
        return {}
    try:
        with open(os.path.join(WORK, "dtc_ssm_map.json"), encoding="utf-8") as fh:
            m = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {int(b["current"], 16): b["bits"] for b in m.get("blocks", [])}


def _adjustments():
    """Writable adjustment definitions, from the work directory if present."""
    sys.path.insert(0, os.path.abspath(TOOLS))
    try:
        from workdir import WORK
        with open(os.path.join(WORK, "dtc_ssm_map.json"), encoding="utf-8") as fh:
            return json.load(fh).get("adjustments", [])
    except (ImportError, OSError, ValueError):
        return []


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
                    help="read both fault arrays and decode them to P-codes")
    ap.add_argument("--adjustments", action="store_true",
                    help="read the writable line-pressure and AWD trim values")
    ap.add_argument("--read", metavar="HEXADDR")
    ap.add_argument("--count", type=int, default=1)
    args = ap.parse_args()

    bus = open_bus(args.channel, args.bitrate)
    try:
        if args.probe:
            print("listening for any diagnostic traffic on 0x%03X and 0x%03X,"
                  " then asking\n" % (REQ_ID, RESP_ID))
            r = read_addresses(bus, [0x00009C])   # first fault byte, logical
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
            cond = _load("dtc_conditions.json", {})
            bits = _bit_map()
            cur = [c for c, _ in DTC_BLOCKS]
            hist = [h for _, h in DTC_BLOCKS]
            print("reading %d fault blocks, current and historic\n" % len(DTC_BLOCKS))
            got = {}
            for label, addrs in (("current", cur), ("historic", hist)):
                r = read_addresses(bus, addrs)
                if r is None or isinstance(r, tuple):
                    print("  %-8s no answer" % label)
                    continue
                data = bytes(r)
                got[label] = data
                print("  %-8s %s" % (label,
                                     binascii.hexlify(data, " ").decode()))
                # Twelve bytes of 0x5A/0xA5 decode into a page of plausible faults
                # if taken at face value. That pattern is the RAM self-test, and it
                # was nearly reported as twenty real codes once already.
                if data and set(data) <= {0x5A, 0xA5}:
                    print("           ^ RAM self-test pattern, not faults")
                    got.pop(label)

            if not got:
                return 1
            print()
            if not bits:
                print("  Raw bytes only. Which bit of a block carries which code is")
                print("  not resolvable from anything in this repository.")
                return 0
            any_set = False
            for label, data in got.items():
                for (c, _h), byte in zip(DTC_BLOCKS, data):
                    for bit, code in sorted(bits.get(c, {}).items(),
                                            key=lambda x: int(x[0])):
                        # Bits are numbered 1-8, least significant first.
                        if not byte & (1 << (int(bit) - 1)):
                            continue
                        any_set = True
                        info = cond.get(code) or {}
                        print("  %-8s %-6s  block %06X bit %s  %s"
                              % (label, code, c, bit, plain(info.get("item", ""))))
                        if info.get("cause"):
                            print("           sets when: %s"
                                  % plain(info["cause"])[:96])
            if not any_set:
                print("  no faults set in either array.")
            return 0

        if args.adjustments:
            adj = _adjustments()
            if not adj:
                print("No adjustment definitions available.")
                return 1
            print("reading %d writable adjustments\n" % len(adj))
            for a in adj:
                addrs = [int(a["addr_low"], 16)]
                if a["addr_high"]:
                    addrs.insert(0, int(a["addr_high"], 16))
                r = read_addresses(bus, addrs)
                if r is None or isinstance(r, tuple):
                    print("  %-6s %-38s no answer"
                          % (a["addr_low"], plain(a["title"])[:38]))
                    continue
                raw = int.from_bytes(bytes(r), "big")
                width = len(addrs) * 8
                lo, hi = signed_range(a["raw_min"], a["raw_max"], a["formula"],
                                      width)
                sraw = raw
                if a["formula"] and a["formula"].strip().startswith("s") \
                        and raw >= 1 << (width - 1):
                    sraw = raw - (1 << width)
                flag = "" if lo <= sraw <= hi else \
                    "  <- outside the %d..%d the definition allows" % (lo, hi)
                v = scale(raw, a["formula"], width)
                shown = ("%8.2f" % v) if v is not None else ("%8d raw" % raw)
                print("  %-6s %-38s %s %-5s (default %d)%s"
                      % (a["addr_low"], plain(a["title"])[:38], shown,
                         plain(a["unit"]), a["raw_default"], flag))
            print("\nThese are writable over SSM, but this tool only reads. Writing "
                  "is\nnot implemented and should not be until reads are trusted.")
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
