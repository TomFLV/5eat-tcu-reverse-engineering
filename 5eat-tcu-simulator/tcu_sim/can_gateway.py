"""CAN I/O for the simulator: drives the whole monitored message set onto the
bus at each ID's rate, and reads the TCU's broadcasts back.

Runs the CANtact Pro natively on Windows through WinUSB/libusb + python-can's
gs_usb backend - no WSL, no usbipd (that path leaks the gs_usb TX echo pool and
wedges after ~1200 frames). pyusb's default backend can't find a libusb DLL on
this machine, so GsUsb.scan() silently returns 0 devices; patch usb.core.find to
the bundled libusb-package backend BEFORE importing python-can.
"""
from __future__ import annotations
import threading
import time
from typing import Optional

import libusb_package
import usb.core

_BACKEND = libusb_package.get_libusb1_backend()
_orig_find = usb.core.find


def _find(*a, **k):
    k.setdefault("backend", _BACKEND)
    return _orig_find(*a, **k)


usb.core.find = _find  # must precede `import can`

import can  # noqa: E402

from .messages import RX_MESSAGES, decode_tx, TX_IDS  # noqa: E402
from .vehicle import SimState  # noqa: E402


class CanGateway:
    def __init__(self, bitrate: int = 500000, channel: int = 0):
        self.bitrate = bitrate
        self.channel = channel
        self.bus: Optional[can.BusABC] = None
        self._tx_thread: Optional[threading.Thread] = None
        self._rx_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._state = SimState()
        self.tx_count = 0
        self.rx_count = 0
        self.tx_errors = 0
        self.last_rx_time = 0.0
        self._frames = {}          # live CAN bus display: id -> {id,src,bytes,n}

    # ---- lifecycle ----
    def open(self) -> None:
        self.bus = can.Bus(interface="gs_usb", channel=self.channel,
                           index=0, bitrate=self.bitrate)

    def close(self) -> None:
        self._stop.set()
        for t in (self._tx_thread, self._rx_thread):
            if t:
                t.join(timeout=1.0)
        if self.bus:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None

    def start(self) -> None:
        if self.bus is None:
            self.open()
        self._stop.clear()
        self._tx_thread = threading.Thread(target=self._tx_loop, daemon=True)
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()
        self._tx_thread.start()

    # ---- state exchange with the sim loop ----
    def set_state(self, s: SimState) -> None:
        """Publish the latest plant state for the TX encoders to read."""
        with self._state_lock:
            # copy only the fields the encoders need (cheap, avoids sharing feedback)
            self._state.ignition = s.ignition
            self._state.selector = s.selector
            self._state.manual_gear = s.manual_gear
            self._state.throttle = s.throttle
            self._state.brake = s.brake
            self._state.drive_mode = s.drive_mode
            self._state.engine_rpm = s.engine_rpm
            self._state.speed_kmh = s.speed_kmh

    def apply_feedback(self, s: SimState) -> None:
        """Copy decoded TCU feedback into the caller's state object."""
        with self._state_lock:
            s.tcu_current_gear = self._state.tcu_current_gear
            s.tcu_target_gear = self._state.tcu_target_gear
            s.tcu_lockup = self._state.tcu_lockup
            s.tcu_selector_code = self._state.tcu_selector_code
            s.tcu_atf_temp_c = self._state.tcu_atf_temp_c
            s.tcu_output_shaft = self._state.tcu_output_shaft
            s.tcu_dtcs = list(self._state.tcu_dtcs)
            s.can_link_up = (time.perf_counter() - self.last_rx_time) < 0.5

    def clear_dtc_cache(self) -> None:
        with self._state_lock:
            self._state.tcu_dtcs = []

    # ---- worker loops ----
    def _tx_loop(self) -> None:
        # per-message next-send schedule
        period = {cid: 1.0 / rate for cid, (rate, _) in RX_MESSAGES.items()}
        nxt = {cid: time.perf_counter() for cid in RX_MESSAGES}
        while not self._stop.is_set():
            now = time.perf_counter()
            with self._state_lock:
                snap = SimState(
                    ignition=self._state.ignition, selector=self._state.selector,
                    manual_gear=self._state.manual_gear, throttle=self._state.throttle,
                    brake=self._state.brake, drive_mode=self._state.drive_mode,
                    engine_rpm=self._state.engine_rpm, speed_kmh=self._state.speed_kmh,
                )
            for cid, (rate, enc) in RX_MESSAGES.items():
                if now >= nxt[cid]:
                    nxt[cid] += period[cid]
                    if nxt[cid] < now:            # fell behind; resync
                        nxt[cid] = now + period[cid]
                    data = enc(snap)
                    try:
                        self.bus.send(can.Message(arbitration_id=cid, data=data,
                                                  is_extended_id=False), timeout=0.05)
                        self.tx_count += 1
                        self._capture(cid, data, "car")   # live bus display
                    except Exception:
                        self.tx_errors += 1
            time.sleep(0.002)

    def _capture(self, cid: int, data: bytes, src: str) -> None:
        with self._state_lock:
            key = "%03X" % cid
            f = self._frames.get(key)
            self._frames[key] = {"id": key, "src": src,
                                 "bytes": data.hex().upper(),
                                 "n": (f["n"] + 1 if f else 1)}

    def get_frames(self) -> dict:
        with self._state_lock:
            return {k: dict(v) for k, v in self._frames.items()}

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(timeout=0.2)
            except Exception:
                continue
            if msg is None:
                continue
            if msg.arbitration_id in TX_IDS:
                self.rx_count += 1
                self.last_rx_time = time.perf_counter()
                self._capture(msg.arbitration_id, bytes(msg.data), "TCU")
                with self._state_lock:
                    decode_tx(msg.arbitration_id, bytes(msg.data), self._state)
