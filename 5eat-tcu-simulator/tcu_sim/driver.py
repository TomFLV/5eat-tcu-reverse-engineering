"""A closed-loop driver model: given a goal and a driving style, it modulates the
throttle and brake the way a person does - ease onto the throttle to reach a
target speed, back off as you approach it, coast or brake proportionally to how
much speed you need to shed. Runs specify GOALS, not pedal numbers, so the pedal
positions emerge from realistic control instead of being hardcoded.

Goal forms:  ("cruise", kmh)  reach and hold a speed
             ("stop",)         come to a smooth stop
             ("emergency",)    brake hard to a stop
             ("wait",)         stopped, foot on brake
"""
from __future__ import annotations

# Style -> how this driver behaves. accel_gain sets how hard they chase a speed
# error; max_thr caps casual throttle; comfort/hard set braking firmness.
STYLES = {
    "calm":     dict(accel_gain=0.045, max_thr=0.18, hold_ff=0.006, brake_gain=0.09, min_thr=0.05),
    "normal":   dict(accel_gain=0.075, max_thr=0.30, hold_ff=0.007, brake_gain=0.14, min_thr=0.06),
    "spirited": dict(accel_gain=0.150, max_thr=0.60, hold_ff=0.008, brake_gain=0.22, min_thr=0.09),
}


def control(style: str, cur_kmh: float, goal) -> tuple[float, float]:
    """Return (throttle, brake) in 0..1 for this tick toward `goal`."""
    p = STYLES.get(style, STYLES["normal"])
    cur = cur_kmh / 3.6                     # m/s
    kind = goal[0]

    if kind == "wait":
        return 0.0, 1.0
    if kind == "emergency":
        return 0.0, 1.0

    target = (goal[1] / 3.6) if kind == "cruise" else 0.0
    err = target - cur                       # m/s, + = need to speed up

    if kind == "stop":
        if cur < 0.4:
            return 0.0, 0.8
        return 0.0, min(0.55, 0.10 + 0.020 * cur)

    # cruise / reach-and-hold - ONE continuous law so nothing toggles near the
    # target. `hold` is the throttle that maintains the current speed against
    # drag; demand adds a proportional term for the speed error.
    hold = 0.04 + p["hold_ff"] * cur
    demand = hold + p["accel_gain"] * err
    if demand >= 0.0:
        return min(p["max_thr"], demand), 0.0
    # demand < 0 -> need to lose speed. Coast (engine braking) for mild overshoot;
    # only touch the brake once well over target, and ramp it in continuously.
    over = -err
    if over < 2.0:                           # within ~7 km/h over: just coast
        return 0.0, 0.0
    return 0.0, min(1.0, p["brake_gain"] * (over - 2.0))
