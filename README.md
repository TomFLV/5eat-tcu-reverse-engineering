# Subaru 5EAT TCU — Reverse Engineering Notes & RomRaider Definition

The Subaru 5EAT holds its shift points, line pressures and clutch timing in a
transmission control unit nobody had published a tuning definition for. This is
the work of opening one up: notes on how the calibration is laid out, and a
RomRaider definition that lets you edit it.

### ▶ [Download the ready-to-run Windows package](../../releases/latest)

Extract the folder, double-click `RomRaider.vbs`, open a ROM. A Java runtime and
the definition are bundled, so there is nothing to install and nothing to
configure — it picks the right firmware itself.

If you already run RomRaider, just point it at
[`definitions/5eat_tcu_romraider_defs.xml`](definitions/) instead.

**Everything is in real units.** Shift points in km/h against pedal percentage,
line pressure in kPa, engine speed in RPM. Where a unit has not actually been
established, the table says `raw` and means it — a plausible-looking unit that
turns out to be wrong is worse than no unit at all.

Eleven firmwares are mapped, all Mitsubishi/Renesas M32R, all with verified
checksums, with full decompiler output for sixteen images.

| Cal ID | ROM ID | Size | Vehicle / notes | Tables mapped |
|---|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM | **yes** |
| `MB436G` | `91FE216300` | 512K | USDM, Early 2005 Outback XT | **yes** |
| `MB436T` | `91D0207500` | 384K | JDM | **yes** |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 | **yes** |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 | **yes** |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 | **yes** |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 | **yes** |
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT | **yes** |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 | **yes** |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM | **yes** |
| `MB562EH` | `ADE0236000` | 512K | — | **yes** |

One definition file carries all of them. RomRaider matches the cal ID at `0x8008`
when you open a ROM and loads the right one, so there is nothing to pick.

---

## What's here

| Path | What it is |
|---|---|
| [`romraider-5eat/`](romraider-5eat/) | **A ready-to-run Windows build of RomRaider** with the definition and a Java runtime bundled. Download it from [Releases](../../releases). |
| [`definitions/`](definitions/) | The RomRaider definition file — all eleven firmwares, auto-selected by cal ID. |
| [`docs/ROMRAIDER-SETUP.md`](docs/ROMRAIDER-SETUP.md) | How to get this working in an existing RomRaider install instead. |
| [`docs/ROM-DETAILS.md`](docs/ROM-DETAILS.md) | The reference firmware in detail — provenance, IDs, memory map, checksum — plus the collection table. |
| [`docs/TECHNICAL-NOTES.md`](docs/TECHNICAL-NOTES.md) | How the tables, checksum, and unit scales were worked out. |
| [`FINDINGS.md`](FINDINGS.md) | The full research log, in order, including the wrong turns and why they looked right. Long. |
| [`tools/`](tools/) | Checksum fix, definition generator, validators, Ghidra scripts, and a [headless RomRaider verifier](tools/romraider-cli/). See [`tools/README.md`](tools/README.md). |
| [`decompiled/`](decompiled/) | Full decompiler output for all sixteen ROMs. |
| [`rom/`](rom/) | The ROM images themselves. |

---

## Quick start

**Easiest:** download the standalone Windows package from
[Releases](../../releases), extract the whole folder, run `RomRaider.vbs`, then
`File -> Open` a ROM. Nothing to install — a Java runtime and the definition are
bundled, and the right firmware is selected automatically from the calibration ID.

**Using your own RomRaider install** — 1.0.0 or later; 0.8.2 cannot load the 3D
tables. Point it at `definitions/5eat_tcu_romraider_defs.xml`. See
[`docs/ROMRAIDER-SETUP.md`](docs/ROMRAIDER-SETUP.md).

Either way: **after any edit, fix the checksum before flashing** — RomRaider
cannot do it for this ROM.

```bash
python tools/checksum.py --fix edited.bin
```

---

## What's confirmed

Six real-world unit conversions are nailed down, each verified two independent
ways — against an external reference (the factory service manual, rimwall's shift
chart, or the community CAN decoding) *and* against the firmware's own arithmetic:

- **Gear ratios** — `raw / 1024`. Decodes to 3.540 / 2.264 / 1.471 / 1.000 / 0.834,
  matching the published ratios to within 0.0007.
