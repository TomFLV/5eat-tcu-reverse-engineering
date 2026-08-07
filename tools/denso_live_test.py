#!/usr/bin/env python3
"""Drive the simulated TCU and watch what it does, tick by tick.

Everything up to now has measured the controller one question at a time: does this
byte reach that address, does this table have a reader. None of it answers the
question a tuner actually asks - put the car in this situation and what does the
transmission do?

This runs a scripted drive against the firmware and prints the controller's own
instrument panel each tick: gear, the eight solenoid currents and pressures,
turbine and wheel speeds, using the 141 addresses the Select Monitor table names.

    python tools/denso_live_test.py --profile accelerate
    python tools/denso_live_test.py --profile accelerate --watch "Gear Position"
    python tools/denso_live_test.py --list-profiles

WHAT THIS IS NOT. The peripheral model provides five status bits and nothing else,
there are no interrupts, and inputs are written straight into the RAM the sensor
paths would have filled. So this exercises the control logic on plausible inputs;
it does not prove the firmware behaves this way in a car. Where a result matters,
the thing to do is trace it back to the instruction that produced it, which is
what --explain is for.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import json
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SSM = os.path.join(HERE, "denso_ssm_addresses.json")

SH2 = SH2_WSL
ROM_L = (REPO_WSL + "/rom-denso/"
         "Impreza_STI_3.583_JDM2011.bin")
WIN, LIN = WORK + "/live", WORK_WSL + "/live"
TASKS_W = WORK + "/tasks_ctl.txt"

# Inputs go into the CAN receive buffers, which is where a real car puts them.
#
# The first version of this wrote to the 0xFFFFA0xx block because that is where
# the Select Monitor names live. That block is the controller's OUTPUT mirror -
# what it publishes to a scan tool - so every value written there was overwritten
# by the firmware on the same tick. ATF temperature read 0, 1, 1, 1... and gear
# never moved, which looked like the transmission ignoring its inputs and was
# actually the harness injecting into the wrong end of the controller.
#
# These addresses come from the signal map in section 77c: each was established
# by holding a frame byte at two values and seeing what changed.
INPUTS = {
    "pedal":        0xFFFF301C,   # frame 0x412 byte 0 -> Accelerator Pedal Travel
    "engine_speed": 0xFFFF3011,   # frame 0x410 byte 5 -> Engine Speed
    "gear_request": 0xFFFF30A6,   # frame 0x491 byte 2 -> Gear Position
    "speed_a":      0xFFFF301F,   # frame 0x412 byte 3 -> 73 addresses downstream
    "speed_b":      0xFFFF3020,   # frame 0x412 byte 4 -> 59 addresses downstream
    "torque":       0xFFFF3010,   # frame 0x410 byte 4 -> control block 0xFFFF8E48
}

# The decoders that move a receive buffer into the values the control code reads.
# Without these a frame lands in its buffer and nothing looks at it - which is
# exactly what the first CAN map run measured, and reported as 7 responsive bytes
# out of 248. Entry addresses are the read site backed up two instructions, not
# the function start, because the function guards its top (section 77c).
#
# Each FRAME has its own decoder, so injecting into 0x412 and 0x491 while running
# only 0x410's decoder leaves those two frames sitting in their buffers unread -
# which is why gear position did not move on the first attempt and looked like the
# controller ignoring a gear request. Derived per frame rather than listed, so
# adding an input cannot silently forget its decoder.
FRAMES_USED = (0x410, 0x412, 0x491)


def decoder_entries():
    sys.path.insert(0, HERE)
    import denso_can_sim as sim
    readers = sim.frame_readers(sim.receive_map())
    out = []
    for cid in FRAMES_USED:
        for e in readers.get(cid, []):
            out.append("0x%08X" % e)
    out.append("0x0002CF80")          # the gather, last: it reads what they wrote
    return out

# A tuple per tick: pedal, engine speed, front/rear wheel speed, ATF temp.
# Values are the byte the firmware reads, not engineering units - the scaling of
# most of these is not established, and inventing one would put a number on the
# screen that looks authoritative and means nothing.
# (pedal, engine speed, road speed, gear, engine torque)
#
# Gear is written to the frame as gear << 4. Holding byte 2 of frame 0x491 at 0x40
# against 0x80 moves Gear Position from 4 to 8, so the gear occupies the high
# nibble; sending a plain 1 or 5 sets gear 0 and nothing downstream moves at all.
# That looked exactly like the controller ignoring the gear request.
def _gear(n):
    return (n & 0xF) << 4


PROFILES = {
    "idle": [(0, 20, 0, _gear(1), 10)] * 12,
    "accelerate": [(p, min(255, 20 + p), min(255, p), _gear(1 + p // 40),
                    min(255, p)) for p in range(0, 200, 8)],
    "cruise": [(40, 90, 120, _gear(5), 60)] * 16,
    "kickdown": ([(30, 80, 140, _gear(5), 50)] * 6
                 + [(220, 200, 150, _gear(3), 220)] * 10
                 + [(30, 90, 130, _gear(5), 50)] * 6),
    "coast_down": [(0, max(20, 200 - t * 12), max(0, 200 - t * 12),
                    _gear(max(1, 5 - t // 3)), 5) for t in range(16)],
    "cold_start": [(20, 40, 10, _gear(1), 20)] * 14,
}


def names():
    out = {}
    for k, v in json.load(open(SSM, encoding="utf-8")).items():
        out.setdefault(v, []).append(int(k, 16))
    return out


def write_profile(path, ticks, extra=None):
    with open(path, "w", newline="\n") as fh:
        for t, row in enumerate(ticks):
            pedal, rpm, speed, gear, torque = row
            cells = [
                "%08X:1=%d" % (INPUTS["pedal"], pedal),
                "%08X:1=%d" % (INPUTS["engine_speed"], rpm),
                "%08X:1=%d" % (INPUTS["speed_a"], speed),
                "%08X:1=%d" % (INPUTS["speed_b"], speed),
                "%08X:1=%d" % (INPUTS["gear_request"], gear),
                "%08X:1=%d" % (INPUTS["torque"], torque),
            ]
            for addr, val in (extra or {}).items():
                cells.append("%08X:1=%d" % (addr, val))
            fh.write("%d,%s\n" % (t, ",".join(cells)))


def task_list():
    """The controller's tasks, with the frame decoders appended."""
    os.makedirs(WIN, exist_ok=True)
    base = open(TASKS_W).read().strip()
    with open("%s/tasks.txt" % WIN, "w", newline="\n") as fh:
        fh.write(base + "".join("+" + d for d in decoder_entries()))
    return "@%s/tasks.txt" % LIN


