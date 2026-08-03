# Vehicle logs

RomRaider logs captured from a running 5EAT, October 2024. These are the only
real-vehicle data in this project; everything else is static analysis.

| File | Rows | Contents |
|---|---|---|
| `romraiderlog_20241016_133923.csv` | 568 | A full drive: 0–173 km/h, all five gears, 599–6944 rpm, ATF 87–92 °C. Engine and turbine speeds, gear, wheel speeds, and the pressure of all seven solenoids by name |
| `romraiderlog_20241016_113910_TCU5.csv` | 43 | Select Monitor pressure corrections: per-shift and line pressure, plus 4WD |
| `romraiderlog_20241016_133733.csv` | 53 | The same corrections, second capture |

Semicolon-delimited, as RomRaider writes them.

What they established is in [FINDINGS.md](../FINDINGS.md) section 34. In short:

- **Lock-up engages in fourth as well as fifth.** Never below fourth, which was the
  part the project had right, but fourth reaches about half the pressure fifth does
  and on far fewer samples. The working assumption had been fifth only.
- **All seven solenoids are confirmed** by name and working range, matching the
  channels identified from the firmware.
- The Select Monitor's `P/L Solenoid Valve Pressure` reaches **2520 kPa**, above the
  1370 kPa the line-pressure tables hold. The two are therefore not the same
  quantity, which is worth knowing before comparing a log against a table.

What they do not settle: which firmware channel is lock-up. The log reports Select
Monitor parameters by name, not RAM addresses, so it cannot separate `0x804EB2` on
TIO5 from `0x804EB6` on TIO7. That needs the duty addresses themselves logged.

The pressure-correction captures line up with the adjustments in FreeSSM's
`e5at-permanent-adjustments` branch.

## Reading these logs

**`Gear Position` lags the real shift by about 0.4–0.6 seconds.** The ratio of turbine
speed to road speed shows the transmission already at the next gear's ratio while the
logged gear still reports the old one. Under hard acceleration that puts any shift
speed read straight from the log roughly 10 km/h late.

Derive the shift instant from `Turbine Revolution Speed / Front Wheel Speed` instead.
Steady-state values measured here are 101, 64, 43, 30 and 26 turbine-rpm per km/h for
gears 1 to 5. Normalised against fifth those give 3.94, 2.48, 1.69, 1.16 and 1.00,
against published ratios of 4.25, 2.72, 1.76, 1.20 and 1.00 — fourth and fifth agree
within 3%, the lower gears read low because nearly all their samples are taken mid-
acceleration.

## The car these came from

Unit **A3DE207100**, calibration **WQDE2WB1** — a **Denso** SH705x, byte-identical to
`rom-denso/Impreza_STI_3.583_JDM2011.bin`. So the exact firmware is known and already
has a definition here.

**Full-throttle shifts do not use the speed tables.** All twelve of this calibration's
shift tables read 224 or 205 km/h in their full-pedal column — speeds the car never
reaches, so the entry means "do not upshift on road speed". What fires instead is
engine speed. Converting the observed shifts through the measured gear ratios:

| shift | road speed | turbine rpm |
|---|---|---|
| 1→2 | 73 km/h | 7300 |
| 2→3 | 103 km/h | 6592 |
| 3→4 | 146 km/h | 6278 |

against a logged maximum of 6944 rpm. Those are redline shifts. The speed tables
govern part-throttle behaviour only.

## Parsing warning

**The numeric columns use a comma decimal separator** (`0,00`). `float()` fails on
them silently, so a column of perfectly good data reads as empty. Convert the comma
before parsing — an earlier pass here wrongly reported accelerator angle as unlogged
for exactly this reason.

## What the tables actually do

Each 15×5 shift table has four live rows, and they are the four upshifts — at idle
they read 19, 29, 44 and 54 km/h, rising in order. Even-numbered tables pair with
odd ones as upshift/downshift, so the twelve are six schedules.

**Above roughly 35% pedal the speed table stops deciding.** Every curve flattens into
the same tail ending at 224 km/h, a speed this car never reaches, so the entry means
"do not upshift on road speed". The full-throttle shifts in this log happen at 7300,
6592 and 6278 turbine rpm against a 6944 rpm maximum — they are redline shifts.

Practical consequence: **changing the high-pedal end of a shift curve will not move a
full-throttle shift point.** Only the part-throttle region does anything.

**Below that, the table is necessary but not sufficient.** The one part-throttle
upshift here happened at 99 km/h and 17% pedal, where the highest threshold across all
twelve tables is 74 km/h. The car sat 25–45 km/h above every threshold it has, in the
right gear, for four seconds before shifting — so something inhibits the upshift
beyond the speed comparison.

See [FINDINGS.md](../FINDINGS.md) sections 35 to 37.
