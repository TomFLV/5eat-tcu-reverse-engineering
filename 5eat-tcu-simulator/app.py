"""Standalone launcher for the 5EAT TCU Simulator.

Runs the FastAPI/uvicorn server locally and opens a front door. Two shells, the
user picks (installer makes a shortcut for each):

    --shell window    a chromeless app window via the installed Edge/Chrome
                      (`--app=` mode) — real app feel, nothing extra to bundle.
                      Falls back to pywebview if present, then the browser.
    --shell browser   opens the default browser to the app.

Same server either way, so the REST/websocket API stays reachable for the AI
agent and the LAN. The window's "Quit" button hits /api/quit; this launcher
waits on that (or Ctrl+C) and shuts the server (and CANtact) down cleanly.
"""
from __future__ import annotations
import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

HOST_DEFAULT = "127.0.0.1"
PORT_PREFERRED = 8642


def _free_port(host: str, preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _wait_ready(host: str, port: int, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.15)
    return False


def _find_browser_exe() -> str | None:
    cands = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in cands:
        if os.path.isfile(p):
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def _open_window(url: str) -> bool:
    """Chromeless app window via Edge/Chrome --app, then pywebview, then browser."""
    exe = _find_browser_exe()
    if exe:
        profile = os.path.join(os.environ.get("TEMP", "."), "tcusim_appwin")
        try:
            subprocess.Popen([exe, "--app=" + url, "--new-window",
                              "--user-data-dir=" + profile, "--window-size=1400,940"])
            return True
        except Exception:
            pass
    try:  # optional true-embedded window if the user installed pywebview
        import webview  # type: ignore
        win = webview.create_window("5EAT TCU Simulator", url, width=1400, height=940)
        return win  # caller handles blocking start for pywebview
    except Exception:
        pass
    import webbrowser
    webbrowser.open(url)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="5EAT TCU Simulator")
    ap.add_argument("--shell", choices=["window", "browser", "webview"],
                    default=os.environ.get("TCUSIM_SHELL", "window"))
    ap.add_argument("--host", default=os.environ.get("TCUSIM_HOST", HOST_DEFAULT))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TCUSIM_PORT", "0")) or None)
    ap.add_argument("--no-open", action="store_true", help="start server only")
    args = ap.parse_args()

    import uvicorn
    from tcu_sim.server import app, QUIT_EVENT

    port = args.port or _free_port(args.host, PORT_PREFERRED)
    config = uvicorn.Config(app, host=args.host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None      # we're off the main thread
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    url = f"http://{args.host}:{port}/"
    if not _wait_ready(args.host, port):
        print("server did not come up in time", file=sys.stderr)
        server.should_exit = True
        return
    print("TCU Simulator running at", url)

    use_pywebview = False
    if not args.no_open:
        if args.shell == "browser":
            import webbrowser
            webbrowser.open(url)
        elif args.shell == "webview":
            try:
                import webview  # type: ignore
                webview.create_window("5EAT TCU Simulator", url, width=1400, height=940)
                use_pywebview = True
            except Exception:
                _open_window(url)
        else:  # window
            _open_window(url)

    try:
        if use_pywebview:
            import webview  # type: ignore
            webview.start()                # blocks until the window is closed
        else:
            QUIT_EVENT.wait()              # released by the UI Quit button
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        t.join(timeout=5.0)
        print("stopped.")


if __name__ == "__main__":
    main()
