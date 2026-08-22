"""Full validation: integrity check, run + log EVERY simulation across powers
(and durations), analyze for anomalies, and print a report."""
import os
import time
from tcu_sim.simulator import run_headless, LOG_DIR
from tcu_sim import romdata
from tcu_sim.runs import RUN_ORDER, DURATIONS
from tcu_sim.vehicle import POWER_LEVELS

REDLINE = 6600
NAMED = RUN_ORDER
DRIVES = ["drive_%d" % m for m in DURATIONS]
POWERS = list(POWER_LEVELS.keys())

print("=" * 68)
print("1) INTEGRITY")
roms = romdata.list_roms()
valid = [r for r in roms if r["valid_5eat"]]
rom = valid[0]["id"] if valid else None
print("   ROMs: %d total, %d with real ratios, %d with SI-DRIVE"
      % (len(roms), len(valid), sum(r["si_drive"] for r in roms)))
print("   named runs: %d | durations: %s | powers: %d" % (len(NAMED), DURATIONS, len(POWERS)))
print("   using ROM:", romdata._friendly(rom) if rom else "none")

issues = []


def analyze(tag, run, r):
    tel, s, ev = r["telemetry"], r["summary"], r["events"]
    if not s:
        issues.append((tag, "no summary (did not complete)")); return None
    if not tel:
        issues.append((tag, "no telemetry")); return s
    rpm = [x["rpm"] for x in tel]; spd = [x["speed"] for x in tel]
    atf = [x["atf1"] for x in tel]; thr = [x["throttle"] for x in tel]
    ln = [x["line_kpa"] for x in tel]; slip = [x["slip"] for x in tel]
    if max(rpm) > REDLINE: issues.append((tag, "rpm over redline %d" % max(rpm)))
    if min(rpm) < 0: issues.append((tag, "negative rpm"))
    if max(thr) > 1.001 or min(thr) < -0.001: issues.append((tag, "throttle out of bounds"))
    if min(slip) < 0: issues.append((tag, "negative slip"))
    if min(ln) < 0: issues.append((tag, "negative line pressure"))
    if run == "wot_pull" and max(spd) < 120: issues.append((tag, "WOT never reached 120 (%.0f)" % max(spd)))
    if run in ("errand", "city_cycle") and max(spd) < 30: issues.append((tag, "barely moved"))
    if run == "stall_test" and max(spd) > 8: issues.append((tag, "stall test not held (%.0f km/h)" % max(spd)))
    if s["duration"] > 90 and atf and atf[-1] <= atf[0] + 2: issues.append((tag, "ATF did not warm"))
    if atf and (max(atf) > 145 or min(atf) < 15): issues.append((tag, "ATF out of range"))
    rev = sum(1 for i in range(1, len(ev)) if ev[i]["dir"] != ev[i-1]["dir"] and ev[i]["t"]-ev[i-1]["t"] < 1.5)
    if rev > 4: issues.append((tag, "gear hunting: %d reversals" % rev))
    if s.get("dtcs"): issues.append((tag, "unexpected DTCs %s" % s["dtcs"]))
    return s


print("\n" + "=" * 68)
print("2) RUN + LOG ALL SIMULATIONS")
t0 = time.time(); n = 0
print("\n   %-16s %-8s %6s %6s %5s %6s" % ("run", "power", "dur", "0-100", "shft", "maxkmh"))
for run in NAMED:
    for power in POWERS:
        r = run_headless(run, power=power, rom=rom, sample_hz=5)
        s = analyze("%s/%s" % (run, power.split()[0]), run, r); n += 1
        if s:
            print("   %-16s %-8s %6.1f %6s %5s %6s"
                  % (run, power.split()[0], s["duration"], s["t100"] or "-", s["shifts"], s["max_speed"]))
for run in DRIVES:
    for power in ["Stock ~250hp", "800 hp"]:
        r = run_headless(run, power=power, rom=rom, sample_hz=2)
        s = analyze("%s/%s" % (run, power.split()[0]), run, r); n += 1
        if s:
            print("   %-16s %-8s %6.1f %6s %5s %6s"
                  % (run, power.split()[0], s["duration"], s["t100"] or "-", s["shifts"], s["max_speed"]))

logs = [f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")] if os.path.isdir(LOG_DIR) else []
size = sum(os.path.getsize(os.path.join(LOG_DIR, f)) for f in logs)

print("\n" + "=" * 68)
print("3) REPORT")
print("   simulations run+logged: %d  (%.1fs)" % (n, time.time()-t0))
print("   log files on disk: %d  (%.1f MB total)" % (len(logs), size/1e6))
print("   anomalies: %d" % len(issues))
for tag, msg in issues:
    print("     [%s] %s" % (tag, msg))
if not issues:
    print("     none - all simulations physically sane")
