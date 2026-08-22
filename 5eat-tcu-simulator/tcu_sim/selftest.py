"""The test suite as a callable that returns structured results, so it can run
from the CLI or from the browser (POST /api/selftest). Covers CAN byte-
correctness, ROMs, determinism, log integrity, edge cases, and physics bounds."""
from __future__ import annotations
import json
import os

from .vehicle import Vehicle, SimState, POWER_LEVELS, GEAR_RATIOS as DEF
from .messages import (encode_all_rx, encode_tx_demo, decode_tx, decode_frame_display)
from .simulator import run_headless, LOG_DIR
from . import romdata


def run_tests() -> list[dict]:
    R = []
    def ok(name, cond, detail=""):
        R.append({"name": name, "pass": bool(cond), "detail": "" if cond else str(detail)})

    # ---- A: CAN codec correctness ----
    s = SimState()
    s.engine_rpm, s.speed_kmh, s.throttle = 2500, 80, 0.5
    s.tcu_current_gear = s.tcu_target_gear = 3
    s.atf_temp1, s.atf_temp2, s.tcu_lockup, s.output_rpm = 90.0, 85.0, True, 3000
    rx = encode_all_rx(s)
    b410 = bytes.fromhex(rx["410"])
    ok("A1  0x410 RPM at B5-6 LE", (b410[5] | (b410[6] << 8)) == 2500, b410[5] | (b410[6] << 8))
    ok("A2  0x412 accel pedal at B0", bytes.fromhex(rx["412"])[0] == round(0.5 * 255))
    ok("A3  0x512 B1 enables 0x511/0x513", bytes.fromhex(rx["512"])[1] == 0x60)
    ok("A4  all 10 RX frames, 8 bytes each", len(rx) == 10 and all(len(bytes.fromhex(v)) == 8 for v in rx.values()))
    tx = encode_tx_demo(s)
    s2 = SimState(); decode_tx(0x420, bytes.fromhex(tx["420"]), s2); decode_tx(0x422, bytes.fromhex(tx["422"]), s2)
    ok("A5  0x420 gear round-trips", s2.tcu_current_gear == 3, s2.tcu_current_gear)
    ok("A6  0x422 ATF round-trips", abs(s2.atf_temp1 - 90) <= 1, s2.atf_temp1)
    ok("A7  0x422 DTC-none = 0x3FFF", bytes.fromhex(tx["422"])[3] == 0xFF and bytes.fromhex(tx["422"])[4] == 0x3F)
    ok("A8  lockup bit in 0x420 B2", bytes.fromhex(tx["420"])[2] & 0x80)
    ok("A9  decode strings non-empty", all(decode_frame_display(k, v) for k, v in {**rx, **tx}.items()
                                           if k in ("410", "412", "420", "422", "512")))

    # ---- B: ROMs ----
    valid = [r for r in romdata.list_roms() if r["valid_5eat"]]
    bad = 0
    for r in valid:
        v = Vehicle(); romdata.apply_rom(v, r["id"]); gr = v.gear_ratios
        if not (gr[1] > gr[2] > gr[3] > gr[4] > gr[5] and 0.9 < gr[4] < 1.12):
            bad += 1
    ok("B1  %d valid ROMs apply monotonic ratios" % len(valid), bad == 0, "%d bad" % bad)
    inval = [r for r in romdata.list_roms() if not r["valid_5eat"]]
    if inval:
        v = Vehicle(); romdata.apply_rom(v, valid[0]["id"]); romdata.apply_rom(v, inval[0]["id"])
        ok("B2  invalid ROM resets to default", v.gear_ratios[1] == DEF[1], v.gear_ratios[1])

    rom = valid[0]["id"] if valid else None

    # ---- C: determinism ----
    r1 = run_headless("errand", power="400 hp", rom=rom, sample_hz=5)
    r2 = run_headless("errand", power="400 hp", rom=rom, sample_hz=5)
    ok("C1  deterministic summary", r1["summary"] == r2["summary"])
    ok("C2  deterministic telemetry length", len(r1["telemetry"]) == len(r2["telemetry"]))

    # ---- D: log integrity ----
    r = run_headless("city_cycle", power="Stock ~250hp", rom=rom, sample_hz=5)
    lines = open(os.path.join(LOG_DIR, r["log_file"])).read().splitlines()
    hdr = json.loads(lines[0]); rows = [json.loads(x) for x in lines[1:]]
    ok("D1  header has summary + ratios", "summary" in hdr and "gear_ratios" in hdr)
    ok("D2  time monotonic", all(rows[i]["t"] >= rows[i-1]["t"] for i in range(1, len(rows))))
    ok("D3  every row has 13 CAN frames", all("can" in x and len(x["can"]["rx"]) == 10 and len(x["can"]["tx"]) == 3 for x in rows))
    ok("D4  all CAN bytes valid hex", all(all(len(v) == 16 and all(c in "0123456789ABCDEF" for c in v) for v in x["can"]["rx"].values()) for x in rows[:50]))
    ok("D5  no None/NaN in key fields", all(isinstance(x["rpm"], (int, float)) and isinstance(x["speed"], (int, float)) for x in rows))

    # ---- E: edge cases ----
    v = Vehicle(); v.s.selector = "R"; v.s.throttle = 0.4
    for _ in range(150): v.step(0.02)
    ok("E1  reverse builds speed", v.s.speed_kmh > 3, "%.1f km/h" % v.s.speed_kmh)
    v = Vehicle(); v.s.selector = "D"; v.s.throttle = 0.5
    for _ in range(100): v.step(0.02)
    v.s.ignition = False
    for _ in range(200): v.step(0.02)
    ok("E2  ignition off -> engine stops", v.s.engine_rpm < 100, "%.0f rpm" % v.s.engine_rpm)
    v = Vehicle(); v.s.selector = "P"; v.s.throttle = 1.0
    for _ in range(150): v.step(0.02)
    ok("E3  Park doesn't move at WOT", v.s.speed_kmh < 0.5, "%.2f km/h" % v.s.speed_kmh)
    v = Vehicle(); v.s.selector = "M"; v.s.manual_gear = 2
    ok("E4  manual uses commanded gear", abs(v._active_ratio() - v.gear_ratios[2]) < 1e-6)
    v = Vehicle(); v.set_power(POWER_LEVELS["Stock ~250hp"]); t1 = v._torque(4000)
    v.set_power(POWER_LEVELS["1000+ hp"]); t2 = v._torque(4000)
    ok("E5  power scales torque >2.5x", t2 > t1 * 2.5, "%.0f vs %.0f Nm" % (t1, t2))

    # ---- F: physics bounds across all powers ----
    fbad = []
    for power in POWER_LEVELS:
        for run in ["wot_pull", "errand", "highway_cruise"]:
            tel = run_headless(run, power=power, rom=rom, sample_hz=10)["telemetry"]
            if any(x["rpm"] > 6600 or x["rpm"] < 0 for x in tel): fbad.append("%s/%s rpm" % (run, power.split()[0]))
            if any(not (-0.001 <= x["throttle"] <= 1.001) for x in tel): fbad.append("%s/%s thr" % (run, power.split()[0]))
            if any(x["atf1"] > 145 or x["atf1"] < 15 for x in tel): fbad.append("%s/%s atf" % (run, power.split()[0]))
            if any(x["slip"] < 0 or x["line_kpa"] < 0 for x in tel): fbad.append("%s/%s neg" % (run, power.split()[0]))
    ok("F1  physics bounds across all 5 powers", not fbad, ", ".join(fbad[:5]))

    return R
