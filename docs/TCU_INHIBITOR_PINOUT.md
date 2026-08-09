# 2006 Tribeca 5EAT TCU — Inhibitor / Selector Pinout (B55 connector)

ROM: `8AF0237300` (MB500NJ0VF32C), Hitachi M32R.
Source manual: **TRANSMISSION SECTION.pdf** (validated correct for this unit — its
pin 8 = H&LR/C oil-pressure switch matches the bench probe). The `5ATDIAGN.pdf`
pinout (inhibitor at 8/9/10/11) is the WRONG variant for this TCU — do not use it.

## Connector B55 (24-pin, TCM side)
```
 1  2  3  4     5  6    7    8  9
10 11 12 13    14 15   16   17 18
19 20 21             22   23 24
```

## Inhibitor switch inputs (validated: manual pins + firmware ports)
| Switch | B55 pin | M32R port | SSM 0xD4 bit |
|--------|---------|-----------|--------------|
| Inhibitor SW1 | **B55-4**  | P0.7 | 0x40 |
| Inhibitor SW2 | **B55-3**  | P0.6 | 0x20 |
| Inhibitor SW3 | **B55-14** | P0.5 | 0x10 |
| Inhibitor SW4 | **B55-13** | P0.4 | 0x08 |
| Inhibitor SW3 open-circuit monitor | **B55-20** | P4.4 | 0x04 |
| H&LR/C oil-pressure SW | **B55-8** | (DAT_008055c0) | SSM 0xD5 bit 0x20 |

SW3 monitor (B55-20) is the electrical **inverse** of SW3 (B55-14):
D range → monitor High / SW3 Low; R range → monitor Low / SW3 High.

Firmware chain: `DAT_00804f08 = CONCAT11(P4DATA, P0DATA)` → `FUN_0002a240`
packs P0.7/P0.6/P0.5/P0.4/P4.4 → XOR `0x1F` (`DAT_0001c2e9`) → `DAT_008047f2`.
A switch **grounded (Low)** sets its `DAT_008047f2` bit; **open (High)** clears it.
`FUN_0002aa34` builds SSM 0xD4 (bit set = switch OPEN). Position decode
(`~line 33327`) indexes ROM table `0x1C2EB` by `(DAT_008047f2 ^ 0xFF) & 0xF`.

## Position truth table (ground = close switch to chassis ground)
Derived from the ROM decode table `0x1C2EB` + manual voltage anchors (SW1 P/N,
SW2 P/D, SW3 R/D, SW4 P/D — all four satisfied) + the P/N-signal grouping
(range code 5||7). "GND" = tie the B55 pin to ground; blank = leave open.

| Position | code | SW1 (B55-4) | SW2 (B55-3) | SW3 (B55-14) | SW4 (B55-13) | Pins to ground |
|----------|------|-------------|-------------|--------------|--------------|----------------|
| **P (Park)** | 7 | open | open | open | open | **none — all open** |
| R (Reverse) | 6 | GND | open | open | GND | B55-4 + B55-13 |
| N (Neutral) | 5 | GND | GND | open | open | B55-4 + B55-3 |
| D (Drive)   | 4 | GND | GND | GND | GND | B55-4 + B55-3 + B55-14 + B55-13 |

(Range codes 0/1/2 = index 10/9/1 = manual-gate / lower positions; not needed for P–D.)

## Key result for bench work
**Park is the all-open state.** With the inhibitor inputs unwired, the TCU already
reads Park — that is exactly why the unwired unit shows SSM 0xD4 = 0x78 (all four SW
"open") and why grounding pins could never *add* Park: it was already there.
To move OUT of Park (into R/N/D) you START grounding pins per the table above.

Bench check: unwired, FreeSSM "P range" signal should already read ON. Grounding
B55-4 + B55-13 (both to chassis ground) should flip SSM 0xD4 from 0x78 and select R.

## P0705 (Transmission Range Sensor Circuit) — manual-authoritative fix
DTC P0705 (`0x0705` @ dtc_code_tbl 0x1D778). **Manual detecting condition:
"the inhibitor switch is open or short."** On the bench with the inhibitor unwired,
all five inputs float HIGH (internally pulled to ~5 V — manual step 6: SW1-4 = 4-6 V,
SW3 monitor = 3.5-5.5 V), i.e. permanent open circuit → P0705 by design. Not clearable
while the switch is open.

Firmware mechanism (`FUN_0002af44`, result → SSM 0x8052BB): a per-channel integrity
self-test — each of SW1/SW2/SW3/SW4/SW3-monitor keeps its fault bit set until that line
is seen transitioning BOTH open→ground AND ground→open. A static/unwired bench never
toggles, so it never clears. Latches (0x8054C2) are RAM → reset every power-up, so the
switch must be exercised after each key-on.

Manual Select-Monitor expectation (steps 2 & 4):
- **P range → SW1-4 + SW3 monitor all read HIGH**
- **D range → all read LOW**

The **SW3 monitor (B55-20)** is wired as the electrical COMPLEMENT of SW3 (B55-14):
grounded when SW3 open, open when SW3 grounded (firmware inverts it so the display
tracks SW1-4). So Park = B55-4/3/14/13 OPEN + B55-20 GROUNDED; Drive = B55-4/3/14/13
GROUNDED + B55-20 OPEN. (This is why unwired SSM 0xD4 = 0x78, bit 0x04 clear — the
monitor isn't complementing SW3, which is the open-circuit signature.)

### Bench fix to clear P0705
1. Wire the 5 lines to a switch, ground return to **B54-19** (control GND) / chassis:
   SW1=B55-4, SW2=B55-3, SW3=B55-14, SW4=B55-13, SW3-monitor=B55-20 (complement of SW3).
2. Power on, then cycle **P → D → P** so every line goes High→Low→High (both directions).
3. Clear P0705 — stays cleared until next power-up (re-exercise after each key-on).

Harness pin pairs (TCM B55 → trans B12) from manual step 5, if tracing:
B55-4→B12-4, B55-3→B12-3, B55-14→B12-2, B55-13→B12-1, B55-20→B12-8.
