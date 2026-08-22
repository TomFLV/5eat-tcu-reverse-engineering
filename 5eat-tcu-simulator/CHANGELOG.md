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
- CANtact Pro CAN I/O (python-can / gs_usb, native Windows).
- Web dashboard with live CAN monitor, self-test, and AI-ready logging.
- Standalone packaging: native app window or browser, portable zip, and a
  driver-bundling Windows installer.
