#!/usr/bin/env python3
"""Build a RomRaider logger definition for the 5EAT TCUs.

The editor definition describes ROM tables. This describes what the Select Monitor
can read out of a running unit, which is a different question and needs a different
file.

Two things make it possible to do properly rather than by guesswork:

  * Each ROM holds a 512-entry table mapping Select Monitor address to the RAM
    address it reads, with a dummy address in every unsupported slot. So support is
    stated by the firmware itself, per image, instead of being inferred from the
    init response flagbytes the way a generic definition must.

  * FreeSSM's measuring-block list names those addresses and gives their units and
    conversions.

The unit identifier RomRaider matches against is read from the table itself:
parameters 1 to 5 answer with it. The M32R copies it from ROM 0x802A, the Denso
points straight at ROM at an address that moves between images. rimwall gave the
M32R location, forum topic 13725 post 379.

Raw memory is readable too. The request handler routes addresses below 0x200
through the translation table and everything else to a direct read, guarded only
for ROM space, so a RAM address can be logged by naming it. That is what the
lock-up entries below are for: sections 29 and 41 narrowed the torque converter
channel to two candidates whose drivers are identical in code, and logging both
duty cycles against gear separates them.

    python tools/generate_logger_def.py

Writes definitions/5eat_tcu_logger.xml.
"""

import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SSM_JSON = os.path.join(HERE, "ssm_parameters.json")
OUT = os.path.join(REPO, "definitions", "5eat_tcu_logger.xml")

ID_OFFSET, ID_LEN = 0x802A, 5

# The candidates for the torque converter clutch, from FINDINGS section 29. Their
# software drivers are exact mirrors, so only observation separates them.
LOCKUP = [
    ("TIO5 duty (lock-up candidate A)", 0x804EB2),
    ("TIO7 duty (lock-up candidate B)", 0x804EB6),
]

# FreeSSM writes a conversion as the operations applied to the raw value. Only
# forms that translate unambiguously are emitted; anything else ships as the raw
# value with its units, which is honest and still loggable.
CONV = [
    (re.compile(r"^\*(\d+)$"),            lambda m: "x*%s" % m.group(1)),
    (re.compile(r"^/(\d+)$"),             lambda m: "x/%s" % m.group(1)),
    (re.compile(r"^-(\d+)$"),             lambda m: "x-%s" % m.group(1)),
    (re.compile(r"^\+(\d+)$"),            lambda m: "x+%s" % m.group(1)),
    (re.compile(r"^/(\d+)\*(\d+)$"),      lambda m: "x/%s*%s" % (m.group(1), m.group(2))),
    (re.compile(r"^\*(\d+)/(\d+)$"),      lambda m: "x*%s/%s" % (m.group(1), m.group(2))),
]


def expression(conv):
    if not conv:
        return "x", False
    conv = conv.strip()
    for pat, fn in CONV:
        m = pat.match(conv)
        if m:
            return fn(m), True
    return "x", False


def unit_ids(data):
    """firmware filename -> the identifier the Select Monitor reports.

    Both families answer parameters 1 to 5 with the five identifier bytes, but they
    reach them differently: the M32R copies them from ROM 0x802A into the staging
    buffer, so its table points at RAM, while the Denso table points at the ROM
    bytes directly and at an address that moves between images. So take the address
    from the table where it points into ROM, and fall back to the fixed M32R offset
    where it does not.
    """
    out, m32r = {}, set()
    for folder in ("rom", "rom-denso"):
        for path in glob.glob(os.path.join(REPO, folder, "*.bin")):
            name = os.path.basename(path)
            info = data.get(name)
            if not info:
                continue
            rows = {r["ssm"]: r["ram"] for r in info["rows"]}
            first = rows.get(1)
            offset = first if first is not None and first < 0x100000 else ID_OFFSET
            with open(path, "rb") as fh:
                fh.seek(offset)
                ident = "".join("%02X" % b for b in fh.read(ID_LEN))
            if len(ident) == ID_LEN * 2:
                out[name] = ident
                if folder == 'rom':
                    m32r.add(ident)
    return out, m32r


def collect_switches(data, ids):
    """(ssm, bit, name, states) -> the unit ids whose table answers that address.

    A switch byte carries up to eight named signals, one per bit - range signals,
    solenoid states, kickdown, ABS, the lamps. Eleven such bytes per Denso image
    hold 81 switches between them, and the first version of this generator dropped
    all of them because they do not fit the measuring-block shape.

    RomRaider models a switch as its own element with a byte and a bit rather than
    as a parameter with a conversion, which is why they need emitting separately.
    """
    out = {}
    for rom, info in data.items():
        uid = ids.get(rom)
        if not uid:
            continue
        for r in info["rows"]:
            for s in r.get("switches") or []:
                # FreeSSM numbers flagbits 1 to 8; RomRaider wants 0 to 7 and
                # rejects the whole file with "Bit must be between 0 and 7
                # inclusive" if given an 8. Convert rather than clamp.
                bit = s["bit"] - 1
                if not 0 <= bit <= 7:
                    continue
                key = (r["ssm"], bit, s["name"], s.get("states") or "Off/On")
                out.setdefault(key, set()).add(uid)
    return out


