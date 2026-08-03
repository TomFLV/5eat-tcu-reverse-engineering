# Technical notes

How the tables, the checksum, and the unit conversions in this project were worked
out. This covers method as much as results, so the same approach can be applied to
firmwares not yet included.

Addresses given below are for **`91D1206000`**, the reference firmware. Sixteen are
mapped in total; structure and formats are shared across the family but **specific
addresses are not** — they shift non-uniformly and are derived per firmware.

---

## Toolchain

**Ghidra** with the community [M32R processor module](https://github.com/ripnet/ghidra-m32r).
radare2 was tried first and rejected — it has no M32R support at all.

Three things had to be fixed to get the module working on a current Ghidra:

1. The bundled `.sla` was stale. Recompile from the `.slaspec` with the installed
   Ghidra's own `support/sleigh`.
2. `m32r.pspec` fails schema validation — its `<memory_block>` elements predate a
   schema change. Add `initialized="false"` to each.
3. `Module.manifest` must be an **empty** file.

Import as raw binary, language `m32r:2:default`, **base address `0x0`**.

Base address matters. An initial attempt used `0x100000` (the CS0 external
chip-select region from the chip's memory map) and produced nothing coherent. This
is a single-chip MCU executing from internal flash at address 0 — the external
chip-select windows aren't used. Disassembling at `0x0` immediately produces valid
boot code, which is how the address was confirmed.

### Getting full code coverage

Seeding analysis from the reset vector alone reaches ~130 functions. The rest is
behind the interrupt table, which is **three levels deep**:

1. Hardware vectors at `0x0`–`0x83` (standard M32R exceptions, each a `BRA`).
2. A pointer-to-pointer table at `0x94`–`0x10C`.
3. The real handler address table at `0x20000`–`0x2007C` — 31 slots, most holding
   the default `0x20100`, with only **four** distinct real handlers:
   `0x245BC`, `0x20A14`, `0x26748`, `0x25828`.

Seeding those four addresses takes coverage from 167 functions / 25 KB to
**1,090 functions / 234 KB** — roughly 90% of the code region — in one pass.

Ghidra's decompiler works well on M32R output. `tools/ghidra/DecompileAll.java`
dumps the whole program; the result is in `decompiled/full_decompile.c`. Grep that
first before tracing anything by hand.

---

## Table formats

Three distinct formats are used, each with its own lookup routine.

### Format 1 — count-prefixed, interpolated

```
[count:u16][axis: count × u16][data: count × u16]
```

Confirmed by decompiling the lookup routine at `0x4515C`, which is textbook linear
interpolation: find the bracketing pair, then
`y0 + (X - x0) * (y1 - y0) / (x1 - x0)`, output clamped to unsigned 16-bit.
`0x45234` is the unsigned-breakpoint variant, `0x45300` a third variant.

Axis values are read signed during interpolation, so negative data (small values in
two's complement) is meaningful in some tables.

**Every call site of all three routines has been enumerated — there are exactly 13
in the whole program, and all are accounted for.** This format is fully mined out.

These are the tables exposed in the RomRaider definition.

### Format 2 — 8-byte hysteresis records

```
[A:u16][B:u16][C:u16][D:u16]  × n, terminated by a leading 0xFFFF
```

Handled by `0x45070`. Record *i* holds breakpoint *i* in field A and breakpoint
*i+1* in field C, with B/D a rising/falling value pair — separate up- and
down-shift trigger points, which is exactly what an automatic transmission shift
schedule needs.

**This format IS exposed**, as `type="3D"` tables.

It was excluded for a long time on the reasoning that the fields are interleaved
at an 8-byte stride and RomRaider's schema has no stride attribute. That
reasoning was wrong, and worth recording as a caution: the *fields* are
interleaved, but the *record block is contiguous*. A 3D table with `sizex=4`
(the four fields) and `sizey=n` (the records) maps onto the raw bytes exactly,
with no stride support needed. RomRaider's own parser accepts them.

Currently exposed:

- **8 shift schedule curves** per firmware, in real units (see below).
- **35 further record curves**, including the two temperature sensor
  linearisation tables. These carry `raw` values — their inputs are named where
  traced and labelled as unidentified internal signals where not.

They are found by enumerating every call site of the record-lookup routine and
reading the table pointer from the argument, then filtering to curves whose
breakpoint column is genuinely monotonic. **That filter is load-bearing**: it
rejects the gear-indexed pointer arrays, which otherwise walk as
plausible-looking tables and would ship addresses pointing at pointer bytes.

### Format 3 — plain contiguous arrays

Ordinary indexed reads, no lookup routine — e.g. `(&DAT_0001234C)[gear]`. Around 90
of these exist. Being contiguous and fixed-stride, they map onto RomRaider's
storage with no difficulty. The gear ratio table and the shift-state bit patterns
come from this group.

---

## Locating tables

Two complementary methods, both needed.

**Pattern scanning** finds format-1 candidates by
looking for a plausible count followed by a monotonic axis. This yields 307
candidates across the ROM, most of which are coincidence. Cross-referencing against
32-bit absolute pointers elsewhere in the ROM narrows it to 38 high-confidence hits.

**Call-site enumeration** is far more reliable: grep the decompiled output for every
call to a known lookup routine and read the table pointer out of the argument. This
is how the confirmed tables were found, and it's the method to prefer.

A caution learned the hard way: a string match on an address in decompiled output is
**not** evidence of a table. `0x8688` and `0x1CEE8` both matched, and both turned
out to be plain scalar reads. Always check how the address is actually used —
indexed array access means a table, a bare comparison does not.

Another: when several parallel arrays sit adjacently, **the spacing between them is
their length**. Five bitmask arrays at `0x87AA`–`0x87EF` were initially sampled at 8
entries; the 14-byte spacing shows they're 14 entries each.

---

## Unit conversions

Five are confirmed. Each was verified two independent ways — against an external
reference (the factory service manual, or a shift chart posted by rimwall) *and*
against the firmware's own arithmetic. Anything not meeting that bar is left
labelled `raw`.

| Quantity | Conversion |
|---|---|
| Gear ratios | `raw / 1024` |
| Engine speed | `raw / 8` |
| Temperature | `raw − 40` °C |
| Vehicle speed | km/h, no scaling |
| Accelerator angle | `raw / 255` → 0–100% |

### Gear ratios — `raw / 1024`

Table at `0x1234C`, five `u16` values indexed by current gear:

| raw | ÷1024 | manual |
|---|---|---|
| 3625 | 3.5400 | 3.540 |
| 2318 | 2.2637 | 2.264 |
| 1507 | 1.4717 | 1.471 |
| 1024 | 1.0000 | 1.000 |
| 854 | 0.8340 | 0.834 |

Matches to within 0.0007 on every gear. Independently, the firmware divides these
by `0x400` when computing expected speed — the code confirms the scale factor
without reference to the manual.

Used for expected-output-speed calculation and gear ratio fault detection
(`P0730`). Editing these does not change physical gearing — it changes what the TCU
*believes* the gearing is.

### Engine speed — `raw / 8`

The signal feeding the Speed Trim, Slip Detection and Reference Speed table axes is
`smoothing_filter(speed << 3)` — an explicit ×8 in code. The pre-scaled value shares
its ceiling constant (`0x1C2A8` = 10000) with two hardware speed channels whose RPM
conversion is confirmed, which is what ties the unit down.

Those channels convert as `60000000 / (N × period)` — the standard period-to-RPM
form (60 s × a 1 MHz timer ÷ pulses per revolution). Two independent channels with
their own tooth counts: `0x1C2C1` = 16 and `0x1C2C2` = 22.

The resulting axes are clean 640 RPM steps topping out at 6400 RPM, with the
`0xFFFF` sentinel landing at ~8192 RPM as an "and above" point.

> An earlier revision of this project used `raw / 12.8` here, labelled as an
> estimate. That was wrong — it produced a 4000 RPM ceiling, implausible for this
> engine family. Noted because the structural reasoning behind it looked convincing
> and wasn't.

### Temperature — `raw − 40` °C

Two NTC thermistor channels. Both routines invert the raw reading (`0xFF - raw`)
before linearising, which is the giveaway — an NTC's voltage falls as temperature
rises.

Linearisation tables at `0x807E` (45 records) and `0x81E8` (41 records), in format 2,
read as `[adc, temp, adc, temp]` pairs. The output column steps in 5s against a
curve that flattens at both ends.

Both map ADC `0..255` onto output `0..255`, which with the −40 offset is exactly
**−40 °C to +215 °C** — the standard automotive encoding. Without the offset the
sensor could not represent sub-zero temperatures at all.

Validated against the manual:

| constant | decodes to | manual reference |
|---|---|---|
| `0x12930` | 71 °C | normal operating range 70–80 °C |
| `0x12945` | 75 °C | same range |
| `0xEFC7` | 55 °C | top of test range 45–55 °C |

23 temperature constants were found in total. Four with fully traced roles are in
the definition file; the rest are listed but not named, since guessing at their
purpose in a file intended for real edits is worse than omitting them.

---

## Signal architecture

The TCU is CAN-driven rather than sensor-driven for its primary inputs. The receive
routine at `0x28E88` handles IDs `0x410`, `0x411`, `0x412`, `0x511`–`0x515`,
`0x520`, `0x600`, `0x740`, `0x741`.

Traced paths:

- **`0x410` bytes 5:6** → ceiling clamp → first-order smoothing filter → the engine
  speed axis of the main table families.
- **`0x412` byte 0** → one operand of the Pressure Control X-formula. (The forum
  established that bytes 3–4 of this message carry calculated engine torque.)
- **`0x511` byte 4** → scaled ×333/256 → a threshold curve at `0x11836`.
- **`0x514`** carries shift events — per the forum, byte value 2 = upshift,
  4 = downshift.

The general shape, independently confirmed by the forum thread: a CAN torque signal
is smoothed, factored by a lookup based on ATF temperature, and used to look up a
line pressure target.

### Gear and shift state

`0x80885A` is the current commanded gear (0–4), written by exactly one function —
the gear state machine at `0x4CA24`, which includes two distinct limp-mode paths
(one forcing a configurable fail-safe gear, one hard-coding 3rd).

Shift schedules are selected from a 50-entry pointer array at `0x17714`, indexed as
`gear × 2 + mode × 10` — five range modes × five gears × two slots. Mode 0 has real
multi-point curves throughout; modes 1–4 progressively fall back to a shared
single-record placeholder for higher gears, consistent with range-restricted
operation.

---

## Line pressure

There is **no pressure sensor on this transmission.** The service manual's own line
pressure test requires removing a test plug, fitting a mechanical gauge, and
separately reading the TCU's *"P/L solenoid target pressure"* off the scan tool to
compare. If the TCU had pressure feedback, the gauge would be redundant.

This is corroborated by the DTC table — `P0745`/`P0746`/`P0748`/`P074C` are all
pressure control *solenoid* codes (an output), and there is no pressure sensor
circuit code anywhere in it. The pressure-related status bits found in RAM are
switch (on/off) feedback, not analogue.

So pressure is commanded open-loop via a duty solenoid.

**kPa is not stored in these ROMs.** Four tests across all sixteen firmwares:
the manual's values appear as code immediates **zero** times; no calibration run
spans the pressure bands; no record curve has a pressure-shaped value range; and
`490` and `1370` both appear in the calibration region of only **1 of 11**
firmwares. Those are transmission specs identical across every variant — if the
TCU stored them they would be in all eleven, so the single hit is chance.

The likely explanation is that the TCU reports a raw duty or target value and the
**Select Monitor performs the kPa conversion itself** — consistent with there
being no pressure sensor, and with the DTC table having no reader in the ROM
either. The diagnostic presentation layer is not on the TCU side.

Settling it needs either an SSM parameter definition for the TCU (FreeSSM ships
none) or empirical logging against the scan tool's readout. **Neither is a
static-analysis problem; more ROM searching will not resolve it.**

---

## Things deliberately not done

Recorded so they aren't mistaken for oversights:

- **No checksum-fix table in the definition.** RomRaider's checksum support is
  hardcoded per ECU family in Java and doesn't cover this one. Including a
  checksum table would imply it works.
- **Five firmwares omit the record curves.** Positional matching against the base
  ROM's call-site order is only safe where the counts match; five firmwares issue
  34 or 36 call sites against the base's 35, so the mapping could be off by one
  somewhere undetectable. Those five keep their fully verified 56-64 tables
  instead of an approximated set.
- **Pressure and most temperature constants left unlabelled.** No confirmed
  conversion, so `raw` is the honest answer.
- ~~The `0x5AA5A55A` checksum from FastECU not implemented.~~ **This was wrong and
  has been corrected.** It does hold, on every image, and it is now implemented.
  The earlier reading failed because it assumed a single 32-bit form: three
  firmwares test the full sum against `0x5AA5A55A`, and the other thirteen test only
  the low half against `0x5AA5`, keeping their balance in the halfword at `0x8022`.
  Both forms are detected per image. Releases up to 1.4.2 shipped without this, so
  a ROM saved by one of those fails the check the TCU runs at start-up.


---

## Settled since these notes were first written

**Both checksums.** See the correction above. `tools/checksum.py` and the editor's
plugin implement both forms and agree byte for byte on all sixteen images.

**How a shift schedule is chosen.** The index is `condition * 2 + group * 10`, read
from two pointer arrays at `0x17714` and `0x17718`. The group comes from a selector
byte holding `0x80`-`0x85` or `0x8C`, which is looked up in a table rather than read
from a sensor - that table now ships as `Shift Schedule Group Selector`. This also
confirms from the firmware what was previously inferred from the data alone: the
five-axis of the shift-mode structure is a GEAR LIMIT. Which driving condition each
value of the condition byte represents is still unknown. FINDINGS section 33.

**The ATF blend window.** All seven solenoid drivers interpolate their target
pressure across a temperature window bounded by a pair of bytes, 15 C to 135 C in
every firmware. Located per firmware by `tools/extract_atf_blend.py`. FINDINGS 29c.

**The downshift ramp pair.** `Downshift Ramp Step` and `Downshift Ramp Hold` were
labelled from the code but unconfirmed. The control loop settles it: a counter
increments each cycle and is compared against the hold, while the step is added to a
pressure. The labels were correct. FINDINGS section 32.

**Fixed-point storage.** Fourteen tables are stored with fractional low bits - every
value in every firmware is an exact multiple of a power of two - so they now display
the numbers the calibrator entered rather than raw storage. What they measure is
still not established, and their unit labels say so. FINDINGS section 28.

## Still open, and why

**Torque converter lock-up.** Narrowed to two of the seven solenoid channels,
`0x804EB2` on TIO5 (package pin 102) and `0x804EB6` on TIO7 (pin 104). Their drivers
are exact mirrors sharing 965 symbols, so no amount of reading them separates the
two. The one asymmetry is a fallback constant at `0x1C2AE` that TIO7 uses and TIO5
does not. A log of both duty addresses during engagement would settle it in one
drive. FINDINGS 25c and 29.

**Naming the Denso tables.** Closed as not worth repeating by static analysis. A
Denso image is fully disassembled - about 51% instructions against 47% code-like
content, the rest blank flash and constant pools - and with that coverage the
calibration pointer arrays still have no references from outside themselves. The
addresses are computed at runtime. GBR is not the route either: its 248 load sites
all take on-chip RAM addresses, so it serves state variables rather than ROM tables.
Only emulation would recover it. FINDINGS section 31.
