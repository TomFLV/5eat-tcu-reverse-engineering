# Subaru 5EAT TCU — Reverse Engineering Notes & RomRaider Definition

Reverse engineering of a Subaru 5EAT (5-speed automatic) transmission control unit
ROM, and a working RomRaider definition file that lets you open and edit the
calibration tables in it.

**Firmware: `91D1206000` (`MB431M` / `R9H`) — JDM, Mitsubishi/Renesas M32R, 384 KB.**

This is an ongoing project. Table addresses, the DTC list, the checksum algorithm,
and three real-world unit conversions are confirmed. Plenty is still unidentified,
and that's marked honestly throughout rather than guessed at.

---

## What's here

| Path | What it is |
|---|---|
| [`definitions/`](definitions/) | The RomRaider definition file — 73 tables. Start here. |
| [`docs/ROMRAIDER-SETUP.md`](docs/ROMRAIDER-SETUP.md) | How to actually get this working in your RomRaider install. |
| [`docs/ROM-DETAILS.md`](docs/ROM-DETAILS.md) | Everything known about this specific binary — provenance, IDs, memory map. |
| [`docs/TECHNICAL-NOTES.md`](docs/TECHNICAL-NOTES.md) | How the tables, checksum, and unit scales were worked out. |
| [`tools/`](tools/) | Python tools (checksum fix, definition generator, validators) and Ghidra scripts. |
| [`decompiled/`](decompiled/) | Full decompiler output for the ROM, ~46,500 lines. |
| [`rom/`](rom/) | The ROM image itself. |

---

## Quick start

1. Install [RomRaider](https://www.romraider.com/) (tested against 1.0.0).
2. Point it at `definitions/5eat_tcu_91D1206000_romraider_def.xml`.
3. Open `rom/91D1206000_5EAT.bin`.
4. **After any edit, fix the checksum before flashing** — RomRaider cannot do it for
   this ROM:
   ```bash
   python tools/checksum.py --fix edited.bin
   ```

Full instructions, including the settings RomRaider needs and how to enable debug
logging if tables don't appear, are in [`docs/ROMRAIDER-SETUP.md`](docs/ROMRAIDER-SETUP.md).

---

## What's confirmed

Three real-world unit conversions are nailed down, each verified two independent
ways (against the factory service manual *and* against the firmware's own arithmetic):

- **Gear ratios** — `raw / 1024`. Decodes to 3.540 / 2.264 / 1.471 / 1.000 / 0.834,
  matching the published ratios to within 0.0007.
- **Engine speed** — `raw / 8`. Gives clean 640 RPM breakpoints topping out at 6400 RPM.
- **Temperature** — `raw − 40` °C. Two NTC thermistor channels, standard −40…+215 °C
  automotive encoding.

Also confirmed: the **checksum algorithm** (32-bit big-endian two's-complement
additive, stored twice at `0x8000`/`0x8004`), the **DTC table** at `0x4090` (19 real
P07xx transmission codes), and the **shift-schedule architecture** (a 50-entry
pointer array indexed by gear × range-mode).

## What's not

- Pressure units. There is **no pressure sensor** on this transmission — line
  pressure is commanded open-loop via a duty solenoid, which the service manual's
  own test procedure confirms (you plumb in a mechanical gauge). The target is the
  TCU's computed kPa value, not a sensor input.
- Roughly 28 further calibration curves are located but not yet exposed, because
  they use an 8-byte interleaved record format that RomRaider's table schema can't
  address without a stride attribute.
- Anything shown as `raw` in the definition file has no confirmed conversion. It's
  still editable — just unlabelled.

---

## Credits

The ROM image originates from the RomRaider forum thread
[**5EAT TCM JECS ROM Image**](https://www.romraider.com/forum/viewtopic.php?f=40&t=13725),
a long-running community effort on this TCU family. Several findings here were
cross-checked against that thread — in particular the CAN message IDs
(`0x412` carrying engine torque, `0x514` carrying shift events) and the
identification of the MCU as a 384 KB 144-pin M32R.

The checksum algorithm was independently verified against
[FastECU](https://github.com/miikasyvanen/FastECU), which implements the same
algorithm for this chip family.

Reference specifications (gear ratios, line pressure targets, ATF operating
temperatures) come from the Subaru factory service manual for the 2004 Legacy.
That document is Subaru's and is not redistributed here.

---

## Legal

The ROM image is Subaru/Fuji Heavy Industries firmware, included for
interoperability and repair research. It is not my work and I claim no rights to
it. The decompiler output in `decompiled/` is derived from it and carries the same
status.

My own contributions — the tools, the RomRaider definition, and the documentation —
are MIT licensed. See [LICENSE](LICENSE).

**Flashing a modified transmission controller can damage the transmission.** The
tables here are the result of static analysis; almost none of it has been validated
on a running vehicle. Anything marked experimental or expert-only genuinely is.
Use at your own risk.

— TomFLV
