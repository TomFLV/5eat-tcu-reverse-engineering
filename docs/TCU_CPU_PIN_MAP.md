# Tribeca 5EAT TCU — CPU pin ↔ firmware ↔ connector map

CPU: **Renesas M32R 32176, 144-pin package** (confirmed: P220/CTX0 = pin 144).
Method: firmware tells us **signal → port bit**; the datasheet gives **port bit → chip pin**;
a bench continuity probe ties **chip pin → B54/B55 connector pin**. The inhibitor block is
fully known on both ends, so it provides validated anchor points to start the probe from.

## CONFIRMED anchors (firmware + manual agree — use these to validate probing)
| Signal | Port.bit | Chip pin (144) | Connector | Source |
|--------|----------|----------------|-----------|--------|
| Inhibitor SW1 | P0.7 | **33** (P07/DB7) | **B55-4**  | firmware FUN_0002a240 + manual |
| Inhibitor SW2 | P0.6 | **32** (P06/DB6) | **B55-3**  | " |
| Inhibitor SW3 | P0.5 | **31** (P05/DB5) | **B55-14** | " |
| Inhibitor SW4 | P0.4 | **30** (P04/DB4) | **B55-13** | " |
| Inhibitor SW3 monitor | P4.4 | **140** (P44/CS0#) | **B55-20** | " |
| CAN0 TX (CTX0) | P22.0 | **144** (P220) | (B?, engine CAN) | firmware CAN init |
| CAN0 RX (CRX0) | P22.1 | **1** (P221, in-only) | (B?, engine CAN) | " |

→ Probe check: continuity from chip pin 33 should ring out to B55-4, pin 30 to B55-13, pin
140 to B55-20, etc. If those five match, the probe method is trusted and the rest can be mapped.

## Solenoid PWM outputs — MJT timer channels TO0–TO20 (Ports 9/10/11)
The 7 linear solenoids (750 Hz PWM) are **RESOLVED** (firmware trace, driver FUN_00024b90;
TIO(n)→TO(11+n) + FF015P/FF1620P pin-select bits agree):

| Solenoid | TIO | TO chan | Chip pin | Connector |
|----------|-----|---------|----------|-----------|
| P/L (line pressure) | TIO5 | TO16 | **86** (P93)  | B54-9 |
| H&LR/C | TIO4 | TO15 | **118** (P107) | B54-15 (LC/B?) — verify by probe |
| I/C | TIO7 | TO18 | **88** (P95)  | B54-18 |
| D/C | TIO9 | TO20 | **90** (P97)  | B54-22 |
| L/U (lockup) | TIO6 | TO17 | **87** (P94)  | B54-23 |
| F/B (front brake) | TIO8 | TO19 | **89** (P96)  | B54-24 |
| AWD | TIO2 | TO13 | **116** (P105) | B55-23 |

On/off **shift solenoids + shift-lock are NOT PWM** — static GPIO latches on P1/P2/P11 DATA
(FUN_00024af8). The MJT TOP unit (TO0–TO10) is unused for solenoid drive. Full TO pin table
for reference:

| TO chan | Port | Chip pin | | TO chan | Port | Chip pin |
|---|---|---|---|---|---|---|
| TO0 | P110 | 97  | | TO11 | P103 | 114 |
| TO1 | P111 | 98  | | TO12 | P104 | 115 |
| TO2 | P112 | 99  | | TO13 | P105 | 116 |
| TO3 | P113 | 100 | | TO14 | P106 | 117 |
| TO4 | P114 | 101 | | TO15 | P107 | 118 |
| TO5 | P115 | 102 | | TO16 | P93  | 86  |
| TO6 | P116 | 103 | | TO17 | P94  | 87  |
| TO7 | P117 | 104 | | TO18 | P95  | 88  |
| TO8 | P100 | 105 | | TO19 | P96  | 89  |
| TO9 | P101 | 106 | | TO20 | P97  | 90  |
| TO10| P102 | 107 | | | | |

Connector side (from manual, to be tied to chip pins by probe): P/L=B54-9, LC/B=B54-15,
I/C=B54-18, D/C=B54-22, L/U=B54-23, Fr/B=B54-24, AWD=B55-23.

## Analog sensor inputs — A/D0 channels AD0IN0–15 (chip pins 44–59)
| AD0IN | pin | | AD0IN | pin | | AD0IN | pin |
|---|---|---|---|---|---|---|---|
| 0 | 44 | | 6 | 50 | | 12 | 56 |
| 1 | 45 | | 7 | 51 | | 13 | 57 |
| 2 | 46 | | 8 | 52 | | 14 | 58 |
| 3 | 47 | | 9 | 53 | | 15 | 59 |
| 4 | 48 | | 10 | 54 | | (VREF0 = pin 42) |
| 5 | 49 | | 11 | 55 | | (AD0IN2/1/0 share P41/P42 region) |

**RESOLVED** (firmware trace): A/D0 data regs **AD0DT0–15 = 0x800090 + 2*n**, copied by
`FUN_00021a68` into RAM shadow **0x804C18 + 2*ch**; getter `FUN_00028f88(ch)`.

| AD0IN | pin | Sensor | Notes |
|-------|-----|--------|-------|
| 0–6 | 44–50 | 7 linear-solenoid pressure/current **feedback** | group-certain; individual solenoid binding inferred (?) |
| 7,8,10,15 | 51,52,54,59 | unused | no consumer |
| 9 | 53 | filtered, DTC range-checked input | ? |
| 11 | 55 | **ATF Temperature** | thermistor tbl 0x8080/0x81ea → SSM −50 °C |
| 12 | 56 | (no consumer found) | ? |
| 13 | 57 | **ATF Temperature 2** | second thermistor |
| 14 | 58 | **TCU supply / ignition voltage** | ignition-off monitor |

**Correction to earlier note:** 0x802A is NOT an A/D register (real A/D data is at 0x800090+).
**Brake booster pressure, engine/wheel speeds, throttle, and gear are CAN-sourced, not A/D.**

## Next steps
1. **Probe session**: buzz continuity chip-pin → B54/B55 for the confirmed anchors first (5
   inhibitor pins), then sweep the TO output pins (86-118) to the B54 solenoid pins and the
   AD0IN pins (44-59) to the sensor pins. Record chip↔connector for each.
2. **Firmware follow-ups DONE**: solenoid→TO channels resolved (`SOLENOID_TO_MAP.md`); A/D scan
   resolved (`ADC_CHANNEL_MAP.md`). Remaining open items for the probe to settle:
   - H&LR/C output = chip pin 118 vs manual's B54-15 "LC/B" label — confirm which clutch.
   - Individual binding of AD0IN0–6 feedback channels to specific solenoids (order inferred).
   - AD0IN9 and AD0IN12 purpose (one filtered/DTC input, one no-consumer).
