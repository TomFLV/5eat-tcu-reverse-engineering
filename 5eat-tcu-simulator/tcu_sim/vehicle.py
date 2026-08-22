"""Longitudinal vehicle + driveline model for the 5EAT TCU simulator.

This is a real dynamic model, not a message player: driver inputs (throttle,
brake, selector) drive engine torque through the *current gear ratio* the TCU
commands, and the resulting force accelerates the car. Engine RPM and road speed
are STATE that integrates over time. The TCU's commanded gear (read from its
0x420 broadcast) closes the loop, so when the TCU upshifts the ratio changes and
RPM drops exactly as in a real car.

Kept deliberately simple but physically plausible; scale constants are tuned for
a ~2006 Tribeca (mass, ratios, wheel size) and refined against the TCU on-bench.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import time

# 5EAT (Aisin AWTF-21) gear ratios - from TRANSMISSION SECTION.pdf.
GEAR_RATIOS = {1: 3.841, 2: 2.352, 3: 1.529, 4: 1.000, 5: 0.839}
REVERSE_RATIO = 3.457
FINAL_DRIVE = 3.583


# 5EAT operating elements per gear (which clutch-apply solenoids are pressurized).
# Names from the firmware SOLENOID_TO_MAP: I/C input clutch, D/C direct clutch,
# F/B front brake, H&LR/C high&low-reverse clutch. Engagement is MODELLED for
# demo; the authoritative per-solenoid current/pressure comes from the TCU over
# SSM (K-line), not CAN.
APPLY_TABLE = {
    1:  {"IC", "HLR"},
    2:  {"IC", "FB"},
    3:  {"IC", "DC"},
    4:  {"IC", "DC", "FB"},
    5:  {"DC", "FB"},
    -1: {"DC", "HLR"},   # Reverse
    0:  set(),            # Park / Neutral
}


def solenoid_model(gear: int, throttle: float, lockup: bool):
    """Return (solenoid duty/engagement dict, line pressure kPa). Demo model."""
    eng = APPLY_TABLE.get(gear, set())
    on = lambda k: 100 if k in eng else 0
    sol = {
        "PL": round(25 + throttle * 70),        # pressure-control (line) duty %
        "LU": 95 if lockup else 0,              # lockup solenoid duty %
        "IC": on("IC"), "DC": on("DC"),
        "FB": on("FB"), "HLR": on("HLR"),
        "AWD": round(40 + throttle * 40),       # transfer-clutch duty %
    }
    line_kpa = round(350 + throttle * 1050)     # approx line pressure
    return sol, line_kpa
WHEEL_RADIUS = 0.34          # m (225/60R17-ish)
DRIVELINE_EFF = 0.85

MASS = 2050.0                # kg (curb + driver, heavy AWD 5EAT car)
G = 9.81
CRR = 0.013                  # rolling resistance coeff
RHO = 1.20                   # air density
CDA = 0.80                   # Cd * frontal area (m^2), boxy SUV
MAX_BRAKE_FORCE = 22000.0    # N (all wheels) - ~1.15g, holds the car in a stall test
TIRE_MU = 1.08               # AWD launch grip ceiling (~1.08g), tuned to real 0-60
MAX_TRACTION_FORCE = TIRE_MU * MASS * G
# Beyond the grip ceiling the launch is traction-limited, but more power still
# helps a little (weight transfer, sustained torque) rather than clipping every
# car to an identical number. Fraction of the over-limit force that still counts,
# and a hard cap on that bonus so it can't run away.
TRACTION_EXCESS = 0.10
TRACTION_BONUS_CAP = 0.45 * MAX_TRACTION_FORCE

BASE_PEAK_TORQUE = 300.0     # Nm at ~4000 rpm = stock Tribeca EZ30 (~250 hp)

IDLE_RPM = 700.0
MAX_RPM = 6200.0
CONVERTER_STALL_SPAN = 2200.0  # extra rpm the engine pulls against a slipping TC
CONVERTER_MAX_MULT = 2.2       # torque multiplication at full slip


def engine_torque_shape(rpm: float) -> float:
    """Normalized WOT torque hump, peaks at 1.0 near 4000 rpm."""
    rpm = max(0.0, min(rpm, MAX_RPM))
    if rpm < 4000.0:
        return 0.5 + 0.5 * (rpm / 4000.0)          # 0.5 -> 1.0
    return 1.0 - 0.30 * ((rpm - 4000.0) / (MAX_RPM - 4000.0))  # 1.0 -> 0.7


# Power presets: label -> peak crank torque (Nm). Torque ~ hp*1.2 at the hump.
POWER_LEVELS = {
    "Stock ~250hp": 300.0,
    "400 hp": 480.0,
    "600 hp": 720.0,
    "800 hp": 960.0,
    "1000+ hp": 1200.0,
}


@dataclass
class SimState:
    # --- driver / operator inputs ---
    ignition: bool = True
    selector: str = "P"          # P R N D M
    manual_gear: int = 1         # commanded gear in M mode (1..5)
    throttle: float = 0.0        # 0..1
    brake: float = 0.0           # 0..1
    drive_mode: int = 5          # SI-DRIVE / drive-mode select (0x515 B7)

    # --- simulated plant state ---
    engine_rpm: float = IDLE_RPM
    speed_kmh: float = 0.0       # forward +, reverse handled by selector

    # --- feedback decoded from the TCU (closed loop) ---
    tcu_current_gear: int = 0    # 1..5, 0 = P/N, -1 = R  (from 0x420 B1 hi nibble)
    tcu_target_gear: int = 0
    tcu_lockup: bool = False
    tcu_selector_code: int = 0
    tcu_atf_temp_c: float = 0.0
    tcu_dtcs: list = field(default_factory=list)
    tcu_output_shaft: int = 0
    can_link_up: bool = False    # are we hearing 0x420/421/422 at all

    # --- transmission internals (2 speed sensors, slip, pressure, solenoids) ---
    turbine_rpm: float = 0.0     # input/turbine speed sensor (SSM on real HW)
    output_rpm: float = 0.0      # output-shaft speed sensor (0x420 B4 on real HW)
    tcc_slip: float = 0.0        # engine - turbine (converter slip)
    line_pressure_kpa: float = 0.0
    shifting: str = ""           # "", "up", "down"  (0x422 B1 bits 3/4)
    solenoids: dict = field(default_factory=dict)
    atf_temp1: float = 25.0      # ATF temp sensor 1 (near converter, hotter)
    atf_temp2: float = 25.0      # ATF temp sensor 2 (pan/cooler side, cooler)
    coolant_c: float = 25.0      # engine coolant temp - ATF is tied to this
    ambient_c: float = 25.0

    # derived / bookkeeping
    pedal_pct: float = 0.0
    def gear_label(self) -> str:
        if self.selector in ("P", "N"):
            return self.selector
        if self.selector == "R":
            return "R"
        g = self.tcu_current_gear
        if g >= 1:
            return str(g)
        return "-"


class Vehicle:
    """Integrates SimState forward under the current driver inputs and the gear
    the TCU is commanding."""

    def __init__(self) -> None:
        self.s = SimState()
        self._last = time.perf_counter()
        self.peak_torque = BASE_PEAK_TORQUE   # scaled by the power selector
        self.gear_ratios = dict(GEAR_RATIOS)  # per-ROM; replaced by romdata.apply_rom
        self._atf = 25.0                      # bulk ATF temperature state (deg C)
        self._coolant = 25.0                  # engine coolant temperature (deg C)

    def set_power(self, peak_torque_nm: float) -> None:
        self.peak_torque = max(150.0, float(peak_torque_nm))

    def _torque(self, rpm: float) -> float:
        return engine_torque_shape(rpm) * self.peak_torque

    def _active_ratio(self) -> float:
        s = self.s
        gr = self.gear_ratios
        if s.selector == "R":
            return -REVERSE_RATIO
        if s.selector == "M":
            return gr.get(s.manual_gear, gr[1])
        if s.selector == "D":
            g = s.tcu_current_gear if s.tcu_current_gear >= 1 else 1
            return gr.get(g, gr[1])
        return 0.0  # P / N: driveline open

    def step(self, dt: float | None = None) -> SimState:
        now = time.perf_counter()
        if dt is None:
            dt = now - self._last
        self._last = now
        dt = max(1e-4, min(dt, 0.1))
        self._dt = dt
        s = self.s
        s.pedal_pct = s.throttle * 100.0

        if not s.ignition:
            s.engine_rpm = max(0.0, s.engine_rpm - 4000.0 * dt)
            s.speed_kmh = self._coast(s.speed_kmh, 0.0, s.brake, dt)
            self._set_internals(0.0)
            return s

        ratio = self._active_ratio()
        v_ms = s.speed_kmh / 3.6
        wheel_rps = abs(v_ms) / (2 * 3.141592653589793 * WHEEL_RADIUS)

        if ratio == 0.0:
            # Park / Neutral: engine free-revs, car coasts.
            target = IDLE_RPM + s.throttle * (MAX_RPM - IDLE_RPM) * 0.9
            s.engine_rpm += (target - s.engine_rpm) * min(1.0, 6.0 * dt)
            s.speed_kmh = self._coast(s.speed_kmh, 0.0, s.brake, dt)
            self._set_internals(0.0)
            return s

        # In gear: torque converter couples engine to driveline.
        input_rpm = wheel_rps * 60.0 * FINAL_DRIVE * abs(ratio)
        stall_rpm = IDLE_RPM + s.throttle * CONVERTER_STALL_SPAN
        # engine rides the higher of "slipping against the converter" and "coupled"
        target_rpm = max(stall_rpm, input_rpm)
        target_rpm = min(target_rpm, MAX_RPM)
        s.engine_rpm += (target_rpm - s.engine_rpm) * min(1.0, 8.0 * dt)

        slip = max(0.0, s.engine_rpm - input_rpm)
        mult = 1.0 + min(1.0, slip / max(1.0, CONVERTER_STALL_SPAN)) * (CONVERTER_MAX_MULT - 1.0)

        eng_tq = self._torque(s.engine_rpm) * s.throttle
        wheel_tq = eng_tq * mult * abs(ratio) * FINAL_DRIVE * DRIVELINE_EFF
        f_drive = wheel_tq / WHEEL_RADIUS
        if f_drive > MAX_TRACTION_FORCE:              # grip-limited, but not a hard clip
            excess = f_drive - MAX_TRACTION_FORCE
            f_drive = MAX_TRACTION_FORCE + min(TRACTION_BONUS_CAP, excess * TRACTION_EXCESS)
        direction = -1.0 if ratio < 0 else 1.0

        # resistances always oppose motion
        v_signed = v_ms if direction > 0 else -v_ms  # not used further; keep simple
        f_drag = 0.5 * RHO * CDA * v_ms * v_ms
        f_roll = CRR * MASS * G
        f_brake = s.brake * MAX_BRAKE_FORCE

        # net longitudinal force along travel direction
        f_net = f_drive - f_drag - f_roll - f_brake
        a = f_net / MASS  # m/s^2 along drive direction

        new_v_ms = v_ms + a * dt
        if new_v_ms < 0:
            new_v_ms = 0.0  # converter won't drive you backwards in D, or fwd in R
        s.speed_kmh = new_v_ms * 3.6
        self._set_internals(ratio)
        return s

    def _set_internals(self, ratio: float) -> None:
        """Derive the two speed-sensor values + converter slip from current state.
        output shaft = wheels x final drive; turbine (input) = output x gear ratio;
        slip = engine - turbine."""
        s = self.s
        v = s.speed_kmh / 3.6
        wheel_rps = v / (2 * 3.141592653589793 * WHEEL_RADIUS)
        s.output_rpm = wheel_rps * 60.0 * FINAL_DRIVE
        s.turbine_rpm = s.output_rpm * abs(ratio) if ratio else 0.0
        s.tcc_slip = max(0.0, s.engine_rpm - s.turbine_rpm)
        self._update_atf(getattr(self, "_dt", 0.02))

    def _update_atf(self, dt: float) -> None:
        """Real-world ATF thermal behaviour. The ATF is coupled to the ENGINE via
        the cooler in the radiator, so it tracks coolant temperature (~90 C
        operating) as its baseline - running HOTTER than coolant under converter
        load, settling near it on the highway, and never sitting far colder than
        the engine once warm. Both warm up together from a cold start."""
        s = self.s
        amb = s.ambient_c
        # power factor: heat generated rises with the engine's output (torque).
        pf = self.peak_torque / BASE_PEAK_TORQUE          # 1.0 stock .. ~4.0 at 1000hp
        # engine coolant: thermostat holds ~90 C, but sustained power+load push it up.
        c_target = (amb + 66.0 + min(20.0, s.throttle * pf * 4.5)) if s.ignition else amb
        c_tau = 150.0 if s.ignition else 1500.0
        self._coolant += (c_target - self._coolant) * min(1.0, dt / c_tau)
        s.coolant_c = round(self._coolant, 1)
        # ATF steady-state sits ABOVE coolant by (heat generated / cooler capacity).
        # Heat comes from converter slip (big) + engine load, and SCALES WITH POWER.
        # The cooler (in the radiator) rejects more with airflow, so highway cruise
        # stays near coolant while city/launch/tow load runs hot - more so with power.
        scale = 1.0 + 0.6 * (pf - 1.0)                    # 1.0 stock .. ~2.8 at 1000hp
        load_heat = (0.005 * s.tcc_slip + 14.0 * s.throttle) * scale
        airflow = 1.0 + s.speed_kmh / 50.0
        delta = min(60.0, load_heat / (0.35 * airflow))   # ATF degrees above coolant
        atf_target = max(amb, min(150.0, self._coolant + delta))
        self._atf += (atf_target - self._atf) * min(1.0, dt / 130.0)
        s.atf_temp1 = round(self._atf + min(8.0, 0.003 * s.tcc_slip * scale), 1)
        s.atf_temp2 = round(self._atf - 3.0, 1)

    @staticmethod
    def _coast(speed_kmh: float, _grade: float, brake: float, dt: float) -> float:
        v = speed_kmh / 3.6
        f = 0.5 * RHO * CDA * v * v + CRR * MASS * G + brake * MAX_BRAKE_FORCE
        v = max(0.0, v - (f / MASS) * dt)
        return v * 3.6