def run(profile_path, out_csv, env_extra=None):
    env = dict(os.environ)
    keys = []
    for k, v in (env_extra or {}).items():
        env[k] = v
        keys.append(k)
    if keys:
        env["WSLENV"] = ":".join(k + "/u" for k in keys)
    r = subprocess.run(["wsl", SH2, ROM_L, profile_path, out_csv,
                        task_list(), "400000"],
                       capture_output=True, text=True, env=env)
    return r


def read_csv(path):
    if not os.path.exists(path):
        return [], {}
    rows = [l.rstrip("\n").split(",") for l in open(path) if l.strip()]
    if len(rows) < 2:
        return [], {}
    head = rows[0][1:]
    cols = {h: [int(v) for v in (r[1:][i] for r in rows[1:])]
            for i, h in enumerate(head)}
    return head, cols


# Fault conditions worth provoking, as (description, input overrides). Each is a
# situation the firmware has a reason to object to, not merely an odd number: a
# sensor reading zero while the car is plainly moving, a gear the box does not
# have, a torque figure the engine cannot produce.
FAULTS = {
    "turbine_dead":  ("turbine input stuck at zero while the road speed is high",
                      {0xFFFF301F: 0, 0xFFFF3020: 0}),
    "gear_invalid":  ("a gear selection outside 1-6",
                      {0xFFFF30A6: 0xF0}),
    "engine_stall":  ("engine speed zero while driving",
                      {0xFFFF3011: 0}),
    "torque_max":    ("engine torque pinned at full scale",
                      {0xFFFF3010: 0xFF}),
    "speed_mismatch": ("the two road speed channels disagreeing wildly",
                       {0xFFFF301F: 10, 0xFFFF3020: 240}),
}