- **Engine speed** — `raw / 8`. Gives clean 640 RPM breakpoints. **The `uint16`
  storage caps these tables at 8191 RPM**; the stock calibration already parks a
  breakpoint at 8160 RPM, so there is headroom for a built engine, but a target
  above 8191 RPM cannot be represented.
- **Temperature** — `raw − 40` °C. Two NTC thermistor channels, standard −40…+215 °C
  automotive encoding.
- **Vehicle speed** — km/h directly, no scaling.
- **Accelerator angle** — raw 0–255 mapping to 0–100%. Independently confirmed
  twice: from the shift chart, and from CAN `0x412` byte 0 being APA at ×100/255.
- **Line pressure** — **kPa directly, no scaling.** The service manual's line
  pressure test (5AT-35) specifies 1370 kPa at full throttle in D and R, and has
  the TCU reporting "P/L Solenoid Target Pressure" to the Subaru Select Monitor
  *already in kPa*. That value appears verbatim in a calibration table in all
  eleven firmwares, at an address that relocates between them.

The pressure result is worth spelling out, because an earlier version of this
project gave up on pressure units after four separate attempts. The mistake was
looking for a conversion inside the ROM. There is none to find — the firmware
already works in kPa, and the answer was in the service manual the whole time.
The tables are `[engine speed × 8, kPa]`, so both columns carry a confirmed unit.
What is still *not* known is which hydraulic circuit each of the two curves
governs, so they are named for what they contain rather than for a guess.

Also confirmed: the **checksum algorithm** (32-bit big-endian two's-complement
additive, stored twice at `0x8000`/`0x8004` — over two different region
conventions, which the tool detects rather than assumes) and the **shift
schedule**, which is fully decoded.

> **Correction:** earlier versions claimed a DTC table at `0x4090`. That address is
> instruction stream, not data — port initialisation misread as records. The DTC
> tables have been removed. See [ROM-DETAILS.md](docs/ROM-DETAILS.md).

### Record-format curves

A further 35 curves use an 8-byte record layout rather than a contiguous array —
including the **temperature sensor linearisation tables**, the calibration that
defines what the ATF sensors actually read. These were long excluded on the
grounds that RomRaider has no stride support; the shift-schedule work showed that
was wrong, since the record block is contiguous and maps onto a 3D table exactly.

Each record array now ships as **a pair of single-quantity tables** rather than one
four-column grid — `Shift 1-2 Upshift Curve - km/h` alongside
`Shift 1-2 Upshift Curve - % pedal`, lining up row for row. The reason is that
RomRaider scales a table as a whole, so a grid holding both a speed and a pedal
angle cannot carry a unit at all and every cell had to be shown as a raw integer.

Splitting them uses RomRaider's own `skipCells` stride: with `sizex="1"` the
populate loop advances by `1 + skipCells` for every cell, so `skipCells="1"` walks
every second `uint16` — exactly one quantity out of the interleaved array, with
nothing skipped and nothing invented. All 640 3D tables across the eleven
firmwares were then checked cell by cell against the raw ROM bytes: **12,844 cells,
zero mismatches.**

Curves whose input is traced carry its real unit (engine speed in RPM, reference
speed in km/h). The rest ship as `raw` and say so. A plausible unit that turns out
to be wrong is worse than an honest `raw`, because it reads as confirmed.

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

More usefully: line pressure in **kPa is not stored in these ROMs** — tested four
ways across all eleven firmwares. The TCU almost certainly reports a raw duty
value and the Select Monitor converts. Settling it needs hardware, not analysis.
Details in [TECHNICAL-NOTES.md](docs/TECHNICAL-NOTES.md).

Five firmwares are missing the record-format curves. **No DTC table has been
located** — the address previously claimed for one turned out to be instruction
stream. DTCs are transmitted on CAN `0x422` bytes 3–4 as a 2-bit index plus a
14-bit code; finding the stored table means locating the code that builds that
message.

The definition needs **RomRaider 1.0.0 or later** — 0.8.2 cannot load 3D tables.

---

## Contributing

