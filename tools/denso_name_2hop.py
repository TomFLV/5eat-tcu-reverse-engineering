#!/usr/bin/env python3
"""Name Denso tables by following one hop further than the reader.

Where this got to. The functions that read the shipped tables are dispatched to
rather than called, so a call-stack attribution never saw them; giving the emulator
the list of function starts and letting it name whichever function the pc is
actually inside fixed that, and 18 of the 20 readers now have write sets of 29 to
117 addresses each.

None of those addresses is one the Select Monitor names. That is not a failure, it
is a fact about what the readers do: they write internal working variables, and the
Select Monitor publishes results. So the chain needs one more hop.

    table -> the function that reads it
          -> the addresses that function writes
          -> the functions that READ those addresses
          -> what THOSE write, and whether any of it is named

Each hop weakens the evidence, and this says so: a table two hops from Line
Pressure is part of the line pressure calculation, not line pressure itself. Coarse
and true beats precise and invented, which is the lesson this project keeps
relearning.

    python3 tools/denso_name_2hop.py
    python3 tools/denso_name_2hop.py --json out.json
"""

import argparse
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workdir import REPO, WORK  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LITERALS = os.path.join(HERE, "denso_literals.json")
SSM = os.path.join(HERE, "denso_ssm_addresses.json")
FNSETS = os.path.join(WORK, "naming", "fnsets.txt")
FNREADS = os.path.join(WORK, "naming", "fnreads.txt")


def load_pairs(path, what):
    out = {}
    if not os.path.exists(path):
        sys.exit("%s not found - run denso_name_by_task.py first" % path)
    for line in open(path):
        p = line.split()
        if len(p) == 2:
            out.setdefault(int(p[0], 16), set()).add(int(p[1], 16))
    sys.stderr.write("%d functions with %s\n" % (len(out), what))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--max-consumer", type=int, default=500,
                    help="ignore consumers writing more than this many addresses. "
                         "Three functions write 48 of the 141 names each while "
                         "touching about 3,900 addresses: they are the routines "
                         "that publish state to the Select Monitor, not "
                         "computations. Every table's output reaches one of them "
                         "eventually, which is why without this filter all 171 "
                         "tables reach all 141 names and nothing is distinguished.")
    ap.add_argument("--max-hop1", type=int, default=200,
                    help="skip readers writing more than this many addresses; a "
"function touching hundreds is a utility and its writes "
"say nothing about any one table")
    args = ap.parse_args()

    import denso_name_by_task as M

    names = {int(k, 16): v
             for k, v in json.load(open(SSM, encoding="utf-8")).items()}
    lit = json.load(open(LITERALS, encoding="utf-8"))["tables"]
    starts = M.function_starts()
    fnsets = load_pairs(FNSETS, "write sets")
    fnreads = load_pairs(FNREADS, "read sets")
    headers = M.shipped_headers()

    def enclosing(a):
        i = bisect.bisect_right(starts, a)
        return starts[i - 1] if i else None

    # address -> functions OBSERVED reading it. The static cross-reference cannot
    # answer this: the readers write 280 addresses around 0xFFFF98xx and none of
    # them appears there as ever being read, because they are reached by computed
    # address. Watching the firmware run has no such blind spot.
    readers_of = {}
    for f, addrs in fnreads.items():
        for a in addrs:
            readers_of.setdefault(a, set()).add(f)

    sys.stderr.write("%d addresses are read by some function\n" % len(readers_of))

    result = {}
    for h in headers:
        sites = set(lit.get(h, []))
        if not sites:
            continue
        fns = {enclosing(s) for s in sites}
        fns.discard(None)

        hop1 = set()
        for f in fns:
            w = fnsets.get(f, set())
            if 0 < len(w) <= args.max_hop1:
                hop1 |= w
        if not hop1:
            continue

        # Anything the reader wrote that is already named needs no second hop.
        direct = sorted({names[a] for a in hop1 if a in names})

        consumers = set()
        for a in hop1:
            consumers |= readers_of.get(a, set())
        indirect = sorted({names[a] for c in consumers
                           if len(fnsets.get(c, ())) <= args.max_consumer
                           for a in fnsets.get(c, set()) if a in names})

        if direct or indirect:
            result[h] = {
                "functions": ["%08X" % f for f in sorted(fns)],
"writes": len(hop1),
"direct": direct,
"via_consumers": indirect,
"consumers": len(consumers),
            }

    # A name 171 of 185 tables reach is not evidence about any of them. Score each
    # name by how FEW tables reach it: a consumer shared by every table is a hub -
    # a scheduler, a copy routine - and says only that the controller is connected.
    # This is the same failure as the dependency map that once reported one input
    # driving all 2,265 addresses, arriving from the other direction.
    reach_count = {}
    for v in result.values():
        for n in set(v["direct"]) | set(v["via_consumers"]):
            reach_count[n] = reach_count.get(n, 0) + 1

    total = len(result) or 1
    for h, v in result.items():
        specific = [n for n in (v["direct"] or v["via_consumers"])
                    if reach_count.get(n, 0) <= max(2, total // 8)]
        v["specific"] = sorted(specific)

    with_specific = sum(1 for v in result.values() if v["specific"])
    print("\nname reach, most common first - anything near %d is a hub:" % total)
    for n, c in sorted(reach_count.items(), key=lambda kv: -kv[1])[:10]:
        print("  %-52s reached by %d tables" % (n[:52], c))
    print("\n%d tables have at least one name that is NOT reached by most "
          "of them" % with_specific)
    if with_specific:
        grp = {}
        for h, v in result.items():
            if v["specific"]:
                grp.setdefault(" / ".join(v["specific"][:3]), []).append(h)
        for k, vv in sorted(grp.items(), key=lambda kv: len(kv[1]))[:12]:
            print("  %-56s %d table(s)" % (k[:56], len(vv)))

    byd = sum(1 for v in result.values() if v["direct"])
    print("\n%d of %d shipped tables reach a named address" % (len(result), len(headers)))
    print("  %d directly from the reader, %d only through what consumes its output\n"
          % (byd, len(result) - byd))

    groups = {}
    for h, v in result.items():
        key = " / ".join((v["direct"] or v["via_consumers"])[:3])
        groups.setdefault(key, []).append(h)
    print("  %-64s %s" % ("evidence", "tables"))
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:20]:
        print("  %-64s %d" % (k[:64], len(v)))

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
        print("\n-> %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
