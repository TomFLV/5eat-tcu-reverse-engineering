# Verifying the TCM pinout on your own unit

*Written 2026-08-07, against a Hitachi `31711AJ675` from a 2006 B9 Tribeca.*

The pinout in [BENCH-RIG.md](BENCH-RIG.md) comes from a service manual that never
names a model and that mentions an electrical architecture ("body integrated unit")
newer than a 2006 car. Rather than trust it or discard it, check it — every pin
below can be measured with the unit unplugged and unpowered, so nothing is at risk.

## Which connector is which

| colour | designator | how to confirm |
|---|---|---|
| **white** | **B54** | every valve-body solenoid output is here |
| **grey** | **B55** | inhibitor switch inputs, AWD solenoid, ignition supply |

Confirmed two ways: the service literature states white B54 / grey B55 for the
5EAT, and on a real `31711AJ675` the output devices are on the white connector.

## The measurable pins

Solenoid windings read a few ohms. If these match, the manual's numbering applies
to your unit; if they read open or wildly different, it does not, and nothing else
on this page should be trusted either.

Measure between the pin and a ground pin (B54 5, 14 or 19), with the TCM
disconnected and the harness still attached to the transmission.

| connector | pin | device | expected |
|---|---|---|---|
| B54 | 9 | P/L solenoid (line pressure) | 3–9 Ω @ 20 °C |
| B54 | 15 | LC/B solenoid | 5–17 Ω @ 25 °C |
| B54 | 17 | H & LR/C solenoid | 3–9 Ω @ 20 °C |
| B54 | 18 | I/C solenoid | 3–9 Ω @ 20 °C |
| B54 | 22 | D/C solenoid | 3–9 Ω @ 20 °C |
| B54 | 23 | L/U solenoid (lock-up) | 3–9 Ω @ 20 °C |
| B54 | 24 | Fr/B solenoid | 3–9 Ω @ 20 °C |
| B55 | 23 | AWD solenoid | 3–9 Ω @ 20 °C |
| B55 | 15 | (per manual) | 7–21 Ω |

The ATF temperature sensors are thermistors and also measurable:

| connector | pin | device | expected |
|---|---|---|---|
| B54 | 2 | ATF temperature sensor 1 | 4.0–5.0 kΩ @ 20 °C, 0.7–0.9 kΩ @ 80 °C |
| B54 | 11 | ATF temperature sensor 2 | 3.0–3.6 kΩ @ 20 °C, 0.4–0.6 kΩ @ 80 °C |

## Power and ground — wire these first, and only these

| connector | pin | function |
|---|---|---|
| B54 | 1 | Battery power supply (permanent) |
| B54 | 7, 8 | PVIGN power supply (switched) |
| B54 | 10 | PVIGN power supply relay output |
| B54 | 5, 14 | Power GND |
| B54 | 13 | Analog GND (sensor ground) |
| B54 | 19 | Control GND |
| B55 | 1, 10 | Ignition power supply |
| B55 | 21 | Control GND |

The manual's supply check expects 9–16 V at the supply pins with ignition on.

## CAN

| connector | pin | function |
|---|---|---|
| B54 | 4 | CAN communication line (+) |
| B54 | 3 | CAN communication line (−) |

**These two are the least verified thing on this page.** They come from the same
manual, they cannot be confirmed by resistance the way a solenoid can, and this is
a Hitachi M32R unit while most of the recent work here has been on the Denso
controller. Before connecting an adapter, confirm continuity from these pins to the
CAN pins of the diagnostic connector on the same harness, or scope them with the
vehicle running and look for differential signalling.

## What this unit is

`31711AJ675` is the 2006 B9 Tribeca TCM, superseded by `31711AJ676`. It is a
**Hitachi M32R** part, so:

- the M32R definition applies, if its calibration ID at `0x8008` matches one of the
  sixteen firmwares this project carries — read the ROM to find out
- the Denso diagnostic work in FINDINGS 81 and 83 does **not** apply to it; that is
  SH7058, with different addresses and a different protocol path
- the M32R diagnostics are separately established: 53 codes, twelve status bytes of
  eight flags each, table located per firmware
