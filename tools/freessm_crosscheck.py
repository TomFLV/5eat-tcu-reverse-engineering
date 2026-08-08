#!/usr/bin/env python3
"""Check the firmware against FreeSSM, and name RAM addresses from the agreement.

Two independent halves fit together. The firmware carries a translation table - SSM
logical address to internal RAM address, 512 entries per ROM, which is what
ssm_parameters.json holds. FreeSSM carries SSM logical address to name, unit and
scaling. Joining on the SSM address puts a name on a RAM address, from a source with
no connection to any of this firmware work.

    python3 tools/freessm_crosscheck.py                     # needs freessm_defs.py first
    python3 tools/freessm_crosscheck.py --freessm <json>
    python3 tools/freessm_crosscheck.py --json <out.json>

WHAT THIS ESTABLISHED, AND THE THING IT LOOKED LIKE IT CONTRADICTED

The join agrees on 689 rows across the 25 firmwares and contradicts on none, which
is worth more than the 234 rows it newly names.

The trouble code blocks resolve too, and at first they appeared to refute the M32R
fault-flag addresses in section 16b: FreeSSM's DTC addresses come out at 0x8051xx
while that section says 0x8041E2 and up. Both are right and they are different
things. 16b follows a table of twelve POINTERS and takes the flag at offset 2 of
each five-byte record, so its addresses are the internal fault records - which is why
they are spaced five apart, exactly the record stride found on Denso. The 0x8051xx
run is the SSM OUTPUT MIRROR, the same role 0xFFFFA0xx plays on Denso, and 71 of its
75 steps are +1 because it is one near-contiguous block the gather routine fills.

So: the mirror is what a scan tool reads, the records are what the firmware sets. A
bench tool should address the mirror, and this prints those addresses.

The gap from a current block to its historic twin is constant WITHIN a firmware and
splits exactly along the family line: +4 on all sixteen M32R images, +12, +13 or +14
on all nine Denso ones. So M32R interleaves in groups of four - four current bytes
then four historic - while Denso lays every current byte down first and the whole
historic run after, which is why its gap is just however many entries came first.

That split was not put in by hand. It falls out of joining two sources that know
nothing about this project's M32R/Denso division, which is what makes it worth
something. An earlier reading of this said +4 everywhere, from eyeballing one
firmware's blocks and generalising.

FreeSSM is GPLv3, by Comer352L: https://github.com/Comer352L/FreeSSM
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, WORK  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# Transmission codes by number. P0218 is transmission over-temperature, P07xx and
# P17xx are the transmission blocks proper, P18xx the later gear-ratio and lock-up
# codes. Blocks that fall below the majority are printed rather than dropped
# silently, so the cut can be checked instead of trusted.
TRANS = re.compile(r"^P(07\d\d|17\d\d|18\d\d|0218|0530|055[89]|056[23])$")


def trans_share(codes):
    real = [c for c in codes if re.match(r"^P\d{4}$", c)]
    return sum(1 for c in real if TRANS.match(c)) / len(real) if real else 0.0


def label_map(fs):
    """SSM logical address -> what FreeSSM says it is."""
    label = {}
    for mb in fs["measuring_blocks"]:
        for a in (mb["addr_low"], mb["addr_high"]):
            if a:
                label.setdefault(int(a, 16), dict(
                    name=mb["title"], unit=mb["unit"], formula=mb["formula"],
                    kind="MB", tcu_only=not mb["both_cu"]))
    for sw in fs["switches"]:
        label.setdefault(int(sw["addr"], 16), dict(
            name=sw["title"], unit=sw["unit"], formula=None, kind="SW",
            tcu_only=not sw["both_cu"]))
    return label


def join(sp, label):
    report = {}
    tot = dict(rows=0, agrees=0, new=0, conflict=0)
    for rom in sorted(sp):
        rows = [r for r in sp[rom]["rows"] if r.get("ram")]
        out = []
        for r in rows:
            lb = label.get(r["ssm"])
            if not lb:
                continue
            had = (r.get("name") or "").strip()
            status = ("agrees" if had.lower() == lb["name"].lower()
                      else "conflict") if had else "new"
            tot[status if status != "agrees" else "agrees"] += 1
            out.append(dict(ssm="0x%03X" % r["ssm"], ram="0x%08X" % r["ram"],
                            had=had or None, freessm=lb["name"], unit=lb["unit"],
                            formula=lb["formula"], kind=lb["kind"],
                            tcu_only=lb["tcu_only"], status=status))
        tot["rows"] += len(rows)
        report[rom] = out
    return report, tot


def main():
    ap = argparse.ArgumentParser(
        description="Cross-check the firmware's SSM table against FreeSSM's labels.")
    ap.add_argument("--freessm", default=os.path.join(WORK, "freessm_tcu.json"),
                    help="output of tools/freessm_defs.py")
    ap.add_argument("--ssm", default=os.path.join(HERE, "ssm_parameters.json"))
    ap.add_argument("--defs", default=os.path.join(
        REPO, "definitions", "5eat_tcu_romraider_defs.xml"))
    ap.add_argument("--conditions", default=os.path.join(HERE, "dtc_conditions.json"))
    ap.add_argument("--json", default=os.path.join(WORK, "freessm_crosscheck.json"))
    args = ap.parse_args()

    if not os.path.isfile(args.freessm):
        sys.exit("no FreeSSM extract at %s\nRun tools/freessm_defs.py --src <clone> "
                 "first." % args.freessm)
    fs = json.load(open(args.freessm, encoding="utf-8"))
    sp = json.load(open(args.ssm, encoding="utf-8"))

    label = label_map(fs)
    print("FreeSSM transmission labels on %d distinct SSM addresses" % len(label))
    report, tot = join(sp, label)
    print("join over %d firmwares: %d mapped rows, %d agree, %d newly named, "
          "%d conflict\n" % (len(sp), tot["rows"], tot["agrees"], tot["new"],
                             tot["conflict"]))

    # --- trouble codes, three independent accounts
    manual = set(json.load(open(args.conditions, encoding="utf-8")))
    fw = set(re.findall(r'name="(P[0-9]{4})"',
                        open(args.defs, encoding="utf-8", errors="replace").read()))
    tcu_blocks = {p: [e["code"] for e in v]
                  for p, v in fs["dtc_obd"].items() if trans_share(
                      [e["code"] for e in v]) >= 0.5}
    fs_codes = {c for v in tcu_blocks.values() for c in v if re.match(r"^P\d{4}$", c)}

    print("trouble codes   firmware %d   manual %d   FreeSSM(TCU blocks) %d"
          % (len(fw), len(manual), len(fs_codes)))
    for title, s in (("in all three", fw & manual & fs_codes),
                     ("firmware + FreeSSM, absent from the manual",
                      (fw & fs_codes) - manual),
                     ("firmware only, no other source lists them",
                      fw - manual - fs_codes),
                     ("manual states, firmware lacks", manual - fw)):
        print("  %-42s %2d %s" % (title, len(s), " ".join(sorted(s))))

    # --- where a bench tool should actually read the fault bytes
    # Pair each block with ITS OWN historic address from the definition. The gap in
    # SSM space is not constant - it is 0x20 for the 0x09x blocks, 4 for the 0x0Fx
    # and 8 for the 0x12x - so assuming one fixed offset pairs unrelated blocks and
    # reports a spread of nonsense differences.
    pairs_ssm = [(int(p.split("/")[0], 16), int(p.split("/")[1], 16))
                 for p in tcu_blocks]
    cur = sorted(c for c, _ in pairs_ssm)
    print("\nSSM mirror addresses of the transmission fault bytes, per firmware:")
    offs, perrom = {}, {}
    for rom in sorted(sp):
        m = {r["ssm"]: r["ram"] for r in sp[rom]["rows"] if r.get("ram")}
        hit = [(a, m[a]) for a in cur if a in m]
        if not hit:
            continue
        seen = {m[h] - m[c] for c, h in pairs_ssm if c in m and h in m}
        perrom[rom] = seen
        for d in seen:
            offs[d] = offs.get(d, 0) + 1
        print("  %-38s %2d blocks at %06X..%06X"
              % (rom[:38], len(hit), min(x[1] for x in hit),
                 max(x[1] for x in hit)))
    print("\nhistoric minus current, per firmware: %s"
          % (", ".join("+%d on %d" % (d, n) for d, n in sorted(offs.items()))
             or "not resolvable from this table"))
    mixed = [r for r, v in perrom.items() if len(v) > 1]
    print("firmwares where the gap is not constant across blocks: %s"
          % (", ".join(sorted(mixed)) if mixed else "none"))

    with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(join=report, totals=tot,
                       dtc_blocks={k: sorted(set(v)) for k, v in tcu_blocks.items()}),
                  fh, indent=1, sort_keys=True)
    print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
