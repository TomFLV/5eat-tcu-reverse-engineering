"""Real-time orchestration: step the vehicle model, publish plant state to the
CAN gateway (which broadcasts the whole monitored bus), and fold the TCU's
feedback back into the model - the closed loop that makes the TCU actually shift.
"""
from __future__ import annotations
import threading
import time

import json
import os
import time as _time

from .vehicle import Vehicle, SimState, POWER_LEVELS, solenoid_model
from .can_gateway import CanGateway
from .runs import RUNS, get_run
from .messages import encode_all_rx, encode_tx_demo, decode_frame_display, FRAME_INFO
from . import driver
from . import romdata
from .paths import LOG_DIR  # frozen-safe: next to the .exe when packaged


class Simulator:
    def __init__(self, tick_hz: float = 100.0):
        self.vehicle = Vehicle()
        self.gw = CanGateway()
        self.tick_dt = 1.0 / tick_hz
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.running = False
        self.can_ok = False          # False => demo mode (internal transmission)
        self.can_error = ""
        self.profile = "manual"      # manual | normal | aggressive
        self.power_label = "Stock ~250hp"
        self._phase = ""
        self._phase_t = 0.0
        self._shift_cd = 0.0         # demo-transmission shift cooldown (s)
        self._shift_flash = 0.0      # how long to hold the up/down shift flag
        # automated run executor
        self._run = None             # active run id, or None
        self._run_style = "normal"
        self._run_steps = []
        self._run_i = 0
        self._run_t = 0.0
        self._run_elapsed = 0.0
        self._run_events = []
        self._run_summary = None
        self._run_maxspeed = 0.0
        self._run_t100 = None
        self._run_prev_gear = 0
        # selected firmware ROM
        self.rom_id = None
        self.rom_name = ""
        self.rom_ratios_valid = False
        self.rom_si_drive = True

    # ---- driver input API (called by the server) ----
    def set_input(self, **kw) -> None:
        s = self.vehicle.s
        # always-allowed, don't disturb an active run/profile
        if "power" in kw and kw["power"] in POWER_LEVELS:
            self.vehicle.set_power(POWER_LEVELS[kw["power"]])
            self.power_label = kw["power"]
        if "ignition" in kw:
            s.ignition = bool(kw["ignition"])
        if "drive_mode" in kw:
            s.drive_mode = max(0, min(7, int(kw["drive_mode"])))
        if "profile" in kw and kw["profile"] in ("manual", "normal", "aggressive"):
            self._run = None
            self.profile = kw["profile"]
            self._phase = ""
            self._phase_t = 0.0
            if self.profile != "manual":
                s.selector = "D"
            else:
                s.throttle = s.brake = 0.0

        # A driving input from the USER takes over: stop any run/profile and
        # release the pedals, so e.g. shifting to Park never leaves throttle
        # stuck from an auto run.
        driving = any(k in kw for k in ("throttle", "brake", "selector", "manual_gear"))
        if driving and (self._run is not None or self.profile != "manual"):
            self._run = None
            self.profile = "manual"
            s.throttle = 0.0
            s.brake = 0.0
        if driving:
            if "throttle" in kw:
                s.throttle = max(0.0, min(1.0, float(kw["throttle"])))
            if "brake" in kw:
                s.brake = max(0.0, min(1.0, float(kw["brake"])))
            if "selector" in kw and kw["selector"] in ("P", "R", "N", "D", "M"):
                s.selector = kw["selector"]
            if "manual_gear" in kw:
                s.manual_gear = max(1, min(5, int(kw["manual_gear"])))

    def set_rom(self, rom_id: str) -> dict:
        """Select a firmware ROM and load its real parameters into the model."""
        p = romdata.apply_rom(self.vehicle, rom_id)
        self.rom_id = rom_id
        self.rom_name = p.get("name", rom_id)
        self.rom_ratios_valid = p.get("ratios_valid", False)
        self.rom_si_drive = p.get("si_drive", True)
        if not self.rom_si_drive:
            self.vehicle.s.drive_mode = 0     # no SI-DRIVE: mode select inactive
        return p

    # ---- automated run executor ----
    def start_run(self, run_id: str, power: str | None = None) -> None:
        meta = get_run(run_id)
        if meta is None:
            return
        if power and power in POWER_LEVELS:
            self.vehicle.set_power(POWER_LEVELS[power])
            self.power_label = power
        self.profile = "manual"
        self._run = run_id
        self._run_style = meta.get("style", "normal")
        self._run_steps = meta["steps"]
        self._run_i = 0
        self._run_t = 0.0
        self._run_elapsed = 0.0
        self._run_events = []
        self._run_summary = None
        self._run_maxspeed = 0.0
        self._run_t100 = None
        self._run_prev_gear = self.vehicle.s.tcu_current_gear

    def stop_run(self) -> None:
        self._run = None
        s = self.vehicle.s
        s.throttle = 0.0
        s.brake = 0.4

    def _run_tick(self, dt: float) -> None:
        s = self.vehicle.s
        step = self._run_steps[self._run_i]
        # selector/gear are instant; the pedals SLEW to target like a real foot -
        # gentle on the throttle, quicker on the brake - so nothing snaps to 50%.
        if "selector" in step:
            s.selector = step["selector"]
        if "manual_gear" in step:
            s.manual_gear = step["manual_gear"]
        if "goal" in step:
            # realistic: the driver model decides the pedals to reach the goal.
            style = step.get("style", self._run_style)
            thr, brk = driver.control(style, s.speed_kmh, step["goal"])
            s.throttle += max(-0.9*dt, min(0.9*dt, thr - s.throttle))
            s.brake += max(-4.0*dt, min(4.0*dt, brk - s.brake))
        else:
            # explicit pedals (deliberate test inputs like WOT / stall), slewed
            if "throttle" in step:
                rate = step.get("thr_rate", 0.9)
                s.throttle += max(-rate*dt, min(rate*dt, step["throttle"] - s.throttle))
            if "brake" in step:
                rate = step.get("brk_rate", 2.5)
                s.brake += max(-rate*dt, min(rate*dt, step["brake"] - s.brake))
        self._run_t += dt
        self._run_elapsed += dt
        self._run_maxspeed = max(self._run_maxspeed, s.speed_kmh)
        if self._run_t100 is None and s.speed_kmh >= 100:
            self._run_t100 = round(self._run_elapsed, 2)
        kind, val = step["until"]
        done = ((kind == "speed_ge" and s.speed_kmh >= val) or
                (kind == "speed_le" and s.speed_kmh <= val) or
                (kind == "time" and self._run_t >= val) or
                (kind == "rpm_ge" and s.engine_rpm >= val) or
                (kind == "rpm_le" and s.engine_rpm <= val))
        if step.get("timeout") and self._run_t >= step["timeout"]:
            done = True
        if done:
            self._run_i += 1
            self._run_t = 0.0
            if self._run_i >= len(self._run_steps):
                self._finish_run()

    def _run_capture(self) -> None:
        """Called after the gear is decided each tick to log shift events."""
        s = self.vehicle.s
        g = s.tcu_current_gear
        if g != self._run_prev_gear and g >= 1 and self._run_prev_gear >= 1:
            self._run_events.append({
                "phase": self._run_steps[min(self._run_i, len(self._run_steps)-1)].get("label", ""),
                "shift": "%d-%d" % (self._run_prev_gear, g),
                "dir": "up" if g > self._run_prev_gear else "down",
                "speed": round(s.speed_kmh), "rpm": round(s.engine_rpm),
                "t": round(self._run_elapsed, 1),
            })
        self._run_prev_gear = g

    def _finish_run(self) -> None:
        s = self.vehicle.s
        self._run_summary = {
            "run": self._run, "power": self.power_label,
            "duration": round(self._run_elapsed, 1),
            "t100": self._run_t100, "max_speed": round(self._run_maxspeed),
            "shifts": len(self._run_events),
            "dtcs": list(s.tcu_dtcs),
        }
        self._run = None
        s.throttle = 0.0
        s.brake = 0.4

    def can_frames(self) -> list:
        """The live CAN bus for the monitor: real captured frames when hardware is
        connected, generated frames in demo. Each: id, name, src, bytes, decode, n."""
        s = self.vehicle.s
        if self.can_ok:
            raw = list(self.gw.get_frames().values())
        else:
            raw = ([{"id": cid, "src": "car", "bytes": hx, "n": 0} for cid, hx in encode_all_rx(s).items()] +
                   [{"id": cid, "src": "TCU", "bytes": hx, "n": 0} for cid, hx in encode_tx_demo(s).items()])
        for f in raw:
            info = FRAME_INFO.get(f["id"], ("", ""))
            f["name"] = info[0]
            f["decode"] = decode_frame_display(f["id"], f["bytes"])
            # space the hex for readability
            f["bytes"] = " ".join(f["bytes"][i:i+2] for i in range(0, len(f["bytes"]), 2))
        raw.sort(key=lambda f: f["id"])
        return raw

    def clear_dtcs(self) -> None:
        self.vehicle.s.tcu_dtcs = []
        self.gw.clear_dtc_cache()

    def snapshot(self) -> dict:
        s = self.vehicle.s
        return {
            "ignition": s.ignition, "selector": s.selector,
            "manual_gear": s.manual_gear, "throttle": round(s.throttle, 3),
            "brake": round(s.brake, 3), "drive_mode": s.drive_mode,
            "engine_rpm": round(s.engine_rpm), "speed_kmh": round(s.speed_kmh, 1),
            "gear_label": s.gear_label(),
            "pedal_pct": round(s.throttle * 100), "brake_pct": round(s.brake * 100),
            "engine_load": round(48 + s.throttle * 180), "ambient_c": round(s.ambient_c),
            "coolant_c": round(s.coolant_c, 1),
            "tcu_current_gear": s.tcu_current_gear,
            "tcu_target_gear": s.tcu_target_gear,
            "tcu_lockup": s.tcu_lockup,
            "tcu_selector_code": s.tcu_selector_code,
            "tcu_atf_temp_c": round(s.atf_temp1, 1),
            "atf1": round(s.atf_temp1, 1), "atf2": round(s.atf_temp2, 1),
            "tcu_dtcs": s.tcu_dtcs,
            "turbine_rpm": round(s.turbine_rpm), "output_rpm": round(s.output_rpm),
            "tcc_slip": round(s.tcc_slip), "line_pressure_kpa": round(s.line_pressure_kpa),
            "shifting": s.shifting, "solenoids": s.solenoids,
            "can_link_up": s.can_link_up,
            "tx_count": self.gw.tx_count, "rx_count": self.gw.rx_count,
            "tx_errors": self.gw.tx_errors,
            "demo": not self.can_ok, "can_error": self.can_error,
            "can_frames": self.can_frames(),
            "profile": self.profile, "power": self.power_label,
            "phase": self._phase,
            "rom_id": self.rom_id, "rom_name": self.rom_name,
            "rom_ratios_valid": self.rom_ratios_valid, "si_drive": self.rom_si_drive,
            "gear_ratios": [round(self.vehicle.gear_ratios.get(i, 0), 3) for i in range(1, 6)],
            "run_active": self._run is not None, "run_id": self._run,
            "run_name": (get_run(self._run)["name"] if self._run else ""),
            "run_phase": (self._run_steps[min(self._run_i, len(self._run_steps)-1)].get("label", "")
                          if self._run else ""),
            "run_elapsed": round(self._run_elapsed, 1) if self._run else 0,
            "run_events": self._run_events[-8:],
            "run_summary": self._run_summary,
        }

    # ---- lifecycle ----
    def start(self) -> None:
        try:
            self.gw.start()
            self.can_ok = True
        except Exception as e:
            # No CANtact / no TCU: run fully in demo mode with an internal
            # transmission model so the UI is drivable without hardware.
            self.can_ok = False
            self.can_error = str(e)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.running = True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self.can_ok:
            self.gw.close()
        self.running = False

    def _loop(self) -> None:
        last = time.perf_counter()
        while not self._stop.is_set():
            now = time.perf_counter()
            dt = now - last
            last = now
            if self._run is not None:
                self._run_tick(dt)
            elif self.profile != "manual":
                self._auto_drive(dt)
            self.vehicle.step(dt)
            if self.can_ok:
                self.gw.set_state(self.vehicle.s)
                self.gw.apply_feedback(self.vehicle.s)
            else:
                self._internal_shift(dt)
            if self._run is not None:
                self._run_capture()
            time.sleep(self.tick_dt)

    def _auto_drive(self, dt: float) -> None:
        """Scripted test drivers. Speed-triggered so they behave across all power
        levels. 'normal' = gentle commuter cycle; 'aggressive' = WOT launch / hard
        brake loop to hammer the shift schedule."""
        s = self.vehicle.s
        self._phase_t += dt
        if not self._phase:
            self._phase = "accel" if self.profile == "normal" else "launch"
            self._phase_t = 0.0

        if self.profile == "normal":
            if self._phase == "accel":
                s.throttle, s.brake = 0.40, 0.0
                if s.speed_kmh >= 65:
                    self._phase, self._phase_t = "cruise", 0.0
            elif self._phase == "cruise":
                s.throttle = 0.16 if s.speed_kmh < 65 else 0.06
                s.brake = 0.0
                if self._phase_t > 7:
                    self._phase = "decel"
            else:  # decel
                s.throttle, s.brake = 0.0, 0.30
                if s.speed_kmh <= 18:
                    self._phase, self._phase_t = "accel", 0.0
        else:  # aggressive
            if self._phase == "launch":
                s.throttle, s.brake = 1.0, 0.0
                if s.speed_kmh >= 130 or self._phase_t > 20:
                    self._phase, self._phase_t = "brake", 0.0
            else:  # brake
                s.throttle, s.brake = 0.0, 1.0
                if s.speed_kmh <= 12:
                    self._phase, self._phase_t = "launch", 0.0

    def _internal_shift(self, dt: float) -> None:
        """Demo-mode stand-in for the TCU: pick a gear (RPM-based schedule with
        kickdown + dwell), flag up/down shift events, and model the solenoid
        activation + line pressure so the transmission panel is populated with no
        hardware. On real hardware these come from the TCU (CAN + SSM)."""
        s = self.vehicle.s
        s.can_link_up = False
        if self._shift_cd > 0:
            self._shift_cd -= dt
        if self._shift_flash > 0:
            self._shift_flash -= dt
            if self._shift_flash <= 0:
                s.shifting = ""
        prev = s.tcu_current_gear

        if s.selector == "R":
            s.tcu_current_gear = s.tcu_target_gear = -1
            s.tcu_lockup = False
        elif s.selector in ("P", "N"):
            s.tcu_current_gear = s.tcu_target_gear = 0
            s.tcu_lockup = False
        elif s.selector == "M":
            s.tcu_current_gear = s.tcu_target_gear = s.manual_gear
            s.tcu_lockup = s.manual_gear >= 4 and s.speed_kmh > 55
        else:  # Drive: upshift rpm rises with throttle (cruise-low -> redline WOT)
            up_rpm = 2200.0 + s.throttle * 3700.0
            dn_rpm = 1150.0 + s.throttle * 1550.0
            g = prev if prev >= 1 else 1
            # margin past the boundary so small rpm fluctuations at cruise don't
            # toggle a shift, plus a dwell after any shift = no hunting.
            if self._shift_cd <= 0:
                if g < 5 and s.engine_rpm > up_rpm + 150:
                    g += 1
                    self._shift_cd = 1.2
                elif g > 1 and s.engine_rpm < dn_rpm - 150 and s.speed_kmh > 4:
                    g -= 1
                    self._shift_cd = 1.2
            s.tcu_current_gear = s.tcu_target_gear = g
            s.tcu_lockup = g >= 4 and s.speed_kmh > 60 and s.throttle < 0.5

        cur = s.tcu_current_gear
        if cur != prev and cur >= 1 and prev >= 1:
            s.shifting = "up" if cur > prev else "down"
            self._shift_flash = 0.5
        s.solenoids, s.line_pressure_kpa = solenoid_model(cur, s.throttle, s.tcu_lockup)


