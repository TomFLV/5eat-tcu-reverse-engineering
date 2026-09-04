# Changelog

## v1.0.0

Initial public release.

- Physics-based 5EAT car simulator driving the TCU logic in real time (vehicle
  model, torque converter, gear ratios, traction limiting), calibrated to real 0–60.
- Per-firmware ROM selection with gear ratios extracted from the binary; power
  levels from stock to 1000+ hp; calm/normal/spirited driver models; scripted and
  duration test drives.
- Dual ATF temperature model coupled to engine coolant.
- Live TCU memory monitor over SSM (Tactrix OpenPort 2.0 serial or a mock TCU fed by
  the simulator): firmware-mapped RAM watch-list with decoders, live byte pokes, and
  JSONL logging. Covers the control-valve-body memory-box link (P1601).
- Full TCU ROM set supplied in `roms/` (25 firmwares, Hitachi/M32R + Denso/SH7058)
  and bundled with the packaged app, so the firmware selector is populated out of the box.
- CANtact Pro CAN I/O (python-can / gs_usb, native Windows).
- Web dashboard with live CAN monitor, self-test, and AI-ready logging.
- Standalone packaging: native app window or browser, portable zip, and a
  driver-bundling Windows installer.

## v1.0.1
- Live monitor: added firmware-portable SSM-index reads — ATF Sensor 1/2
  (index 0x56/0x5A, x-50 °C) and the 12 DTC-group current/confirmed bitfields
  (0x9C–0x167), matching the analysis repo's verified SSM mapping (FINDINGS §89/§91).
  These resolve on any supported image through the TCU's own translation table.
