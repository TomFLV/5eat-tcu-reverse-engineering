"""One-click launcher: start the backend and open the dashboard in the browser.
Non-technical use - no scripting, no CLI needed beyond running this once
(or the packaged .exe)."""
from __future__ import annotations
import threading
import time
import webbrowser

import uvicorn

HOST, PORT = "127.0.0.1", 8642


def _open():
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run("tcu_sim.server:app", host=HOST, port=PORT, log_level="warning")
