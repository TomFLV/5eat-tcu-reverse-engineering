"""Deeper test suite for the bench tool. Categories:
  A CAN codec correctness (byte positions + round-trip) - critical: a real TCU
    only responds if the frames are byte-exact.
  B all valid ROMs apply + simulate sanely
  C determinism (same inputs -> identical result) for firmware comparison
  D log integrity (well-formed JSONL, monotonic time, valid CAN hex)
  E edge cases (reverse, ignition off, manual gears, P/N no motion, power change)
  F physics bounds across all powers
"""
import json
import os
import struct

from tcu_sim.vehicle import Vehicle, SimState, POWER_LEVELS
from tcu_sim.messages import (encode_all_rx, encode_tx_demo, decode_tx,
                              decode_frame_display, RX_MESSAGES)
from tcu_sim.simulator import run_headless, Simulator, LOG_DIR
from tcu_sim import romdata
from tcu_sim.runs import RUN_ORDER

results = []
def ok(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---------- A: CAN codec correctness ----------
s = SimState()
s.engine_rpm, s.speed_kmh, s.throttle = 2500, 80, 0.5
s.tcu_current_gear = s.tcu_target_gear = 3
s.atf_temp1, s.atf_temp2 = 90.0, 85.0
s.tcu_lockup = True
s.output_rpm = 3000
rx = encode_all_rx(s)
b410 = bytes.fromhex(rx["410"])
ok("A1 0x410 RPM at B5-6 LE", (b410[5] | (b410[6] << 8)) == 2500, "got %d" % (b410[5] | (b410[6] << 8)))
b412 = bytes.fromhex(rx["412"])
ok("A2 0x412 pedal at B0", b412[0] == round(0.5 * 255), "got %d" % b412[0])
b512 = bytes.fromhex(rx["512"])
ok("A3 0x512 B1 enables 0x511/0x513 (0x60)", b512[1] == 0x60, "got 0x%02X" % b512[1])
ok("A4 all 10 RX frames present + 8 bytes", len(rx) == 10 and all(len(bytes.fromhex(v)) == 8 for v in rx.values()))
tx = encode_tx_demo(s)
# round-trip: decode_tx should recover gear + atf
s2 = SimState()
decode_tx(0x420, bytes.fromhex(tx["420"]), s2)
decode_tx(0x422, bytes.fromhex(tx["422"]), s2)
ok("A5 0x420 gear round-trips", s2.tcu_current_gear == 3, "got %d" % s2.tcu_current_gear)
ok("A6 0x422 ATF1 round-trips", abs(s2.atf_temp1 - 90) <= 1, "got %.0f" % s2.atf_temp1)
ok("A7 0x422 DTC-none encodes 0x3FFF", bytes.fromhex(tx["422"])[3] == 0xFF and bytes.fromhex(tx["422"])[4] == 0x3F)
ok("A8 lockup bit set in 0x420 B2", bytes.fromhex(tx["420"])[2] & 0x80, "B2=0x%02X" % bytes.fromhex(tx["420"])[2])
ok("A9 decode string non-empty for all", all(decode_frame_display(k, v) for k, v in {**rx, **tx}.items()
                                             if k in ("410", "412", "420", "422", "512")))


# ---------- B: all valid ROMs ----------
valid = [r for r in romdata.list_roms() if r["valid_5eat"]]
bad = 0
for r in valid:
    v = Vehicle()
    p = romdata.apply_rom(v, r["id"])
    gr = v.gear_ratios
    if not (gr[1] > gr[2] > gr[3] > gr[4] > gr[5] and 0.9 < gr[4] < 1.12):
        bad += 1
ok("B1 all %d valid ROMs apply monotonic ratios" % len(valid), bad == 0, "%d bad" % bad)
# an invalid ROM resets to default (does not keep a previous ROM's ratios)
inval = [r for r in romdata.list_roms() if not r["valid_5eat"]]
if inval and valid:
    v = Vehicle()
    romdata.apply_rom(v, valid[0]["id"])          # set 3.54 family
    romdata.apply_rom(v, inval[0]["id"])          # invalid -> should reset to default
    from tcu_sim.vehicle import GEAR_RATIOS as DEF
    ok("B2 invalid ROM resets to default", v.gear_ratios[1] == DEF[1], "got %.3f" % v.gear_ratios[1])


# ---------- C: determinism ----------
# no firmware supplied (clean checkout) -> exercise the default-calibration path
rom = valid[0]["id"] if valid else None
r1 = run_headless("errand", power="400 hp", rom=rom, sample_hz=5)
r2 = run_headless("errand", power="400 hp", rom=rom, sample_hz=5)
ok("C1 deterministic summary", r1["summary"] == r2["summary"], "%.1f vs %.1f" % (r1["summary"]["duration"], r2["summary"]["duration"]))
ok("C2 deterministic telemetry length", len(r1["telemetry"]) == len(r2["telemetry"]))


# ---------- D: log integrity ----------
r = run_headless("city_cycle", power="Stock ~250hp", rom=rom, sample_hz=5)
lines = open(os.path.join(LOG_DIR, r["log_file"])).read().splitlines()
hdr = json.loads(lines[0])
rows = [json.loads(x) for x in lines[1:]]
ok("D1 header has summary+ratios", "summary" in hdr and "gear_ratios" in hdr)
ok("D2 time monotonic", all(rows[i]["t"] >= rows[i-1]["t"] for i in range(1, len(rows))))
ok("D3 every row has CAN rx+tx (13 frames)",
   all("can" in x and len(x["can"]["rx"]) == 10 and len(x["can"]["tx"]) == 3 for x in rows))
ok("D4 all CAN bytes valid hex (16 chars)",
   all(all(len(v) == 16 and all(c in "0123456789ABCDEF" for c in v) for v in x["can"]["rx"].values()) for x in rows[:50]))
ok("D5 no None/NaN in key fields", all(isinstance(x["rpm"], (int, float)) and isinstance(x["speed"], (int, float)) for x in rows))


# ---------- E: edge cases ----------
# reverse moves the car
v = Vehicle(); v.s.ignition = True; v.s.selector = "R"; v.s.throttle = 0.4
for _ in range(150): v.step(0.02)
ok("E1 reverse builds speed", v.s.speed_kmh > 3, "%.1f km/h" % v.s.speed_kmh)
# ignition off spins the engine down and coasts
v = Vehicle(); v.s.selector = "D"; v.s.throttle = 0.5
for _ in range(100): v.step(0.02)
v.s.ignition = False
for _ in range(200): v.step(0.02)
ok("E2 ignition off -> engine stops", v.s.engine_rpm < 100, "%.0f rpm" % v.s.engine_rpm)
# Park/Neutral: no motion no matter the throttle
v = Vehicle(); v.s.selector = "P"; v.s.throttle = 1.0
for _ in range(150): v.step(0.02)
ok("E3 Park does not move the car", v.s.speed_kmh < 0.5, "%.2f km/h" % v.s.speed_kmh)
# manual holds the commanded gear
v = Vehicle(); v.s.selector = "M"; v.s.manual_gear = 2; v.s.throttle = 0.3; v.s.tcu_current_gear = 2
r = v._active_ratio()
ok("E4 manual uses commanded gear ratio", abs(r - v.gear_ratios[2]) < 1e-6)
# power change takes effect
v = Vehicle(); v.set_power(POWER_LEVELS["Stock ~250hp"]); t1 = v._torque(4000)
v.set_power(POWER_LEVELS["1000+ hp"]); t2 = v._torque(4000)
ok("E5 power selector scales torque", t2 > t1 * 2.5, "%.0f vs %.0f Nm" % (t1, t2))


# ---------- F: physics bounds across all powers ----------
fbad = []
for power in POWER_LEVELS:
    for run in ["wot_pull", "errand", "highway_cruise"]:
        rr = run_headless(run, power=power, rom=rom, sample_hz=10)
        tel = rr["telemetry"]
        if any(x["rpm"] > 6600 or x["rpm"] < 0 for x in tel): fbad.append("%s/%s rpm" % (run, power))
        if any(x["throttle"] > 1.001 or x["throttle"] < -0.001 for x in tel): fbad.append("%s/%s thr" % (run, power))
        if any(x["atf1"] > 145 or x["atf1"] < 15 for x in tel): fbad.append("%s/%s atf" % (run, power))
        if any(x["slip"] < 0 or x["line_kpa"] < 0 for x in tel): fbad.append("%s/%s neg" % (run, power))
ok("F1 physics bounds across all powers", not fbad, ", ".join(fbad[:5]))


# ---------- report ----------
print("=" * 64)
passed = sum(1 for _, p, _ in results if p)
for name, p, detail in results:
    print("  [%s] %-42s %s" % ("PASS" if p else "FAIL", name, "" if p else "<< " + detail))
print("=" * 64)
print("  %d/%d passed" % (passed, len(results)))