Adding a firmware is documented in [`tools/README.md`](tools/README.md#adding-a-firmware).
Dumps of TCUs not already here are the most useful thing anyone can contribute —
five of the eleven still need their record-format curves mapped, and that needs a
Ghidra pass per image rather than any shortcut.

If you contributed a ROM to the forum thread and want it removed or credited
differently, open an issue.

## Credits

**Almost none of the raw material here is mine.** This project is analysis layered
on top of other people's work, and the pieces below belong to them.

### The ROM images

Every firmware in [`rom/`](rom/) was dumped and shared by members of the RomRaider
forum thread [**5EAT TCM JECS ROM Image**](https://www.romraider.com/forum/viewtopic.php?f=40&t=13725)
— a years-long community effort. Getting these off a car is slow, fiddly, and
occasionally risks the TCU. They are included here so the work can continue, not
because I have any claim to them. If you contributed a dump and want it removed or
credited differently, open an issue and I'll act on it.

The `91FE216300` image (Early 2005 USDM Outback XT) is the one I dumped myself.

### The shift-curve chart

[`docs/shift-curves-reference.png`](docs/shift-curves-reference.png) was produced
and posted to the thread by another member, on page 9, alongside this description:

> *"The shift table pointers start at 0x180e8. The first lot of data is at
> 0x0001683c. The data is structured as words (uint16) in pairs of x, y. x is the
> Vehicle Speed in km/hr. y is the Accelerator Pedal Angle in % where 0xff = 100%.
> The data is terminated by 0xffff."*

**It is not my work**, and it is the single most valuable external input to this
project: the shift-schedule units were verified against it. That post also states
the encoding outright, which independently confirms what was derived here from the
chart geometry — same units, same 0xff = 100% mapping, same terminator.

Both claims in that post were checked against the `ACD1A06000` image and hold
exactly: the pointer array is at `0x180E8`, its first entry points to `0x01683C`,
and the data there parses as (speed, pedal) pairs ending in `0xFFFF`.

**The chart is rimwall's work.**

### The people in that thread

The thread runs to 380 posts over several years. These are the contributors named
in it — the work here rests on theirs:

**[rimwall](https://github.com/rimwall)** — by a wide margin the largest
contributor: the shift-curve chart above, the shift-table encoding, the
security-access and protocol work that made these TCUs readable at all, the Denso
side, and the FastECU OEM fork.

**MiikaS** ([miikasyvanen](https://github.com/miikasyvanen)) — FastECU itself,
without which none of these ROMs could be dumped.

**ajayel**, **riksk**, **jimihimisimi**, **AJ08H65EAT**, **kiki86**,
**curt4576** — the testing effort: dumping TCUs, running experimental builds,
posting logs, and bricking-risk on their own vehicles to prove the read/write
paths.

**Sasha_A80** — the original JDM ROM that opens the thread and the M32R chip
identification. **V6er**, **trcxsa**, **Blake_Volpex**, **ciper**, **SergArb**,
**roadie**, **Waselon**, **dschultz**, **b4andrey**, **Tugsay**,
**Alucard7002**, **alesv**, **lvkeith**, **fenugrec** — analysis, ROM dumps,
corrections and domain knowledge throughout.

**Comer352L** — FreeSSM, and the branch adding 5EAT TCU adjustment support.

If you are on this list and want your name removed, changed, or your contribution
described differently, open an issue.

### Prior and parallel work

- **[FastECU](https://github.com/miikasyvanen/FastECU)** (Miika Syvänen) and
  **[rimwall's OEM fork](https://github.com/rimwall/fastecu-oem)** — the tooling
  that makes reading and writing these TCUs possible at all. Its
  `checksum_tcu_subaru_hitachi_m32r_can` module independently corroborated the
  checksum algorithm.
- **rimwall** — much of the protocol and security-access work in the thread, and
  the Denso-side reverse engineering.
- **[FreeSSM](https://github.com/Comer352L/FreeSSM)** (Comer352L) — diagnostic
  tooling, and the branch adding TCU adjustment support.
- **[ghidra-m32r](https://github.com/ripnet/ghidra-m32r)** (ripnet) — the Ghidra
  processor module without which none of the disassembly here would exist.
- Forum members whose findings are used directly: the CAN ID meanings
  (`0x412` engine torque, `0x514` shift events), the MCU identification, and the
  observation that gear changes are governed by pedal-angle/speed curves — which
  is what pointed at the shift tables in the first place.

### Reference documentation

Gear ratios, line-pressure targets and ATF operating temperatures come from the
Subaru factory service manual (2004 Legacy). That document is Subaru's and is
**not** redistributed here.

### What is actually mine

The tooling in [`tools/`](tools/), the RomRaider definitions in
[`definitions/`](definitions/), and the written analysis in [`docs/`](docs/) —
the table mapping, the unit derivations, the checksum region detection, and the
multi-firmware porting. That, and nothing else in this repository, is what the
MIT licence covers.

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