def _telem_row(sim: "Simulator") -> dict:
    s = sim.vehicle.s
    return {
        "t": round(sim._run_elapsed, 2), "phase": (
            sim._run_steps[min(sim._run_i, len(sim._run_steps)-1)].get("label", "")
            if sim._run else ""),
        "speed": round(s.speed_kmh, 1), "rpm": round(s.engine_rpm),
        "gear": s.gear_label(), "throttle": round(s.throttle, 3), "brake": round(s.brake, 3),
        "turbine": round(s.turbine_rpm), "output": round(s.output_rpm),
        "slip": round(s.tcc_slip), "line_kpa": round(s.line_pressure_kpa),
        "lockup": s.tcu_lockup, "solenoids": dict(s.solenoids),
        "atf1": round(s.atf_temp1, 1), "atf2": round(s.atf_temp2, 1),
        "coolant": round(s.coolant_c, 1),
        "dtcs": list(s.tcu_dtcs),
        "can": {"rx": encode_all_rx(s), "tx": encode_tx_demo(s)},
    }


def run_headless(run_id: str, power: str | None = None, style: str | None = None,
                 rom: str | None = None, sample_hz: float = 20.0,
                 dt: float = 0.02, max_seconds: float = 240.0) -> dict:
    """Run a scenario to completion FASTER than real time (no CAN, no sleep),
    reusing the exact live run/driver/transmission logic, and return a structured
    result: {run, power, rom, summary, events, telemetry}. This is the AI-facing
    entry point - deterministic, machine-readable, repeatable."""
    sim = Simulator()
    sim.can_ok = False
    if rom:
        try:
            sim.set_rom(rom)
        except Exception:
            pass
    sim.start_run(run_id, power)
    if style:
        sim._run_style = style
    # duration drives need a bigger budget than the default
    if run_id.startswith("drive_"):
        try:
            max_seconds = int(run_id.split("_")[1]) * 60 * 1.4
        except Exception:
            pass
    telem = []
    next_s = 0.0
    sdt = 1.0 / sample_hz
    guard = 0
    limit = int(max_seconds / dt)
    while sim._run is not None and guard < limit:
        sim._run_tick(dt)
        sim.vehicle.step(dt)
        sim._internal_shift(dt)
        sim._run_capture()
        if sim._run_elapsed >= next_s:
            telem.append(_telem_row(sim))
            next_s += sdt
        guard += 1
    if sim._run is not None:          # hit the guard - finalize a partial summary
        sim._finish_run()
    result = {
        "run": run_id, "power": sim.power_label,
        "rom": rom, "rom_name": sim.rom_name, "rom_ratios_valid": sim.rom_ratios_valid,
        "gear_ratios": [round(sim.vehicle.gear_ratios.get(i, 0), 3) for i in range(1, 6)],
        "summary": sim._run_summary, "events": sim._run_events, "telemetry": telem,
    }
    result["log_file"] = _write_log(result)
    return result