# The diagnostic layout, read out of the firmware rather than assumed.
#
#   0x0008624C   44 uint16 codes, each the P-number in hex
#   0x000864A8   one 5-byte record per code: [enable, group, mask, ?, enable]
#   0xFFFF21D6   the status bytes in RAM, one per group
#
# The reporting loop at 0x0007D4F8 does exactly this: add the group to
# 0xFFFF21D6, read the byte, AND it with the record's mask, and if what is left
# is non-zero fetch the code and mask it with 0x3FFF. So a DTC is set when
#
#     ram[0xFFFF21D6 + record.group] & record.mask
#
# and that is a fact taken from the instruction sequence, not a guess about how
# diagnostics usually work.
DTC_CODES = 0x0008624C
DTC_RECORDS = 0x000864A8
DTC_STATUS = 0xFFFF21D6
DTC_COUNT = 44
ROM_W = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")


def dtc_map():
    """[(code, group, mask)] straight out of the ROM."""
    import struct
    rom = open(ROM_W, "rb").read()
    out = []
    for i in range(DTC_COUNT):
        code = struct.unpack_from(">H", rom, DTC_CODES + i * 2)[0]
        rec = rom[DTC_RECORDS + i * 5: DTC_RECORDS + i * 5 + 5]
        if len(rec) < 3 or not code:
            continue
        out.append(("P%04X" % (code & 0x3FFF), rec[1], rec[2]))
    return out


def dtcs_set(image):
    """Which DTCs are latched in this RAM image."""
    out = []
    for code, group, mask in dtc_map():
        off = DTC_STATUS - 0xFFFF0000 + group
        if off < len(image) and image[off] & mask:
            out.append(code)
    return out


def fault_scan(base_profile, verbose=False):
    """Run each fault beside a clean drive and report what only the fault changed.

    The comparison is against the SAME profile without the override, so what is
    reported is the effect of the fault and not the effect of driving. A single
    faulted run on its own would show hundreds of addresses moving and say nothing.
    """
    os.makedirs(WIN, exist_ok=True)
    ticks = PROFILES[base_profile]

    def image(extra, tag):
        write_profile("%s/f_%s.csv" % (WIN, tag), ticks, extra)
        run("%s/f_%s.csv" % (LIN, tag), "%s/f_%s.out" % (LIN, tag),
            {"SH2_DUMP": "%s/f_%s.bin" % (LIN, tag)})
        p = "%s/f_%s.bin" % (WIN, tag)
        return open(p, "rb").read() if os.path.exists(p) else b""

    clean = image(None, "clean")
    if not clean:
        print("the clean run produced no RAM image")
        return {}

    sig = names()
    addr_name = {}
    for n, addrs in sig.items():
        for a in addrs:
            addr_name[a] = n

    out = {}
    for key, (desc, extra) in sorted(FAULTS.items()):
        faulted = image(extra, key)
        if len(faulted) != len(clean):
            continue
        diff = [0xFFFF0000 + i for i in range(len(clean))
                if clean[i] != faulted[i]]
        # The injected addresses themselves are not evidence of anything.
        diff = [a for a in diff if a not in extra]
        out[key] = (desc, diff)
        named = sorted({addr_name[a] for a in diff if a in addr_name})
        print("\n  %-15s %s" % (key, desc))
        print("      %d address(es) differ from the clean drive" % len(diff))
        was, now = dtcs_set(clean), dtcs_set(faulted)
        new = [c for c in now if c not in was]
        if new:
            print("      DTC SET: %s" % ", ".join(new))
        elif now:
            print("      DTCs already set in the clean drive too: %s"
                  % ", ".join(now))
        else:
            print("      no DTC latched")
        if named:
            print("      named: %s" % ", ".join(named))
        for a in diff[: (None if verbose else 8)]:
            print("        %08X  clean %3d  faulted %3d%s"
                  % (a, clean[a - 0xFFFF0000], faulted[a - 0xFFFF0000],
                     "  <- " + addr_name[a] if a in addr_name else ""))
        if not verbose and len(diff) > 8:
            print("        ... and %d more" % (len(diff) - 8))
    return out


