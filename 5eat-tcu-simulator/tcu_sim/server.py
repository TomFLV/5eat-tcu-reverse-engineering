"""Web backend: serves the dashboard and bridges it to the Simulator over a
websocket (state out ~30 Hz, driver inputs in). The browser is the whole UI -
no scripting for the user."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .simulator import Simulator, run_headless, LOG_DIR
from .runs import run_list
from .vehicle import POWER_LEVELS
from . import romdata
from . import tcu_map
from .live import LiveMonitor
from .paths import web_dir
import threading

app = FastAPI(title="5EAT TCU Car Simulator")
sim = Simulator()
live = LiveMonitor(sim)
_web = web_dir()

# set by /api/quit; the standalone launcher (app.py) waits on this to exit cleanly
QUIT_EVENT = threading.Event()


@app.on_event("startup")
def _startup():
    try:
        sim.start()
    except Exception as e:  # surface CAN-open failures in the UI instead of dying
        app.state.start_error = str(e)
    else:
        app.state.start_error = None


@app.on_event("shutdown")
def _shutdown():
    live.disconnect()
    sim.stop()


@app.get("/api/live/map")
def api_live_map():
    """The watch-list metadata: what each row is and where it lives in RAM."""
    return {"watch": [{"name": e["name"], "group": e["group"],
                       "addr": "0x%06X" % e["addr"], "size": e["size"],
                       "fmt": e["fmt"], "src": e.get("src", "")}
                      for e in tcu_map.WATCH],
            "groups": tcu_map.GROUP_ORDER}


@app.get("/api/live/ports")
def api_live_ports():
    """Enumerate serial ports so the user can pick the OpenPort 2.0 COM port."""
    try:
        from serial.tools import list_ports
        return {"ports": [{"device": p.device, "desc": p.description}
                          for p in list_ports.comports()]}
    except Exception as e:
        return {"ports": [], "error": str(e)}


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((_web / "index.html").read_text(encoding="utf-8"))


@app.get("/api/runs")
def api_runs():
    return {"runs": run_list(), "powers": list(POWER_LEVELS.keys())}


@app.get("/api/roms")
def api_roms():
    return {"roms": romdata.list_roms()}


@app.post("/api/headless")
def api_headless(body: dict):
    """Run a scenario faster-than-real-time and return the result + log file.
    The full telemetry (with CAN capture) is written to the log, not returned
    inline, to keep the response small. This is the AI-facing entry point."""
    r = run_headless(
        run_id=body.get("run_id", "errand"),
        power=body.get("power"),
        style=body.get("style"),
        rom=body.get("rom"),
        sample_hz=float(body.get("sample_hz", 10)),
    )
    return JSONResponse({
        "run": r["run"], "power": r["power"], "rom": r["rom"],
        "rom_name": r["rom_name"], "rom_ratios_valid": r["rom_ratios_valid"],
        "gear_ratios": r["gear_ratios"], "summary": r["summary"],
        "events": r["events"], "samples": len(r["telemetry"]),
        "log_file": r["log_file"],
    })


@app.post("/api/quit")
def api_quit():
    """Ask the standalone app to shut down (window Quit button). No-op when the
    server is run headless/dev without the launcher — it just sets the flag."""
    QUIT_EVENT.set()
    return {"quitting": True}


@app.post("/api/selftest")
def api_selftest():
    from .selftest import run_tests
    res = run_tests()
    return {"results": res, "passed": sum(1 for r in res if r["pass"]), "total": len(res)}


@app.get("/api/logs")
def api_logs():
    if not os.path.isdir(LOG_DIR):
        return {"logs": []}
    files = sorted((f for f in os.listdir(LOG_DIR) if f.endswith(".jsonl")), reverse=True)
    return {"logs": [{"name": f, "size": os.path.getsize(os.path.join(LOG_DIR, f))} for f in files]}


@app.get("/api/log/{name}")
def api_log(name: str):
    safe = os.path.basename(name)
    path = os.path.join(LOG_DIR, safe)
    if not os.path.isfile(path):
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse(open(path, encoding="utf-8").read(),
                             headers={"Content-Disposition": 'attachment; filename="%s"' % safe})


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()

    async def pump_out():
        while True:
            snap = sim.snapshot()
            snap["start_error"] = getattr(app.state, "start_error", None)
            snap["live"] = live.snapshot()
            await sock.send_text(json.dumps(snap))
            await asyncio.sleep(1 / 30)

    out = asyncio.create_task(pump_out())
    try:
        while True:
            msg = json.loads(await sock.receive_text())
            cmd = msg.get("cmd")
            if cmd == "input":
                sim.set_input(**{k: v for k, v in msg.items() if k != "cmd"})
            elif cmd == "clear_dtc":
                sim.clear_dtcs()
            elif cmd == "start_run":
                sim.start_run(msg.get("run_id"), msg.get("power"))
            elif cmd == "stop_run":
                sim.stop_run()
            elif cmd == "set_rom":
                sim.set_rom(msg.get("rom_id"))
            elif cmd == "live_connect":
                r = live.connect(msg.get("spec") or {"kind": "mock"})
                await sock.send_text(json.dumps({"live_result": r}))
            elif cmd == "live_disconnect":
                live.disconnect()
            elif cmd == "live_poke":
                live.poke(msg.get("addr"), msg.get("value"))
            elif cmd == "live_log":
                if msg.get("on"):
                    live.start_log()
                else:
                    live.stop_log()
    except WebSocketDisconnect:
        pass
    finally:
        out.cancel()
