"""Batch-simulate every scenario across powers + a ROM, write logs, and flag
anomalies so the model can be corrected. Run: python batch_analyze.py"""
import sys
from tcu_sim.simulator import run_headless
from tcu_sim import romdata
from tcu_sim.runs import RUN_ORDER

REDLINE = 6600
rom = next((r["id"] for r in romdata.list_roms() if r["valid_5eat"]), None)
POWERS = ["Stock ~250hp", "800 hp"]
RUNS = RUN_ORDER + ["drive_20"]

issues = []


def check(run, power, r):
    tag = "%s/%s" % (run, power.split()[0])
    tel = r["telemetry"]
    s = r["summary"]
    if not s:
        issues.append((tag, "run did not complete (no summary)"))
        return
    if not tel:
        issues.append((tag, "no telemetry"))
        return
    rpm = [row["rpm"] for row in tel]
    spd = [row["speed"] for row in tel]
    atf = [row["atf1"] for row in tel]
    thr = [row["throttle"] for row in tel]
    # rpm range
    if max(rpm) > REDLINE:
        issues.append((tag, "rpm over redline: %d" % max(rpm)))
    if min(rpm) < 0:
        issues.append((tag, "negative rpm: %d" % min(rpm)))
    # stopped-but-revving / moving checks
    if run in ("wot_pull",) and max(spd) < 120:
        issues.append((tag, "WOT never reached 120 (max %.0f)" % max(spd)))
    if run in ("errand", "city_cycle", "highway_cruise") and max(spd) < 30:
        issues.append((tag, "barely moved (max %.0f)" % max(spd)))
    # ATF should warm on drives > 60s
    if s["duration"] > 60 and atf and atf[-1] <= atf[0] + 2:
        issues.append((tag, "ATF did not warm (%.0f->%.0f)" % (atf[0], atf[-1])))
    if atf and (max(atf) > 145 or min(atf) < 15):
        issues.append((tag, "ATF out of range %.0f..%.0f" % (min(atf), max(atf))))
    # gear hunting: count up/down reversals within 1.5s
    ev = r["events"]
    rev = 0
    for i in range(1, len(ev)):
        if ev[i]["dir"] != ev[i-1]["dir"] and ev[i]["t"] - ev[i-1]["t"] < 1.5:
            rev += 1
    if rev > 3:
        issues.append((tag, "gear hunting: %d quick reversals" % rev))
    # calm launches should be gentle (errand/drive use calm/normal)
    if run in ("errand",) and max(thr) > 0.5:
        issues.append((tag, "errand throttle too high: %.0f%%" % (max(thr)*100)))
    # unexpected DTCs in demo
    if s.get("dtcs"):
        issues.append((tag, "unexpected DTCs: %s" % s["dtcs"]))
    # throttle bounds
    if max(thr) > 1.001 or min(thr) < -0.001:
        issues.append((tag, "throttle out of bounds %.2f..%.2f" % (min(thr), max(thr))))


print("ROM:", rom)
n = 0
for run in RUNS:
    for power in POWERS:
        r = run_headless(run, power=power, rom=rom, sample_hz=5)
        check(run, power, r)
        n += 1
        s = r["summary"] or {}
        print("  %-16s %-6s dur=%5s maxspd=%3s shifts=%2s" % (
            run, power.split()[0], s.get("duration", "?"),
            s.get("max_speed", "?"), s.get("shifts", "?")))

print("\n=== %d sims run, %d anomalies ===" % (n, len(issues)))
for tag, msg in issues:
    print("  [%s] %s" % (tag, msg))
if not issues:
    print("  none")