def explain(addr, profile, extra=None):
    """Which instruction wrote this address, and what function was it in.

    A differing byte is a symptom. SH2_WATCH reports every write to an address
    with the pc that made it, which turns "something set this" into a line of the
    listing - the point of the whole exercise being to get back to real code.
    """
    os.makedirs(WIN, exist_ok=True)
    write_profile("%s/x.csv" % WIN, PROFILES[profile], extra)
    r = run("%s/x.csv" % LIN, "%s/x.out" % LIN,
            {"SH2_WATCH": "%08X" % addr})
    pcs = {}
    for line in r.stderr.splitlines():
        m = re.match(r"WRITE ([0-9A-F]{8}) = ([0-9A-F]{2})\s+by pc ([0-9A-F]{8})",
                     line)
        if m:
            pcs.setdefault(m.group(3), []).append(m.group(2))
    if not pcs:
        print("  nothing wrote %08X during this drive" % addr)
        return
    print("  %08X is written by %d instruction(s):" % (addr, len(pcs)))
    listing = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
    src = {}
    if os.path.exists(listing):
        with open(listing, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if len(line) > 8 and line[:8] in pcs:
                    src[line[:8]] = line.rstrip()
    for pc, vals in sorted(pcs.items(), key=lambda kv: -len(kv[1])):
        print("    pc %s  %d write(s), values %s"
              % (pc, len(vals), " ".join(sorted(set(vals))[:6])))
        if pc in src:
            print("       %s" % src[pc].strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="accelerate")
    ap.add_argument("--faults", action="store_true",
                    help="inject each fault beside a clean drive and diff")
    ap.add_argument("--explain", metavar="ADDR",
                    help="find the instruction that writes this RAM address")
    ap.add_argument("--list-profiles", action="store_true")
    ap.add_argument("--watch", action="append", default=[],
                    help="signal name to follow, repeatable")
    ap.add_argument("--all", action="store_true",
                    help="show every named signal, not just those that move")
    args = ap.parse_args()

    if args.list_profiles:
        for k, v in sorted(PROFILES.items()):
            print("  %-12s %d ticks" % (k, len(v)))
        return 0
    if args.profile not in PROFILES:
        print("unknown profile %r - try --list-profiles" % args.profile)
        return 1

    if args.explain:
        explain(int(args.explain, 16), args.profile)
        return 0

    if args.faults:
        print("faults injected against the %r drive, each compared with the same "
              "drive unfaulted\n" % args.profile)
        fault_scan(args.profile, args.all)
        return 0

    os.makedirs(WIN, exist_ok=True)
    write_profile("%s/drive.csv" % WIN, PROFILES[args.profile])
    r = run("%s/drive.csv" % LIN, "%s/live.csv" % LIN)
    sys.stderr.write(r.stdout.strip() + "\n")
    head, cols = read_csv("%s/live.csv" % WIN)
    if not head:
        print("the drive produced no output")
        return 1

    sig = names()
    ticks = len(next(iter(cols.values()))) if cols else 0
    print("\nprofile %r, %d ticks, %d addresses recorded\n"
          % (args.profile, ticks, len(head)))

    shown = 0
    print("  %-38s %s" % ("signal", "value each tick"))
    for name in sorted(sig):
        if args.watch and not any(w.lower() in name.lower() for w in args.watch):
            continue
        # A signal is mirrored at up to five addresses; show the one that moves,
        # since a stale copy sitting at zero says nothing about the drive.
        best, series = None, None
        for a in sig[name]:
            key = "%08X" % a
            if key in cols and len(set(cols[key])) > (0 if args.all else 1):
                if series is None or len(set(cols[key])) > len(set(series)):
                    best, series = key, cols[key]
        if series is None:
            continue
        print("  %-38s %s" % ("%s @%s" % (name, best),
                              " ".join("%3d" % v for v in series[:18])))
        shown += 1

    if not shown:
        print("  nothing named responded to this drive.")
        print("  That is a result, not an error: the inputs written here are the")
        print("  addresses the control code reads, and if none of the named")
        print("  outputs move, the control path being exercised does not reach")
        print("  them. --all shows the constant ones too.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
