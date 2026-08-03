# Subaru 5EAT TCU

RomRaider tuning definitions for the Subaru 5EAT transmission control unit, with the
tooling and analysis behind them.

Two controller families are covered: Hitachi M32R (16 firmwares) and Denso SH705x (9).
Shift schedules, line pressure and downshift pressure are in real units. Trouble codes
are individually switchable. Both checksum families are corrected on save.

### [Download the Windows app](../../releases/latest)

Extract the folder and run `RomRaider-TCU.exe`, then `File > Open` a ROM from
`app\roms`. A Java runtime, both definitions and twenty-five ROM images are bundled.

Already using RomRaider? Point it at [`definitions/`](definitions/) instead. Requires
1.0.0 or later; 0.8.2 cannot load 3D tables.

> **Checksums are handled on save.** M32R images carry two — an additive checksum at
> `0x8000`/`0x8004` and a balance at `0x8020` — and the TCU verifies both at start-up.
> Releases up to 1.4.2 maintained only the first, so a ROM saved with one of those
> will fail its own integrity check. Re-save with 1.4.3 or later, or run
> `python tools/checksum.py --fix edited.bin`.

---

## Tunable tables

| Category | Contents |
|---|---|
| Shift Schedule | Ten shift maps: road speed in km/h against accelerator angle, one row per shift event. Drag-and-drop curve editor on the toolbar |
| Shift Schedule Group Selector | Which of the five schedule groups applies |
| Line Pressure | Nine target maps, engine torque (Nm) to line pressure (kPa), plus the slip and ATF-temperature multipliers feeding them |
| Downshift Pressure | Per-downshift target pressure in kPa, with the ramp step and hold that set how harshly each applies |
| Diagnostic Codes | All 53 trouble codes, individually enabled or disabled |
| Sensor Calibration | ATF temperature sensor linearisation, ADC counts to °C; ATF blend window in °C |

![shift curves](docs/shift-curves-reference.png)

