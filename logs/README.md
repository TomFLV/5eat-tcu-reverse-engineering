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