def _write_log(result: dict) -> str:
    """Write a run to a JSONL log: header line (meta+summary), then one line per
    telemetry sample (full CAN capture). Returns the file name."""
    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    rom_tag = (result.get("rom") or "default").split(".")[0][:20]
    pw_tag = (result.get("power") or "def").split()[0].replace("+", "plus").replace("~", "")
    base = "%s_%s_%s_%s" % (result["run"], rom_tag, pw_tag, stamp)
    name, k = base + ".jsonl", 1
    while os.path.exists(os.path.join(LOG_DIR, name)):   # guarantee uniqueness
        name, k = "%s_%d.jsonl" % (base, k), k + 1
    path = os.path.join(LOG_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        header = {"type": "header", "run": result["run"], "power": result["power"],
                  "rom": result["rom"], "rom_name": result["rom_name"],
                  "gear_ratios": result["gear_ratios"], "summary": result["summary"],
                  "events": result["events"], "generated": stamp}
        f.write(json.dumps(header) + "\n")
        for row in result["telemetry"]:
            f.write(json.dumps(row) + "\n")
    return name


def selftest(seconds: int = 30) -> None:
    """Phase-1 keep-alive proof (headless). Idle in Park, then blip throttle,
    and report whether the TCU stays alive (no P1718) and reacts."""
    sim = Simulator()
    print("opening CAN + starting sim ...", flush=True)
    sim.start()
    t0 = time.perf_counter()
    try:
        while time.perf_counter() - t0 < seconds:
            t = time.perf_counter() - t0
            # drive profile: 0-5s idle P, 5s shift to D, 8s throttle ramp
            if t > 5:
                sim.set_input(selector="D")
            if t > 8:
                sim.set_input(throttle=min(0.6, (t - 8) / 6.0))
            time.sleep(1.0)
            s = sim.snapshot()
            print("t=%4.1f  link=%s  rpm=%4d spd=%5.1f gear=%s  "
                  "tx=%d rx=%d err=%d  dtc=%s"
                  % (t, s["can_link_up"], s["engine_rpm"], s["speed_kmh"],
                     s["gear_label"], s["tx_count"], s["rx_count"],
                     s["tx_errors"], ",".join(s["tcu_dtcs"]) or "none"),
                  flush=True)
    finally:
        sim.stop()
        print("stopped.", flush=True)


if __name__ == "__main__":
    import sys
    selftest(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
