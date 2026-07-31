# Subaru 5EAT TCU — RomRaider definitions and tooling

RomRaider tuning definitions for the Subaru 5EAT transmission control unit, plus the
tooling and notes behind them.

Two controller families are covered: **Hitachi M32R** (16 firmwares) and **Denso
SH705x** (9). Shift schedules, line pressure and downshift pressure are in real
units; trouble codes are individually switchable; both families' checksums are
corrected on save.

ROM images, the protocol work that gets them off a car, and a good deal of what is
documented here came from other people — see [credits](#credits). Tables whose
quantity has not been established are labelled `raw` or `unidentified` rather than
guessed at.

### ▶ [Download the Windows app](../../releases/latest)

Extract the folder, run `RomRaider-TCU.exe`, `File -> Open` a ROM from `app\roms`.
A Java runtime, both definitions and twenty-five ROM images are bundled — nothing
to install, nothing to configure.

Already run RomRaider? Point it at the definitions in [`definitions/`](definitions/)
instead. Needs 1.0.0+; 0.8.2 can't load 3D tables.

> **Both checksums are handled for you.** These ROMs carry two — an additive one at
> `0x8000`/`0x8004` and a balance at `0x8020` — and the TCU checks both on start-up.
> The bundled build corrects both on save. If you use stock RomRaider instead, it has
> no manager for this ECU and you must fix them yourself before flashing:
> ```bash
> python tools/checksum.py --fix edited.bin
> ```
> Versions up to 1.4.2 maintained only the first. If you edited a ROM with one of
> those, re-save it with 1.4.3 or run the command above before flashing.

---

## What you can actually tune

| Category | What it is |
|---|---|
| Shift Schedule | Ten complete shift maps — speed in km/h against % pedal, one row per shift event. There is a drag-and-drop curve editor on the toolbar if you would rather draw them. |
| Line Pressure | Nine target maps, engine torque (Nm) → line pressure (kPa), plus the slip and ATF-temperature multipliers that feed them |
| Downshift Pressure | Per-downshift target pressure in kPa, and the ramp step and hold that set how harshly each one applies |
| Diagnostic Codes | All 53 trouble codes, individually, each Enabled/Disabled |
| Sensor Calibration | ATF temperature sensor linearisation, ADC counts → °C |

Ten shift maps, because the transmission carries ten complete schedules and switches
between them by operating condition. The definition shipped one for a long time
before that was understood. Each also has four gear-limited variants for manual
mode, which reuse the same curves.

![shift curves](docs/shift-curves-reference.png)

*Chart by [rimwall](https://github.com/rimwall), not mine — it's what the units were
verified against.*

In the shift maps, cells showing `-` aren't editable: that curve has no vertex at
that pedal position, so there's no byte to change. Left blank rather than invented.

## Firmwares

Sixteen mapped, all Renesas M32R, every one with both checksums verified.
Decompiler output in [`decompiled/`](decompiled/).

Five of these — the EDM calibrations, the 2005 USDM Legacy GT and `AAD1A06000` —
came from [jimihimi/TCURoms](https://github.com/jimihimi/TCURoms).

| Cal ID | ROM ID | Size | Vehicle / notes |
|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM |
| `MB436G` | `91FE216300` | 512K | USDM, early 2005 Outback XT |
| `MB436T` | `91D0207500` | 384K | JDM |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 |
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM |
| `MB562EH` | `ADE0236000` | 512K | — |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 |
| `MB4365` | `91A0217300` | 384K | EDM |
| `MB4372` | `91A0217400` | 512K | EDM |
| `MB4364` | `91A1207300` | 384K | EDM |
| `MB436L` | `91FE207100` | 384K | USDM Legacy GT 2005 |
| `MB4402` | `AAD1A06000` | 512K | JDM |

RomRaider matches the cal ID at `0x8008` and loads the right one automatically.

## The other 5EAT controller: Denso SH705x

The 5EAT was built with two different transmission controllers. Everything above is
the **Hitachi M32R**. Later JDM and EDM cars, and the 2014 Tribeca, use a **Denso
SH705x** instead — a different processor, table format and checksum, sharing nothing
but the gearbox they drive.

Nine of those are now supported, in their own definition
([`definitions/5eat_tcu_denso_romraider_defs.xml`](definitions/)):

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

**Twelve shift schedules** per image, in real units — accelerator pedal angle against
vehicle speed in km/h. The address matches what rimwall reported for these TCUs, and
the units are read from the data rather than assumed.

Everything else is listed honestly as **unidentified**: a few hundred tables whose
structure is certain but whose physical quantity is not established. They are shown
raw, at `userlevel="4"`, so they are out of the way unless you go looking.

Denso protect these images with a block table at `0xFFB80` rather than the M32R's
two checksums; that is implemented as a separate plugin and is corrected on save.

## Confirmed units

Each verified two independent ways — against an external reference *and* against the
firmware's own arithmetic.

| Quantity | Conversion | How |
|---|---|---|
| Gear ratios | `raw / 1024` | 3.540 / 2.264 / 1.471 / 1.000 / 0.834 — published ratios to within 0.0007 |
| Engine speed | `raw / 8` | Clean 640 RPM breakpoints. **Caps at 8191 RPM** — `uint16` limit, not a display choice |
| Temperature | `raw − 40` °C | Standard −40…+215 °C automotive encoding |
| Vehicle speed | km/h direct | Factory shift chart |
| Accelerator angle | `raw × 100/255` | Shift chart, and CAN `0x412` byte 0 |
| **Line pressure** | **kPa direct** | Manual specifies 1370 kPa at full throttle; that value is in a table in all sixteen images |
| **Trouble codes** | P-number in **hex** | `0x705` = P0705. 53 codes, found via the thread's CAN `0x422` decoding |
| **Line pressure targets** | torque `/10` = Nm, pressure `/10` = kPa | Two *different* maps hit the manual's two figures: 490 kPa closed throttle, 1372 at 400 Nm |
| **Slip pressure factor** | `/1024` both axes | Reproduces rimwall's stated numbers: 0.5 slip → 1.392 ("~1.4"), 0.9 → exactly 1.000 ("~1.0") |
| **ATF temp factor** | `/256` | From the arithmetic, not the shape — unity is `0x100` and the product is `>>16`, exact only at `/256` |

Also confirmed: **both checksums** and the **shift schedule**, fully decoded.

Every image carries two checksums, and the TCU checks both:

| | Where | Rule |
|---|---|---|
| **Additive** | `0x8000` and `0x8004`, held twice | 32-bit BE two's-complement sum over the payload, whose extent is `0x60000` or the whole file — detected per image, not assumed |
| **Balance** | `0x8020` | Sum from there to the end of the payload. Three firmwares must reach `0x5AA5A55A`; the other thirteen test only the low half against `0x5AA5` and keep the balance in the halfword at `0x8022` |

The two-variant balance was read out of the firmware's own routine rather than
inferred — searching for the 32-bit form alone finds it in three images and makes
the rest look like they have no second checksum, which is wrong and would leave
them failing their own integrity check after any edit.

The pressure result is worth a note: four earlier attempts failed because they
searched the ROM. There's no conversion in there to find — the firmware already
works in kPa, and the answer was in the service manual all along.

## What isn't done

**Torque converter lockup.** Not found. It is at least no longer being looked for in
the wrong place: the factory manual describes engagement as *"Smooth
control — in lock-up clutch engagement, gradually changes pressure to provide smooth
engagement"*, which makes it a pressure ramp over time rather than a speed/pedal
threshold curve. That is why scanning for shift-curve-shaped arrays never turned it
up. See [FINDINGS.md](FINDINGS.md) §17e.

**Which operating condition selects which shift schedule is still unknown.** The
transmission carries 50 sets of shift curves — 10 operating conditions × 5 gear
limits — and all ten schedules now ship. What is missing is the mapping from driving
state to schedule. Sasha_A80 listed the likely conditions: cold and warm engine, cold
and warm ATF, catalyst preheat, quick shift, hill assist, driver style adaptation.
None is named on that basis, because guessing which is which would read as confirmed.

rimwall read the 5-way axis as a fuelling state (closed loop / open loop / sensor
error) in an early post. This project reads it as a gear limit, from the data; his
reading appears to come from a different array. Biggest open lead. See
[FINDINGS.md](FINDINGS.md) §14, §15 and §17a.

**Zero-to-disable on DTCs is inferred, not tested.** The trouble-code table is
mapped (see below), and blanking an entry should stop that code being reported —
zero is what the firmware's own 43 unused slots contain. Nobody has confirmed on a
car how a scan tool reports it, and it suppresses the *code*, not the fault.

Some tables still read `raw`. Those are the ones whose quantity hasn't been
established. A wrong unit reads as confirmed; an honest `raw` doesn't.

## Batch use

The application takes a `--cli` switch and runs headless, printing one JSON object
and exiting non-zero when the answer is no. It drives the real code — the same
parser, the same write path, the same `Rom.saveFile` the Save button calls — so it
checks the application rather than a copy of it.

```bash
RomRaider-TCU.exe --cli info     definitions/5eat_tcu_romraider_defs.xml rom/ACD1A06000.bin
RomRaider-TCU.exe --cli dump     <def> <rom> "Shift Map"
RomRaider-TCU.exe --cli checksum <def> <rom> --fix fixed.bin
RomRaider-TCU.exe --cli set      <def> <rom> "Shift Map" 12 65 out.bin
RomRaider-TCU.exe --cli selftest <def> rom/*.bin
```

`selftest` loads each ROM, confirms its checksums as shipped, edits a cell, saves,
and confirms them again — all sixteen M32R firmwares in about five seconds.

## Repo

| Path | What |
|---|---|
| [`romraider-5eat/`](romraider-5eat/) | The Windows app: patches, build script. **GPL-2.0**, not MIT |
| [`definitions/`](definitions/) | The RomRaider definition |
| [`tools/`](tools/) | Generator, validators, checksum, scanners — see [README](tools/README.md) |
| [`decompiled/`](decompiled/) | Ghidra output, sixteen images |
| [`rom/`](rom/) | The ROM images |
| [`docs/`](docs/) | [ROM details](docs/ROM-DETAILS.md) · [technical notes](docs/TECHNICAL-NOTES.md) · [manual setup](docs/ROMRAIDER-SETUP.md) |
| [`FINDINGS.md`](FINDINGS.md) | Full research log, in order, wrong turns included. Long |
| [`docs/forum_thread_13725.txt`](docs/) | All 385 posts of the RomRaider thread this work builds on, archived |

## Contributing

Adding a firmware: [`tools/README.md`](tools/README.md#adding-a-firmware). TCU dumps
not already here are the most useful contribution — five of the sixteen still need
their record-format curves mapped, and that needs a Ghidra pass per image.

If you contributed a ROM and want it removed or credited differently, open an issue.

---

## Credits

**Almost none of the raw material here is mine.** This is analysis layered on other
people's work.

**The ROM images** in [`rom/`](rom/) were dumped and shared by members of the
RomRaider thread [5EAT TCM JECS ROM Image](https://www.romraider.com/forum/viewtopic.php?f=40&t=13725)
over several years. Getting these off a car is slow, fiddly and occasionally risks
the TCU. They're here so the work can continue, not because I have any claim to
them. `91FE216300` is the one I dumped myself.

**The shift-curve chart** ([`docs/shift-curves-reference.png`](docs/shift-curves-reference.png))
is **rimwall's work**, posted to the thread with this description:

> *"The shift table pointers start at 0x180e8. The first lot of data is at
> 0x0001683c. The data is structured as words (uint16) in pairs of x, y. x is the
> Vehicle Speed in km/hr. y is the Accelerator Pedal Angle in % where 0xff = 100%.
> The data is terminated by 0xffff."*

It's the single most valuable external input here — the shift units were verified
against it, and both claims in that post check out exactly against `ACD1A06000`.

### The people in that thread

380 posts over several years. The work here rests on theirs.

**[rimwall](https://github.com/rimwall)** — by a wide margin the largest
contributor: the chart above, the shift-table encoding, the security-access and
protocol work that made these TCUs readable at all, the Denso side, the FastECU OEM
fork, and the corrected M32R Ghidra language this project's disassembly depends on.

**MiikaS** ([miikasyvanen](https://github.com/miikasyvanen)) — FastECU itself,
without which none of these ROMs could be dumped.

**ajayel**, **riksk**, **jimihimisimi**, **AJ08H65EAT**, **kiki86**, **curt4576**
— the testing effort: dumping TCUs, running experimental builds, posting logs, and
taking bricking risk on their own vehicles to prove the read/write paths.

**Sasha_A80** — the original JDM ROM that opens the thread, and the M32R chip
identification. **V6er**, **trcxsa**, **Blake_Volpex**, **ciper**, **SergArb**,
**roadie**, **Waselon**, **dschultz**, **b4andrey**, **Tugsay**, **Alucard7002**,
**alesv**, **lvkeith**, **fenugrec** — analysis, dumps, corrections and domain
knowledge throughout.

**Comer352L** — FreeSSM, and the branch adding 5EAT TCU adjustment support.

If you're on this list and want your name removed, changed, or your contribution
described differently, open an issue.

### Prior and parallel work

- **[FastECU](https://github.com/miikasyvanen/FastECU)** (Miika Syvänen) and
  **[rimwall's OEM fork](https://github.com/rimwall/fastecu-oem)** — the tooling
  that makes reading and writing these TCUs possible. Its
  `checksum_tcu_subaru_hitachi_m32r_can` module, on the **`development`** branch,
  is where the second checksum came from — `master` carries no TCU code at all.
- **[FreeSSM](https://github.com/Comer352L/FreeSSM)** (Comer352L) — diagnostics,
  and the branch adding TCU adjustment support.
- **[ghidra-m32r](https://github.com/ripnet/ghidra-m32r)** (ripnet) — the Ghidra
  processor module, without which none of the disassembly exists.
- **[RomRaider](https://github.com/RomRaider/RomRaider)** — the editor itself.
- Forum findings used directly: the CAN ID meanings (`0x412` engine torque, `0x514`
  shift events), the MCU identification, and the observation that gear changes are
  governed by pedal-angle/speed curves — which is what pointed at the shift tables
  in the first place.

Gear ratios, line-pressure targets and ATF temperatures come from the Subaru factory
service manual (2004 Legacy). That document is Subaru's and is **not** redistributed
here.

### What is actually mine

The tooling in [`tools/`](tools/), the definitions in [`definitions/`](definitions/),
and the written analysis in [`docs/`](docs/) — table mapping, unit derivations,
checksum region detection, multi-firmware porting. That, and nothing else here, is
what the MIT licence covers.

---

## Legal

The ROM images are Subaru/Fuji Heavy Industries firmware, included for
interoperability and repair research. Not my work, no rights claimed. The
decompiler output in [`decompiled/`](decompiled/) is derived from them and carries
the same status.

My own contributions are MIT licensed — see [LICENSE](LICENSE).

**[`romraider-5eat/`](romraider-5eat/) is GPL-2.0, not MIT.** Those patches are
diffs against RomRaider, so they're a derivative of a GPL-2.0 program, and so is the
package built from them. If you redistribute it, GPL-2.0 requires you to provide
corresponding source; the patches plus the upstream revision pinned in
`build-standalone.sh` are what satisfy that. See
[`romraider-5eat/LICENSE`](romraider-5eat/LICENSE).

**Flashing a modified transmission controller can damage the transmission.** This is
static analysis; almost none of it has been validated on a running vehicle. Anything
marked experimental or expert-only genuinely is. Use at your own risk.

— TomFLV