*Chart by [rimwall](https://github.com/rimwall). The shift units were verified against it.*

Cells showing `-` in a shift map are not editable: that curve has no vertex at that
pedal position, so there is no byte to change.

## Firmwares

### Hitachi M32R

Sixteen mapped, all checksum-verified. Decompiler output in [`decompiled/`](decompiled/).

| Cal ID | ROM ID | Size | Vehicle |
|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM |
| `MB436G` | `91FE216300` | 512K | USDM, early 2005 Outback XT |
| `MB436T` | `91D0207500` | 384K | JDM |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 |
| `MB5300` | `ABD1207000` | 384K | JDM Legacy GT 2006 |
| `MB558D01` | `ACD1207000` | 512K | JDM Legacy GT 2006 |
| `MB562EH` | `ADE0236000` | 512K | — |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 |
| `MB4365` | `91A0217300` | 384K | EDM |
| `MB4372` | `91A0217400` | 512K | EDM |
| `MB4364` | `91A1207300` | 384K | EDM |
| `MB436L` | `91FE207100` | 384K | USDM Legacy GT 2005 |
| `MB4402` | `AAD1A06000` | 512K | JDM |

Five of these came from [jimihimi/TCURoms](https://github.com/jimihimi/TCURoms).
The definition is selected automatically from the cal ID at `0x8008`.

### Denso SH705x

A separate controller with its own processor, table format and checksum. Later JDM
and EDM cars, and the 2014 Tribeca.

| Cal ID | Vehicle |
|---|---|
| `PDDE2WA0` | Forester SH9 STI 3.283, JDM 2010 |
| `WQDE2WB1` | Impreza STI 3.583, JDM 2011 |
| `25D1AWS1` | Legacy STI 3.171, JDM |
| `25D12WB1` | Legacy 3.583, JDM 2008 |
| `26DE2OB0` | Legacy 3.272, EJDM 2008 |
| `YSD12WB0` | Exiga TG5 3.083 |
| `02EB2WB0` | Tribeca 3.583, EDM 2009 |
| `08FB2WA0` | Tribeca, USDM 2014 |
| `EZAE2WB1` | Legacy GT, EDM 2010 |

Twelve shift schedules per image in real units. Remaining tables are listed as
unidentified at `userlevel=4`, restricted to the 140–186 per image the firmware
demonstrably indexes; header-format scanning alone returns about 1770 candidates,
most of them coincidence.

## Confirmed units

Each verified against an external reference and against the firmware's own arithmetic.

| Quantity | Conversion | Basis |
|---|---|---|
| Gear ratio | `raw / 1024` | Published ratios to within 0.0007 |
| Engine speed | `raw / 8` | Clean 640 RPM breakpoints; caps at 8191 RPM (uint16 limit) |
| Temperature | `raw − 40` °C | Standard automotive encoding |
| Vehicle speed | km/h direct | Factory shift chart |
| Accelerator angle | `raw × 100/255` | Shift chart and CAN `0x412` |
| Line pressure | kPa direct | Manual specifies 1370 kPa at full throttle; present in all sixteen images |
| Line pressure targets | torque `/10` Nm, pressure `/10` kPa | Two maps hit the manual's 490 kPa and 1372 kPa figures |
| Slip pressure factor | `/1024` both axes | Reproduces rimwall's stated 0.5 slip → 1.392, 0.9 → 1.000 |
| ATF temp factor | `/256` | From the arithmetic: unity is `0x100`, product is `>>16` |
| Trouble codes | P-number in hex | `0x705` = P0705, via the thread's CAN `0x422` decoding |

Fourteen further tables are shown scaled but unnamed: every value in every firmware is
an exact multiple of a power of two, which fixes the storage format even where the
quantity is unknown. Their unit labels say so.

## Known limitations

**Torque converter lockup is not identified.** Narrowed to two of the seven solenoid
channels, `0x804EB2` (TIO5) and `0x804EB6` (TIO7). Their drivers are exact mirrors,
so the code cannot separate them; a log of both duty addresses during engagement
would. See [FINDINGS.md](FINDINGS.md) §29.

**Which driving condition selects which schedule is unknown.** The selection mechanism
is understood — index `= condition × 2 + group × 10` — and the group selector now
ships. What each value of the condition byte means is not established. See
[FINDINGS.md](FINDINGS.md) §33.

**Denso tables cannot be named by static analysis.** The route from code to table is
computed at runtime; a fully disassembled image still shows no references to the
calibration arrays. See [FINDINGS.md](FINDINGS.md) §31.

**Disabling a DTC is inferred, not tested.** Blanking an entry should stop the code
being reported, which is what the firmware's 43 unused slots contain, but nobody has
confirmed it on a car. It suppresses the code, not the fault.

Tables whose quantity has not been established are labelled `raw`.

## Batch use

`tcu-cli.exe` ships alongside the editor. It runs headless, prints one JSON object,
and exits non-zero when the answer is no. It drives the same parser and save path as
the application.

```
tcu-cli info     definitions/5eat_tcu_romraider_defs.xml roms/ACD1A06000.bin
tcu-cli dump     <def> <rom> "Shift Map"
tcu-cli checksum <def> <rom> --fix fixed.bin
tcu-cli set      <def> <rom> "Shift Map" 12 65 out.bin
tcu-cli selftest <def> roms/*.bin
```

`selftest` loads each ROM, verifies its checksums, edits a cell, saves and verifies
again — sixteen firmwares in about five seconds.

## Repository

| Path | Contents |
|---|---|
| [`romraider-5eat/`](romraider-5eat/) | The Windows application: patches and build script. GPL-2.0, not MIT |
| [`definitions/`](definitions/) | RomRaider definitions for both families |
| [`tools/`](tools/) | Generators, validators, extractors ([README](tools/README.md)) |
| [`decompiled/`](decompiled/) | Ghidra output, sixteen M32R images |
| [`rom/`](rom/), [`rom-denso/`](rom-denso/) | ROM images |
| [`docs/`](docs/) | [ROM details](docs/ROM-DETAILS.md) · [technical notes](docs/TECHNICAL-NOTES.md) · [manual setup](docs/ROMRAIDER-SETUP.md) |
| [`FINDINGS.md`](FINDINGS.md) | Full research log, in order, including wrong turns |

## Contributing

Adding a firmware: [`tools/README.md`](tools/README.md#adding-a-firmware). TCU dumps
not already here are the most useful contribution.

If you contributed a ROM and want it removed or credited differently, open an issue.

---

## Credits

Most of the raw material here is other people's work.

The ROM images in [`rom/`](rom/) were dumped and shared by members of the RomRaider
thread [5EAT TCM JECS ROM Image](https://www.romraider.com/forum/viewtopic.php?f=40&t=13725)
over several years. Getting these off a car is slow and occasionally risks the TCU.
`91FE216300` is the one I dumped.

The shift-curve chart in [`docs/`](docs/shift-curves-reference.png) is rimwall's work,
posted to that thread:

> "The shift table pointers start at 0x180e8. The first lot of data is at 0x0001683c.
> The data is structured as words (uint16) in pairs of x, y. x is the Vehicle Speed in
> km/hr. y is the Accelerator Pedal Angle in % where 0xff = 100%. The data is
> terminated by 0xffff."

Both claims check out exactly against `ACD1A06000`, and the shift units were verified
against the chart.

### The thread

[rimwall](https://github.com/rimwall) is by a wide margin the largest contributor: the
chart above, the shift-table encoding, the security-access and protocol work that made
these TCUs readable, the Denso side, the FastECU OEM fork, and the corrected M32R
Ghidra language this project's disassembly depends on.

MiikaS ([miikasyvanen](https://github.com/miikasyvanen)) wrote FastECU, without which
none of these ROMs could be dumped.

ajayel, riksk, jimihimisimi, AJ08H65EAT, kiki86 and curt4576 did the testing: dumping
TCUs, running experimental builds, posting logs, and taking bricking risk on their own
vehicles to prove the read and write paths.

Sasha_A80 posted the original JDM ROM and identified the M32R. V6er, trcxsa,
Blake_Volpex, ciper, SergArb, roadie, Waselon, dschultz, b4andrey, Tugsay,
Alucard7002, alesv, lvkeith and fenugrec contributed analysis, dumps, corrections and
domain knowledge.

Comer352L wrote FreeSSM and the branch adding 5EAT TCU adjustment support.

If you are on this list and want your name removed, changed, or your contribution
described differently, open an issue.

### Prior and parallel work

- [FastECU](https://github.com/miikasyvanen/FastECU) and
  [rimwall's OEM fork](https://github.com/rimwall/fastecu-oem) — the tooling that makes
  reading and writing these TCUs possible. Its `checksum_tcu_subaru_hitachi_m32r_can`
  module, on the `development` branch, is where the second checksum came from; `master`
  carries no TCU code.
- [FreeSSM](https://github.com/Comer352L/FreeSSM) — diagnostics, and the
  `e5at-permanent-adjustments` branch.
- [ghidra-m32r](https://github.com/ripnet/ghidra-m32r) — the Ghidra processor module.
- [RomRaider](https://github.com/RomRaider/RomRaider) — the editor.

Gear ratios, line-pressure targets and ATF temperatures come from the Subaru factory
service manual (2004 Legacy), which is not redistributed here.

### Scope of this work

The tooling in [`tools/`](tools/), the definitions in [`definitions/`](definitions/)
and the written analysis in [`docs/`](docs/): table mapping, unit derivations, checksum
detection and multi-firmware porting. That is what the MIT licence covers.

---

## Legal

The ROM images are Subaru/Fuji Heavy Industries firmware, included for
interoperability and repair research. No rights claimed. The decompiler output in
[`decompiled/`](decompiled/) is derived from them and carries the same status.

My own contributions are MIT licensed — see [LICENSE](LICENSE).

[`romraider-5eat/`](romraider-5eat/) is GPL-2.0, not MIT. Those patches are diffs
against RomRaider, so the package built from them is a derivative of a GPL-2.0
program. Redistribution requires corresponding source: the patches plus the upstream
revision pinned in `build-standalone.sh`. See
[`romraider-5eat/LICENSE`](romraider-5eat/LICENSE).

**Flashing a modified transmission controller can damage the transmission.** This is
static analysis; almost none of it has been validated on a running vehicle. Use at
your own risk.
