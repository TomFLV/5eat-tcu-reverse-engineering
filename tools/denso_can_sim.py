#!/usr/bin/env python3
"""Drive the TCU with simulated CAN traffic and watch what it does with it.

The faithful version of this runs the engine controller alongside the TCU and
lets it transmit. It is also the slow version: a second bring-up, an interrupt
model and a CAN controller, all to deliver bytes whose layout is already known.
The receive table at 0x08600E gives every frame a fixed RAM buffer, so writing
the payload straight there leaves the firmware in the state the hardware would
have left it in, and the whole detour disappears.

    python tools/denso_can_sim.py --list
    python tools/denso_can_sim.py --frame 410=0000640000000000 --ticks 40
    python tools/denso_can_sim.py --sweep 410 --byte 2

What this cannot show is anything about delivery - no mailbox flags, no
interrupt, no stale-frame timeout. A control path that only runs when a frame is
fresh will not run here, and that is a limit of the shortcut, not a finding.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, REPO_WSL, WORK, WORK_WSL, SH2_WSL  # noqa: E402

import argparse
import json
import re
import struct
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(REPO, "rom-denso", "Impreza_STI_3.583_JDM2011.bin")
TABLE = 0x08600E
ENTRIES = 36

SH2 = SH2_WSL
WORK_W, WORK_L = WORK + "/cansim", WORK_WSL + "/cansim"
ROM_L = (REPO_WSL + "/rom-denso/"
         "Impreza_STI_3.583_JDM2011.bin")
TASKS = WORK_WSL + "/tasks_ctl.txt"


def receive_map():
    """CAN id -> (mailbox, buffer address), read out of the ROM."""
    rom = open(ROM, "rb").read()
    out = {}
    for i in range(ENTRIES):
        e = rom[TABLE + i * 16: TABLE + i * 16 + 16]
        if len(e) < 16:
            break
        cid = struct.unpack_from(">H", e, 0)[0]
        buf = struct.unpack_from(">I", e, 6)[0]
        if 0x100 <= cid <= 0x7FF and 0xFFFF0000 <= buf <= 0xFFFFFFFF:
            out.setdefault(cid, (e[3], buf, e[4]))
    return out


LISTING = os.path.join(REPO, "disasm-denso", "Impreza_STI_3.583_JDM2011.asm")
XREF = WORK + "/xref.json"
ROW = re.compile(r"^([0-9A-F]{8})\s+(?:[0-9A-F]{2} )+\s+_?(\S+)\s*(.*)$")
PROLOGUE = re.compile(r"^(r\d+|pr),@-r15$")


def function_starts():
    starts = []
    with open(LISTING, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = ROW.match(line.rstrip("\n"))
            if m and m.group(2) in ("mov.l", "sts.l") \
               and PROLOGUE.match(m.group(3).split(";")[0].strip()):
                starts.append(int(m.group(1), 16))
    starts.sort()
    out = []
    for a in starts:
        if not out or a - out[-1] > 2:
            out.append(a)
    return out


def frame_readers(rmap):
    """For each frame, entry points that will actually decode it.

    A frame whose decoder never runs looks inert, which is indistinguishable from
    a frame the firmware genuinely ignores, so the cross-reference is used to find
    the code that reads each buffer.

    The entry is NOT the enclosing function. Frame 0x410's reader is the function
    at 0x00012BA8, and entering there propagates nothing at all: the function
    guards its top and a cold entry takes the early exit - the same failure that
    once named five tables out of 185. Entering at 0x00012BD0, a few instructions
    ahead of the read, propagates to twenty addresses.

    So the entry is the read site backed up far enough to include the instruction
    that loads the buffer address, and both offsets are used because which one is
    the load depends on how the address reached the register. Entering
    mid-function skips whatever the guard was checking, which is a deliberate
    trade: it exercises the decode at the cost of running it in a state the
    firmware might have rejected.
    """
    import bisect
    try:
        xr = json.load(open(XREF, encoding="utf-8"))["reads"]
    except (OSError, ValueError, KeyError):
        sys.stderr.write("no xref.json - frames will run without their decoders\n")
        return {}

    out = {}
    for cid, (_mbx, buf, dlc) in rmap.items():
        sites = set()
        for off in range(dlc or 8):
            for key in ("%08X" % (buf + off), "0x%08X" % (buf + off)):
                sites.update(xr.get(key, ()))
        if sites:
            first = min(sites)
            out[cid] = [first - 4, first - 2]
    sys.stderr.write("%d of %d frames have a reader in the cross-reference\n"
                     % (len(out), len(rmap)))
    return out


def run(feed, ticks, out_name):
    os.makedirs(WORK_W, exist_ok=True)
    fp = "%s/feed.txt" % WORK_W
    with open(fp, "w", newline="\n") as fh:
        for addr, data in feed:
            fh.write("%08X %s\n" % (addr, data))
    prof = "%s/prof.csv" % WORK_W
    with open(prof, "w", newline="\n") as fh:
        fh.write("# ticks with no injected RAM, the frames carry the input\n")
        for t in range(ticks):
            fh.write("%d\n" % t)
    env = dict(os.environ)
    env["SH2_CANFEED"] = "%s/feed.txt" % WORK_L
    env["WSLENV"] = "SH2_CANFEED/u"
    r = subprocess.run(["wsl", SH2, ROM_L, "%s/prof.csv" % WORK_L,
                        "%s/%s" % (WORK_L, out_name), "@" + TASKS, "400000"],
                       capture_output=True, text=True, env=env)
    return r, "%s/%s" % (WORK_W, out_name)


def read_csv(path):
    """Column header -> list of values per tick."""
    if not os.path.exists(path):
        return {}
    rows = [l.rstrip("\n").split(",") for l in open(path) if l.strip()]
    if len(rows) < 2:
        return {}
    head = rows[0][1:]
    cols = {h: [] for h in head}
    for r in rows[1:]:
        for h, v in zip(head, r[1:]):
            cols[h].append(int(v))
    return cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--frame", action="append", default=[],
                    metavar="ID=HEXBYTES")
    ap.add_argument("--sweep", metavar="ID")
    ap.add_argument("--compare", metavar="ID",
                    help="hold the byte at two values and report what differs")
    ap.add_argument("--map", action="store_true",
                    help="every byte of every received frame, compared")
    ap.add_argument("--json")
    ap.add_argument("--low", type=int, default=0x40)
    ap.add_argument("--high", type=int, default=0x80)
    ap.add_argument("--byte", type=int, default=0)
    ap.add_argument("--with", dest="extra", action="append", default=[],
                    metavar="ADDR",
                    help="also run this routine each tick (hex). The 394-entry "
                         "control list does not include the CAN decode or the "
                         "gather, so without this a frame lands in its buffer "
                         "and nothing reads it.")
    ap.add_argument("--ticks", type=int, default=24)
    args = ap.parse_args()

    # Extra routines are appended to the controller's own list so they run after
    # it, in the order a tick would: the gather reads what the decode wrote.
    global TASKS
    if args.extra:
        os.makedirs(WORK_W, exist_ok=True)
        base = open(WORK + "/tasks_ctl.txt").read().strip()
        with open("%s/tasks.txt" % WORK_W, "w", newline="\n") as fh:
            fh.write(base + "".join("+0x%08X" % int(a, 16) for a in args.extra))
        TASKS = "%s/tasks.txt" % WORK_L

    rmap = receive_map()
    if args.list:
        print("%d frames the firmware receives, from the table at 0x%06X\n"
              % (len(rmap), TABLE))
        for cid, (mbx, buf, dlc) in sorted(rmap.items()):
            print("  0x%03X  mailbox %2d  dlc %d  -> %08X" % (cid, mbx, dlc, buf))
        return 0

    if args.sweep:
        cid = int(args.sweep, 16)
        if cid not in rmap:
            print("0x%03X is not in the receive table" % cid)
            return 1
        buf = rmap[cid][1]
        print("sweeping byte %d of frame 0x%03X (buffer %08X) over %d ticks\n"
              % (args.byte, cid, buf, args.ticks))
        # One value per tick, so a response shows up as a column that tracks it.
        os.makedirs(WORK_W, exist_ok=True)
        fp = "%s/feed.txt" % WORK_W
        prof = "%s/prof.csv" % WORK_W
        with open(prof, "w", newline="\n") as fh:
            for t in range(args.ticks):
                v = int(t * 255 / max(1, args.ticks - 1))
                fh.write("%d,%08X:1=%d\n" % (t, buf + args.byte, v))
        with open(fp, "w", newline="\n") as fh:
            fh.write("# swept through the profile instead\n")
        env = dict(os.environ)
        env["SH2_CANFEED"] = "%s/feed.txt" % WORK_L
        env["WSLENV"] = "SH2_CANFEED/u"
        r = subprocess.run(["wsl", SH2, ROM_L, "%s/prof.csv" % WORK_L,
                            "%s/sweep.csv" % WORK_L, "@" + TASKS, "400000"],
                           capture_output=True, text=True, env=env)
        sys.stderr.write(r.stdout.strip() + "\n")
        cols = read_csv("%s/sweep.csv" % WORK_W)
        moved = {h: v for h, v in cols.items() if len(set(v)) > 1}
        print("%d of %d recorded addresses respond to it\n" % (len(moved), len(cols)))
        # Monotone responders first: those are the ones carrying the value on.
        def rank(v):
            up = sum(1 for a, b in zip(v, v[1:]) if b >= a)
            return -up / max(1, len(v) - 1), -len(set(v))
        for h in sorted(moved, key=lambda h: rank(moved[h]))[:20]:
            v = moved[h]
            print("  %s  %d distinct  %s%s"
                  % (h, len(set(v)), " ".join(str(x) for x in v[:12]),
                     " ..." if len(v) > 12 else ""))
        return 0

    if args.compare:
        cid = int(args.compare, 16)
        if cid not in rmap:
            print("0x%03X is not in the receive table" % cid)
            return 1
        buf = rmap[cid][1] + args.byte
        # A sweep cannot tell a response from a counter: everything that moves
        # per tick looks like it is tracking the input, which is how a previous
        # dependency map came back claiming one input drove all 2,265 addresses.
        # Two constant holds have identical tick structure, so every counter
        # cancels and only what actually depends on the value survives.
        os.makedirs(WORK_W, exist_ok=True)
        with open("%s/feed.txt" % WORK_W, "w", newline="\n") as fh:
            fh.write("# held through the profile\n")
        img = {}
        for tag, val in (("lo", args.low), ("hi", args.high)):
            with open("%s/prof.csv" % WORK_W, "w", newline="\n") as fh:
                for t in range(args.ticks):
                    fh.write("%d,%08X:1=%d\n" % (t, buf, val))
            env = dict(os.environ)
            env["SH2_CANFEED"] = "%s/feed.txt" % WORK_L
            env["SH2_DUMP"] = "%s/%s.bin" % (WORK_L, tag)
            env["WSLENV"] = "SH2_CANFEED/u:SH2_DUMP/u"
            subprocess.run(["wsl", SH2, ROM_L, "%s/prof.csv" % WORK_L,
                            "%s/%s.csv" % (WORK_L, tag), "@" + TASKS, "400000"],
                           capture_output=True, text=True, env=env)
            img[tag] = open("%s/%s.bin" % (WORK_W, tag), "rb").read()
        lo, hi = img["lo"], img["hi"]
        if not lo or len(lo) != len(hi):
            print("no RAM dump - is SH2_DUMP supported by this build?")
            return 1
        diff = [i for i in range(len(lo)) if lo[i] != hi[i]]
        print("frame 0x%03X byte %d held at %d vs %d over %d ticks\n"
              % (cid, args.byte, args.low, args.high, args.ticks))
        print("%d of %d RAM bytes end up different\n" % (len(diff), len(lo)))
        # Runs of adjacent differing bytes are one multi-byte value, not several.
        runs_out, start = [], None
        for i in range(len(lo) + 1):
            d = i < len(lo) and lo[i] != hi[i]
            if d and start is None:
                start = i
            elif not d and start is not None:
                runs_out.append((start, i - start))
                start = None
        print("grouped into %d contiguous values:\n" % len(runs_out))
        # The Select Monitor table names 141 of these addresses. A responder with
        # a name is the whole point: it turns "byte 5 reaches 0xFFFFA69D" into a
        # statement about the car.
        names = {}
        try:
            import json
            for k, v in json.load(open(os.path.join(HERE,
                    "denso_ssm_addresses.json"), encoding="utf-8")).items():
                names[int(k, 16)] = v
        except (OSError, ValueError):
            pass
        for off, ln in runs_out[:40]:
            a = 0xFFFF0000 + off
            nm = ""
            for k in range(ln):
                if a + k in names:
                    nm = "  <- %s" % names[a + k]
                    break
            print("  %08X  %d byte%s   lo %s | hi %s%s"
                  % (a, ln, "" if ln == 1 else "s",
                     lo[off:off + ln].hex(), hi[off:off + ln].hex(), nm))
        if len(runs_out) > 40:
            print("  ... and %d more" % (len(runs_out) - 40))
        return 0

    if args.map:
        # Every byte of every received frame, held at two values, compared on the
        # whole RAM image. What comes out is a signal map derived by running the
        # firmware rather than by reading the frame layouts off a forum post.
        import json
        names = {}
        try:
            for k, v in json.load(open(os.path.join(HERE,
                    "denso_ssm_addresses.json"), encoding="utf-8")).items():
                names[int(k, 16)] = v
        except (OSError, ValueError):
            pass
        # Each frame has its own decoder, and only 0x410's was being run - which
        # is why the first pass found seven responsive bytes out of 248 and all
        # seven belonged to one frame. The cross-reference knows which code reads
        # each buffer, so each frame can bring its own decoder along.
        readers = frame_readers(rmap)
        base_tasks = TASKS
        out, total = {}, len(rmap) * 8
        done = 0
        for cid in sorted(rmap):
            buf = rmap[cid][1]
            fns = readers.get(cid, [])
            if fns:
                with open("%s/tasks.txt" % WORK_W, "w", newline="\n") as fh:
                    fh.write(open(WORK + "/tasks_ctl.txt").read().strip()
                             + "".join("+0x%08X" % f for f in fns)
                             + "+0x0002CF80")
                TASKS = "%s/tasks.txt" % WORK_L
            else:
                TASKS = base_tasks
            for b in range(8):
                done += 1
                imgs = {}
                for tag, val in (("lo", args.low), ("hi", args.high)):
                    with open("%s/prof.csv" % WORK_W, "w", newline="\n") as fh:
                        for t in range(args.ticks):
                            fh.write("%d,%08X:1=%d\n" % (t, buf + b, val))
                    env = dict(os.environ)
                    env["SH2_DUMP"] = "%s/%s.bin" % (WORK_L, tag)
                    env["WSLENV"] = "SH2_DUMP/u"
                    subprocess.run(["wsl", SH2, ROM_L, "%s/prof.csv" % WORK_L,
                                    "%s/%s.csv" % (WORK_L, tag), "@" + TASKS,
                                    "400000"], capture_output=True, env=env)
                    imgs[tag] = open("%s/%s.bin" % (WORK_W, tag), "rb").read()
                l, h = imgs["lo"], imgs["hi"]
                if len(l) != len(h):
                    continue
                d = [0xFFFF0000 + i for i in range(len(l)) if l[i] != h[i]]
                # The injected byte itself always differs; it is not a response.
                d = [a for a in d if a != buf + b]
                if not d:
                    continue
                hit = sorted({names[a] for a in d if a in names})
                ctl = ["%08X" % a for a in d if 0xFFFF8E44 <= a <= 0xFFFF8E8C]
                out["%03X.%d" % (cid, b)] = {
                    "buffer": "%08X" % (buf + b),
                    "reaches": len(d),
                    "named": hit,
                    "control_block": ctl,
                }
                sys.stderr.write("  %d/%d  %03X byte %d -> %d addresses%s\n"
                                 % (done, total, cid, b, len(d),
                                    ("  " + ", ".join(hit)) if hit else ""))
        print("\n%d of %d frame bytes reach something downstream\n"
              % (len(out), total))
        named = {k: v for k, v in out.items() if v["named"]}
        print("%d reach an address the Select Monitor table names:\n" % len(named))
        for k, v in sorted(named.items()):
            print("  frame 0x%s byte %s  ->  %s" % (k.split(".")[0], k.split(".")[1],
                                                    ", ".join(v["named"])))
        ctl = {k: v for k, v in out.items() if v["control_block"]}
        print("\n%d reach the control block at 0xFFFF8E44-8E8C:\n" % len(ctl))
        for k, v in sorted(ctl.items()):
            print("  frame 0x%s byte %s  ->  %s" % (k.split(".")[0], k.split(".")[1],
                                                    ", ".join(v["control_block"])))
        if args.json:
            with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(out, fh, indent=1, sort_keys=True)
            print("\n-> %s" % args.json)
        return 0

    feed = []
    for spec in args.frame:
        sid, _, data = spec.partition("=")
        cid = int(sid, 16)
        if cid not in rmap:
            print("0x%03X is not in the receive table - see --list" % cid)
            return 1
        feed.append((rmap[cid][1], data))
    if not feed:
        print("nothing to send; use --frame ID=HEXBYTES or --sweep ID")
        return 1

    r, out = run(feed, args.ticks, "out.csv")
    sys.stderr.write(r.stdout.strip() + "\n")
    cols = read_csv(out)
    moved = {h: v for h, v in cols.items() if len(set(v)) > 1}
    print("\n%d addresses changed while those frames were being delivered"
          % len(moved))
    for h in sorted(moved)[:20]:
        print("  %s  %s" % (h, " ".join(str(x) for x in moved[h][:12])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
