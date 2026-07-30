# Subaru 5EAT TCU — Reverse Engineering & RomRaider Definition

The Subaru 5EAT keeps its shift points, line pressures and clutch timing in a
transmission controller nobody had published a tuning definition for. This is the
work of opening one up.

### ▶ [Download the Windows app](../../releases/latest)

Extract the folder, run `RomRaider-TCU.exe`, `File -> Open` a ROM from `app\roms`.
A Java runtime, the definitions and eleven ROM images are bundled — nothing to
install, nothing to configure.

Already run RomRaider? Point it at [`definitions/5eat_tcu_romraider_defs.xml`](definitions/)
instead. Needs 1.0.0+; 0.8.2 can't load 3D tables.

> **The checksum is handled for you.** The bundled build corrects it on save — the
> algorithm is implemented as a RomRaider checksum plugin, so there is no extra step.
> If you use stock RomRaider instead, it has no manager for this ECU and you must fix
> it yourself before flashing:
> ```bash
> python tools/checksum.py --fix edited.bin
> ```

---

## What you can actually tune

| Category | What it is |
|---|---|
| **Shift Schedule** | **Ten** complete shift maps — speed in km/h against % pedal, one row per shift event. Plus a **drag-and-drop curve editor** on the toolbar. |
| **Line Pressure** | Nine target maps, **engine torque (Nm) → line pressure (kPa)**, plus the slip and ATF-temperature multipliers that feed them |
| **Downshift Pressure** | Per-downshift target pressure in kPa, and the ramp step and hold that set how harshly each one applies |
| **Diagnostic Codes** | All 53 trouble codes, individually, each Enabled/Disabled |
| **Sensor Calibration** | ATF temperature sensor linearisation, ADC counts → °C |

Ten shift maps, because the transmission carries ten complete schedules and switches
between them by operating condition. The definition used to ship one. Each also has
four gear-limited variants for manual mode, which reuse the same curves.

![shift curves](docs/shift-curves-reference.png)

*Chart by [rimwall](https://github.com/rimwall), not mine — it's what the units were
verified against.*

In the shift maps, cells showing `-` aren't editable: that curve has no vertex at
that pedal position, so there's no byte to change. Left blank rather than invented.

## Firmwares

Eleven mapped, all Renesas M32R, all with verified checksums. Decompiler output for
sixteen images in [`decompiled/`](decompiled/).

| Cal ID | ROM ID | Size | Vehicle / notes |
|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM |
| `MB436G` | `91FE216300` | 512K | USDM, Early 2005 Outback XT |
| `MB436T` | `91D0207500` | 384K | JDM |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 |
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM |
| `MB562EH` | `ADE0236000` | 512K | — |

RomRaider matches the cal ID at `0x8008` and loads the right one automatically.

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
| **Line pressure** | **kPa direct** | Manual specifies 1370 kPa at full throttle; that value is in a table in all eleven images |
| **Trouble codes** | P-number in **hex** | `0x705` = P0705. 53 codes, found via the thread's CAN `0x422` decoding |
| **Line pressure targets** | torque `/10` = Nm, pressure `/10` = kPa | Two *different* maps hit the manual's two figures: 490 kPa closed throttle, 1372 at 400 Nm |
| **Slip pressure factor** | `/1024` both axes | Reproduces rimwall's stated numbers: 0.5 slip → 1.392 ("~1.4"), 0.9 → exactly 1.000 ("~1.0") |
| **ATF temp factor** | `/256` | From the arithmetic, not the shape — unity is `0x100` and the product is `>>16`, exact only at `/256` |

Also confirmed: the **checksum** (32-bit BE two's-complement additive, stored twice
at `0x8000`/`0x8004`, over two region conventions the tool detects rather than
assumes) and the **shift schedule**, fully decoded.

The pressure result is worth a note: four earlier attempts failed because they
searched the ROM. There's no conversion in there to find — the firmware already
works in kPa, and the answer was in the service manual all along.

## What's not

**Torque converter lockup — not found, but no longer being looked for in the wrong
place.** The factory describes engagement as *"Smooth control — in lock-up clutch
engagement, gradually changes pressure to provide smooth engagement"*, so it's a
**pressure ramp over time**, not a speed/pedal threshold curve. That's why scanning
for shift-curve-shaped arrays never found it. See [FINDINGS.md](FINDINGS.md) §17e.

**74 of 82 threshold curves are unmapped, and we now know what they are.** The
definition ships **one cell of a 5 × 10 grid**: rimwall established the transmission
carries 50 sets of shift curves, 5 fuelling states (closed loop / open loop / sensor
error) × 10 operating conditions. Sasha_A80 listed the likely conditions — cold and
warm engine, cold and warm ATF, catalyst preheat, quick shift, hill assist, driver
style adaptation. *Which* condition is which is still unknown, so nothing is named on
that basis. Biggest open lead. See [FINDINGS.md](FINDINGS.md) §15 and §17a.

**Zero-to-disable on DTCs is inferred, not tested.** The trouble-code table is
mapped (see below), and blanking an entry should stop that code being reported —
zero is what the firmware's own 43 unused slots contain. Nobody has confirmed on a
car how a scan tool reports it, and it suppresses the *code*, not the fault.

Some tables still read `raw`. Those are the ones whose quantity hasn't been
established. A wrong unit reads as confirmed; an honest `raw` doesn't.

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
not already here are the most useful contribution — five of the eleven still need
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
  `checksum_tcu_subaru_hitachi_m32r_can` module independently corroborated the
  checksum algorithm.
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
