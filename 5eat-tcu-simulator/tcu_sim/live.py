"""LiveMonitor — the bench window into a running TCU.

Polls the firmware-mapped RAM over SSM (one 0xA8 batch read per cycle), decodes
every watch entry via tcu_map, and exposes a snapshot for the dashboard. Supports
live pokes (0xB8 single write) and AI-ready JSONL logging. The poll thread owns
the transport exclusively; pokes are queued and executed there so serial access
is never concurrent.
"""
from __future__ import annotations
import json
import os
import queue
import threading
import time
from typing import Dict, List, Optional

from . import ssm
from . import tcu_map
from .ssm_transport import Transport, make_transport
from .paths import LOG_DIR  # frozen-safe: next to the .exe when packaged


class LiveMonitor:
    def __init__(self, sim=None):
        self.sim = sim
        self._t: Optional[Transport] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pokes: "queue.Queue[tuple]" = queue.Queue()
        self.connected = False
        self.kind = ""
        self.error = ""
        self.init: Dict = {}
        self.hz = 0.0
        self.poll_count = 0
        self.err_count = 0
        self._decoded: List[Dict] = []
        self._addrs = tcu_map.all_byte_addrs()
        # logging
        self._log_f = None
        self.log_name = ""

    # ---- lifecycle -------------------------------------------------------- #
    def connect(self, spec: dict) -> dict:
        self.disconnect()
        self.error = ""
        self.init = {}
        try:
            t = make_transport(spec, self.sim)
            t.open()
            # handshake / liveness: read ECU id (skip if it fails on a bare cable)
            try:
                payload = t.query(ssm.build_init(), ssm.CMD_INIT, timeout=1.0)
                self.init = ssm.parse_init(payload)
            except Exception:
                self.init = {"note": "no init response (continuing)"}
            self._t = t
            self.kind = t.describe()
            self.connected = True
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            self.connected = False
            return {"ok": False, "error": self.error}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return {"ok": True, "kind": self.kind, "init": self.init}

    def disconnect(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._t:
            try:
                self._t.close()
            except Exception:
                pass
            self._t = None
        self.connected = False
        self.stop_log()

    # ---- pokes ------------------------------------------------------------ #
    def poke(self, addr: int, value: int) -> None:
        """Queue a single-byte write; applied on the next poll cycle."""
        self._pokes.put((int(addr) & 0xFFFFFF, int(value) & 0xFF))

    def _drain_pokes(self) -> List[dict]:
        done = []
        while True:
            try:
                addr, val = self._pokes.get_nowait()
            except queue.Empty:
                break
            try:
                self._t.query(ssm.build_write_addr(addr, val), ssm.CMD_WRITE_ADDR)
                done.append({"addr": addr, "value": val, "ok": True})
            except Exception as e:
                done.append({"addr": addr, "value": val, "ok": False, "err": str(e)})
        return done

    # ---- logging ---------------------------------------------------------- #
    def start_log(self) -> str:
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        name = "live_%s_%s.jsonl" % (self.kind.split()[0].replace("-", ""), stamp)
        self._log_f = open(os.path.join(LOG_DIR, name), "w", encoding="utf-8")
        self._log_f.write(json.dumps({
            "type": "header", "kind": self.kind, "init": self.init,
            "generated": stamp, "watch": [e["name"] for e in tcu_map.WATCH]}) + "\n")
        self._log_f.flush()
        self.log_name = name
        return name

    def stop_log(self) -> None:
        if self._log_f:
            try:
                self._log_f.close()
            finally:
                self._log_f = None
        self.log_name = ""

    # ---- poll loop -------------------------------------------------------- #
    def _loop(self) -> None:
        req = ssm.build_read_addresses(self._addrs)
        t_prev = time.perf_counter()
        while not self._stop.is_set():
            poked = self._drain_pokes()
            try:
                payload = self._t.query(req, ssm.CMD_READ_ADDRS)
                if len(payload) < len(self._addrs):
                    raise ssm.SsmError("short read %d/%d" % (len(payload), len(self._addrs)))
                mem = {a: payload[i] for i, a in enumerate(self._addrs)}
                decoded = [tcu_map.decode(e, mem) for e in tcu_map.WATCH]
                now = time.perf_counter()
                dt = now - t_prev
                t_prev = now
                with self._lock:
                    self._decoded = decoded
                    self.hz = (1.0 / dt) if dt > 0 else 0.0
                    self.poll_count += 1
                    self.error = ""
                    if poked:
                        self._last_poke = poked
                if self._log_f:
                    row = {"t": round(now, 3), "hz": round(self.hz, 2),
                           "v": {d["name"]: d.get("raw") for d in decoded}}
                    if poked:
                        row["pokes"] = poked
                    self._log_f.write(json.dumps(row) + "\n")
            except Exception as e:
                with self._lock:
                    self.err_count += 1
                    self.error = str(e)
                time.sleep(0.2)      # back off on error
            # mock is instant; pace it so it doesn't spin. Real serial self-paces.
            if self._t and self._t.kind == "mock":
                time.sleep(0.1)

    # ---- snapshot for the dashboard --------------------------------------- #
    def snapshot(self) -> dict:
        with self._lock:
            decoded = list(self._decoded)
            base = {"connected": self.connected, "kind": self.kind,
                    "error": self.error, "init": self.init,
                    "hz": round(self.hz, 2), "polls": self.poll_count,
                    "errs": self.err_count, "logging": bool(self._log_f),
                    "log_name": self.log_name}
        groups = []
        for gname in tcu_map.GROUP_ORDER:
            rows = [d for d in decoded if d["group"] == gname]
            if rows:
                groups.append({"name": gname, "rows": rows})
        base["groups"] = groups
        return base