def collect(data, ids):
    """(ssm, name, unit, conv, length) -> sorted list of unit ids supporting it."""
    params = {}
    for rom, info in data.items():
        uid = ids.get(rom)
        if not uid:
            continue
        rows = {r["ssm"]: r for r in info["rows"]}
        for ssm, r in rows.items():
            if not r.get("name"):
                continue
            # A 16-bit quantity occupies two Select Monitor addresses. Emit it once,
            # at the lower address with length 2, rather than as two useless halves.
            half = r.get("half")
            if half == "low":
                continue
            length = 1
            if half == "high":
                if (ssm + 1) not in rows or rows[ssm + 1].get("name") != r["name"]:
                    continue
                length = 2
            key = (ssm, r["name"], r.get("unit") or "", r.get("conv") or "", length)
            params.setdefault(key, set()).add(uid)
    return params


def main():
    if not os.path.exists(SSM_JSON):
        sys.stderr.write("run tools/map_ssm_parameters.py first\n")
        return 1
    data = json.load(open(SSM_JSON, encoding="utf-8"))
    ids, m32r_ids = unit_ids(data)
    known = sorted({v for k, v in ids.items() if k in data})
    if not known:
        sys.stderr.write("no firmware in %s matched a ROM in rom/\n" % SSM_JSON)
        return 1

    params = collect(data, ids)

    logger = ET.Element("logger", version="5eat-tcu")
    proto = ET.SubElement(
        logger, "protocol", id="SSM", baud="4800", databits="8", stopbits="1",
        parity="0", connect_timeout="2000", send_timeout="55")
    transport = ET.SubElement(
        proto, "transport", id="iso9141", name="K-Line",
        desc="Subaru Select Monitor over the diagnostic K-line")
    ET.SubElement(transport, "module", id="TCU", address="0x18", tester="0xF0",
                  desc="Transmission Control Unit", fastpoll="true")

    untranslated = 0
    for n, (key, uids) in enumerate(sorted(params.items()), 1):
        ssm, name, unit, conv, length = key
        expr, ok = expression(conv)
        if not ok:
            untranslated += 1
        desc = "Select Monitor address 0x%03X" % ssm
        if not ok and conv:
            desc += ". Raw value: FreeSSM gives the conversion as '%s'" % conv
        ep = ET.SubElement(proto, "ecuparam", id="P%03d" % n, name=name,
                           desc=desc, target="2")
        ecu = ET.SubElement(ep, "ecu", id=",".join(sorted(uids)))
        addr = ET.SubElement(ecu, "address")
        if length > 1:
            addr.set("length", str(length))
        addr.text = "0x%06X" % ssm
        convs = ET.SubElement(ep, "conversions")
        ET.SubElement(convs, "conversion", units=(unit or "raw"), expr=expr,
                      format="0.00" if "/" in expr else "0")

    # Switches. RomRaider takes these as their own element with a byte and a bit,
    # not as parameters with a conversion, so they cannot go through the loop above.
    # They are worth having: range signals, solenoid states, kickdown, ABS and the
    # lamps are all here, and none of it was being logged.
    switches = collect_switches(data, ids)
    for n, (key, uids) in enumerate(sorted(switches.items()), 1):
        ssm, bit, name, states = key
        sw = ET.SubElement(proto, "switch", id="S%03d" % n, name=name,
                           desc="Select Monitor address 0x%03X bit %d. States: %s"
                                % (ssm, bit, states),
                           byte="0x%06X" % ssm, bit=str(bit),
                           target="2", storagetype="uint8")
        ET.SubElement(sw, "conversions")

    # Raw RAM reads: the two lock-up candidates. These are M32R addresses, so they
    # are offered only to M32R units - pointing a Denso unit at them would read an
    # unrelated part of its address space and report a plausible-looking number.
    for n, (name, ram) in enumerate(LOCKUP, 1):
        ep = ET.SubElement(
            proto, "ecuparam", id="LU%d" % n, name=name,
            desc="Raw read of RAM 0x%06X. The torque converter clutch is driven by "
                 "one of two timer channels whose code paths are identical "
                 "(FINDINGS section 29); logging both against gear identifies which. "
                 "Addresses at or above 0x200 are read directly by the firmware "
                 "rather than through the Select Monitor translation table."
                 % ram,
            target="2")
        ecu = ET.SubElement(ep, "ecu", id=",".join(sorted(m32r_ids)))
        ET.SubElement(ecu, "address").text = "0x%06X" % ram
        convs = ET.SubElement(ep, "conversions")
        ET.SubElement(convs, "conversion", units="duty (raw)", expr="x", format="0")

    try:
        ET.indent(logger, space=" ")
    except AttributeError:
        pass
    xml = ET.tostring(logger, encoding="unicode")
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write("<!--\n  Select Monitor logger definition for the Subaru 5EAT TCU,\n"
                 "  Hitachi M32R family. Generated by tools/generate_logger_def.py -\n"
                 "  edit that, not this.\n\n"
                 "  Parameter support is taken from each firmware's own Select Monitor\n"
                 "  address table rather than inferred from the init response.\n-->\n")
        fh.write(xml + "\n")

    print("%d parameters, %d switches, across %d firmwares -> %s"
          % (len(params), len(switches), len(known), OUT))
    if untranslated:
        print("%d shipped as raw values: FreeSSM's conversion was not a simple form"
              % untranslated)
    print("%d raw RAM parameters for the lock-up channels" % len(LOCKUP))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
