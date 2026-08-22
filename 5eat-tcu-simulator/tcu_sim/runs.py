"""Automated test-run library for firmware validation.

A run is an ordered list of steps. Each step gives the DRIVER MODEL a goal - a
speed to reach and hold, a stop, an emergency stop, or a wait - plus an optional
style override, and an exit condition. The throttle and brake are produced by the
closed-loop driver (driver.py), so the pedal positions are realistic, not
hardcoded. A few deliberate test runs (WOT, stall) still command the pedal
directly because flooring it IS the input under test.

Step keys:
  goal:     ("cruise", kmh) | ("stop",) | ("emergency",) | ("wait",)
  throttle/brake: explicit pedal (only for deliberate WOT/stall steps)
  style:    "calm" | "normal" | "spirited"  (overrides the run default)
  selector, manual_gear: set directly
  until:    ("speed_ge",kmh) | ("speed_le",kmh) | ("time",s) | ("rpm_ge",r) | ("rpm_le",r)
  timeout:  safety cap in seconds
  label:    phase name
"""
from __future__ import annotations


def _errand():
    S = []
    S.append({"selector": "D", "goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 8, "label": "stage"})
    S.append({"goal": ("cruise", 45), "until": ("speed_ge", 43), "timeout": 22, "label": "pull out of lot"})
    S.append({"goal": ("cruise", 45), "until": ("time", 6.0), "timeout": 7, "label": "city cruise"})
    S.append({"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 15, "label": "ease to red light"})
    S.append({"goal": ("wait",), "until": ("time", 3.0), "timeout": 4, "label": "wait at light"})
    S.append({"goal": ("cruise", 50), "until": ("speed_ge", 48), "timeout": 20, "label": "accelerate away"})
    S.append({"goal": ("cruise", 22), "until": ("speed_le", 25), "timeout": 14, "label": "traffic slows"})
    S.append({"goal": ("cruise", 50), "until": ("speed_ge", 48), "timeout": 18, "label": "traffic clears"})
    S.append({"goal": ("emergency",), "until": ("speed_le", 1.5), "timeout": 8, "label": "HARD BRAKE"})
    S.append({"goal": ("wait",), "until": ("time", 2.0), "timeout": 3, "label": "stopped"})
    S.append({"goal": ("cruise", 65), "style": "normal", "until": ("speed_ge", 62), "timeout": 22, "label": "merge to main road"})
    S.append({"goal": ("cruise", 65), "until": ("time", 8.0), "timeout": 9, "label": "cruise 65"})
    S.append({"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 16, "label": "arrive"})
    S.append({"selector": "P", "goal": ("wait",), "until": ("time", 1.5), "timeout": 2, "label": "park"})
    return S


def _city_cycle():
    S = []
    for _ in range(3):
        S.append({"selector": "D", "goal": ("cruise", 50), "until": ("speed_ge", 48), "timeout": 16, "label": "accelerate"})
        S.append({"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 14, "label": "stop"})
        S.append({"goal": ("wait",), "until": ("time", 1.5), "timeout": 2, "label": "idle"})
    return S


def _highway():
    return [
        {"selector": "D", "goal": ("cruise", 110), "style": "normal", "until": ("speed_ge", 106), "timeout": 30, "label": "on-ramp / merge"},
        {"goal": ("cruise", 110), "until": ("time", 18.0), "timeout": 19, "label": "steady cruise (TCC)"},
        {"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 20, "label": "exit / brake"},
    ]


def _coast():
    return [
        {"selector": "D", "goal": ("cruise", 120), "style": "spirited", "until": ("speed_ge", 115), "timeout": 30, "label": "accelerate"},
        {"goal": ("cruise", 15), "until": ("speed_le", 18), "timeout": 45, "label": "lift & coast down"},
        {"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 12, "label": "stop"},
    ]


def _part_throttle():
    return [
        {"selector": "D", "goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 6, "label": "stage"},
        {"goal": ("cruise", 120), "style": "normal", "until": ("speed_ge", 116), "timeout": 45, "label": "steady part-throttle climb"},
        {"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 16, "label": "brake"},
    ]


def _manual_sweep():
    S = [{"selector": "M", "manual_gear": 1, "goal": ("stop",), "until": ("speed_le", 2), "timeout": 5, "label": "stage"}]
    for g in (1, 2, 3, 4, 5):
        S.append({"selector": "M", "manual_gear": g, "throttle": 0.30, "brake": 0.0,
                  "until": ("time", 4.0), "timeout": 5, "label": "hold gear %d" % g})
    return S


RUNS = {
    "errand": {
        "name": "Errand — drive to the store",
        "desc": "Realistic calm city trip: pull out, red light, traffic creep, a hard-braking event, cruise, arrive and park.",
        "style": "calm",
        "steps": _errand(),
    },
    "city_cycle": {
        "name": "City stop-and-go (3x)",
        "desc": "Three accelerate-to-50 / smooth-stop cycles. Low-gear shifts and TCC apply/release.",
        "style": "normal",
        "steps": _city_cycle(),
    },
    "highway_cruise": {
        "name": "Highway merge + TCC cruise",
        "desc": "Merge to 110 and hold steady. Torque-converter lockup engagement and hold.",
        "style": "normal",
        "steps": _highway(),
    },
    "part_throttle": {
        "name": "Part-throttle climb",
        "desc": "Steady normal-driver climb to highway speed. Characterizes the everyday upshift points.",
        "style": "normal",
        "steps": _part_throttle(),
    },
    "coast_downshift": {
        "name": "Coast-down engine braking",
        "desc": "Accelerate, then lift with no brake. The deceleration downshift schedule.",
        "style": "spirited",
        "steps": _coast(),
    },
    "wot_pull": {
        "name": "WOT acceleration",
        "desc": "Full-throttle pull from a standstill. The wide-open shift schedule and 0-100.",
        "style": "spirited",
        "steps": [
            {"selector": "D", "goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 6, "label": "stage"},
            {"throttle": 1.0, "brake": 0.0, "thr_rate": 3.0, "until": ("speed_ge", 190), "timeout": 22, "label": "WOT pull"},
            {"goal": ("stop",), "until": ("speed_le", 2), "timeout": 14, "label": "brake to stop"},
        ],
    },
    "kickdown": {
        "name": "Kickdown",
        "desc": "Cruise in top gear, then floor it. The throttle-demand downshift (kickdown) logic.",
        "style": "normal",
        "steps": [
            {"selector": "D", "goal": ("cruise", 80), "until": ("speed_ge", 78), "timeout": 25, "label": "cruise up"},
            {"goal": ("cruise", 80), "until": ("time", 3.0), "timeout": 4, "label": "steady cruise"},
            {"throttle": 1.0, "brake": 0.0, "thr_rate": 4.0, "until": ("time", 6.0), "timeout": 8, "label": "kickdown WOT"},
            {"goal": ("stop",), "until": ("speed_le", 2), "timeout": 14, "label": "brake"},
        ],
    },
    "stall_test": {
        "name": "Stall test",
        "desc": "Brake held + full throttle in Drive. Converter stall speed - a real TCU diagnostic.",
        "style": "normal",
        "steps": [
            {"selector": "D", "goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 6, "label": "stage"},
            {"selector": "D", "throttle": 1.0, "brake": 1.0, "thr_rate": 3.0, "until": ("time", 4.0), "timeout": 5, "label": "stall"},
            {"throttle": 0.0, "brake": 1.0, "until": ("time", 2.0), "timeout": 3, "label": "release"},
        ],
    },
    "manual_sweep": {
        "name": "Manual gear sweep",
        "desc": "Tiptronic mode, hold each gear 1-5 at part throttle. Manual-mode gear holding.",
        "style": "normal",
        "steps": _manual_sweep(),
    },
}

RUN_ORDER = ["errand", "city_cycle", "highway_cruise", "part_throttle",
             "coast_downshift", "wot_pull", "kickdown", "stall_test", "manual_sweep"]

DURATIONS = [20, 40, 60, 120]      # minutes, selectable full-drive simulations


def build_drive(minutes: int) -> list:
    """Procedurally build a realistic drive of ~`minutes`: a mix of city streets
    with lights, highway stretches, traffic, and the occasional hard-braking
    event, driven by the driver model. Deterministic (same minutes -> same drive)
    so logs are reproducible for firmware comparison."""
    target = minutes * 60
    S = [{"selector": "D", "goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 6, "label": "engine on / staged"}]
    t, seg = 0.0, 0
    while t < target:
        seg += 1
        pick = seg % 6
        if pick in (0, 3):                       # city to a red light
            S += [{"goal": ("cruise", 50), "style": "calm", "until": ("speed_ge", 48), "timeout": 18, "label": "city street"},
                  {"goal": ("cruise", 50), "until": ("time", 8), "timeout": 9, "label": "cruise"},
                  {"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 14, "label": "red light"},
                  {"goal": ("wait",), "until": ("time", 4), "timeout": 5, "label": "wait at light"}]
            t += 42
        elif pick in (1, 4):                     # highway stretch
            S += [{"goal": ("cruise", 110), "style": "normal", "until": ("speed_ge", 106), "timeout": 30, "label": "highway merge"},
                  {"goal": ("cruise", 110), "until": ("time", 70), "timeout": 72, "label": "highway cruise"},
                  {"goal": ("cruise", 70), "until": ("speed_le", 74), "timeout": 20, "label": "slow for exit"}]
            t += 100
        elif pick == 2:                          # stop-and-go traffic
            S += [{"goal": ("cruise", 40), "style": "calm", "until": ("speed_ge", 38), "timeout": 15, "label": "traffic"},
                  {"goal": ("cruise", 15), "until": ("speed_le", 18), "timeout": 12, "label": "traffic slows"},
                  {"goal": ("cruise", 45), "until": ("speed_ge", 43), "timeout": 14, "label": "traffic clears"}]
            t += 36
        else:                                    # suburban + a hard brake
            S += [{"goal": ("cruise", 60), "style": "normal", "until": ("speed_ge", 58), "timeout": 18, "label": "suburban road"},
                  {"goal": ("emergency",), "until": ("speed_le", 1.5), "timeout": 8, "label": "HARD BRAKE"},
                  {"goal": ("wait",), "until": ("time", 3), "timeout": 4, "label": "stopped"}]
            t += 30
    S += [{"goal": ("stop",), "until": ("speed_le", 1.5), "timeout": 16, "label": "arrive"},
          {"selector": "P", "goal": ("wait",), "until": ("time", 1.5), "timeout": 2, "label": "park"}]
    return S


def get_run(run_id: str):
    """Resolve a run id to {name, desc, style, steps}. Handles both the named
    scenarios and the procedural `drive_<minutes>` durations."""
    if run_id in RUNS:
        r = RUNS[run_id]
        return {"name": r["name"], "desc": r["desc"], "style": r.get("style", "normal"), "steps": r["steps"]}
    if run_id.startswith("drive_"):
        m = int(run_id.split("_")[1])
        return {"name": "%d-minute drive" % m, "desc": "Procedural realistic %d-minute drive: city, highway, traffic, lights, hard braking." % m,
                "style": "normal", "steps": build_drive(m)}
    return None


def run_list():
    named = [{"id": k, "name": RUNS[k]["name"], "desc": RUNS[k]["desc"],
              "style": RUNS[k].get("style", "normal")} for k in RUN_ORDER]
    drives = [{"id": "drive_%d" % m, "name": "%d-minute drive" % m,
               "desc": "Realistic %d-minute drive: city, highway, traffic, lights, hard braking." % m,
               "style": "normal"} for m in DURATIONS]
    return named + drives
