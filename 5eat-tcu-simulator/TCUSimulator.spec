# PyInstaller spec — one-folder build of the standalone TCU Simulator.
# Build:  pyinstaller TCUSimulator.spec --noconfirm
# Output: dist/TCUSimulator/TCUSimulator.exe  (portable folder)
#
# One-folder (not one-file): reliable with the native USB DLLs (libusb) and the
# web data file, faster start, no per-launch temp extraction.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [("tcu_sim/web/index.html", "tcu_sim/web")]
binaries = []
hiddenimports = [
    # python-can loads interface backends dynamically
    "can.interfaces.gs_usb", "can.interfaces.gs_usb.gs_usb",
    # uvicorn's dynamically-imported loop/protocol/lifespan modules
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
]

# collect native libs + data for the USB/serial stack (libusb DLL, gs_usb, pyusb, pyserial)
for pkg in ("libusb_package", "gs_usb", "usb", "serial", "can"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="TCUSimulator",
    console=False,          # windowed app; set True to get a console for debugging
    icon="packaging/app.ico" if __import__("os").path.exists("packaging/app.ico") else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TCUSimulator")
