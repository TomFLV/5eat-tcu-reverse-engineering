# Subaru 5EAT TCU — Reverse Engineering Notes & RomRaider Definition

Reverse engineering of a Subaru 5EAT (5-speed automatic) transmission control unit
ROM, and a working RomRaider definition file that lets you open and edit the
calibration tables in it.

**Eleven firmwares included**, all Mitsubishi/Renesas M32R, all with verified
checksums. Full decompiler output is provided for every one of them.

| Cal ID | ROM ID | Size | Vehicle / notes | Tables mapped |
|---|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM | **yes** |
| `MB436G` | `91FE216300` | 512K | USDM, Early 2005 Outback XT | **yes** |
| `MB436T` | `91D0207500` | 384K | JDM | not yet |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 | not yet |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 | not yet |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 | not yet |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 | not yet |
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT | not yet |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 | not yet |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM | not yet |
| `MB562EH1` | `ADE0236000` | 512K | — | not yet |

The definition file carries every mapped firmware. **RomRaider selects the right
one automatically** by matching the cal ID at `0x8008` when you open a ROM —
there is nothing to choose.

This is an ongoing project. Table addresses, the DTC list, the checksum algorithm,
and three real-world unit conversions are confirmed. Plenty is still unidentified,
and that's marked honestly throughout rather than guessed at.

---

## What's here

| Path | What it is |
|---|---|
| [`definitions/`](definitions/) | The RomRaider definition file — both firmwares, auto-selected by cal ID. Start here. |
| [`docs/ROMRAIDER-SETUP.md`](docs/ROMRAIDER-SETUP.md) | How to actually get this working in your RomRaider install. |
| [`docs/ROM-DETAILS.md`](docs/ROM-DETAILS.md) | Everything known about this specific binary — provenance, IDs, memory map. |
| [`docs/TECHNICAL-NOTES.md`](docs/TECHNICAL-NOTES.md) | How the tables, checksum, and unit scales were worked out. |
| [`tools/`](tools/) | Python tools (checksum fix, definition generator, validators) and Ghidra scripts. |
| [`decompiled/`](decompiled/) | Full decompiler output for both ROMs, ~46,500 lines each. |
| [`rom/`](rom/) | The ROM images themselves. |

---

## Quick start

1. Install [RomRaider](https://www.romraider.com/) (tested against 1.0.0).
2. Point it at `definitions/5eat_tcu_romraider_defs.xml`.
3. Open either ROM from `rom/`.
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
- **Vehicle speed** — km/h directly, no scaling.
- **Accelerator angle** — raw 0–255 mapping to 0–100%.

Also confirmed: the **checksum algorithm** (32-bit big-endian two's-complement
additive, stored twice at `0x8000`/`0x8004` — over two different region
conventions, which the tool detects rather than assumes), the **DTC table** at
`0x4090` (19 real P07xx transmission codes), and the **shift schedule**, which is
fully decoded.

### The shift schedule

The eight shift-point curves are editable, in real units. Each is a polyline in
**vehicle speed (km/h)** against **accelerator opening angle (%)** — the same form
as the factory shift chart, which is what the encoding was verified against:

![shift curves](docs/shift-curves-reference.png)

Slot A is the upshift from a given gear and slot B the downshift, which is why 1st
gear has no downshift curve and 5th has no upshift — both are placeholders in the
ROM, exactly where that reading predicts.

## What's not

IDK

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
