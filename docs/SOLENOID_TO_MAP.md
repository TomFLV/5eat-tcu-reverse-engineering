# 5EAT TCU — Solenoid → MJT Timer Output (TO) Channel → Chip Pin Map

Firmware: `8AF0237300_MB500NJ0` (Renesas M32R 32176, 144-pin).
Decompile: `decompiled/8AF0237300_MB500NJ0.c`. Annotated: `8AF0237300_MB500NJ0.annotated.c`.

## Result: 7 linear (current-controlled) solenoids mapped

All seven 750 Hz PWM linear solenoids are driven from the MJT **TIO** unit
(input/output-related timers), channels TIO2/4/5/6/7/8/9, in the output driver
`FUN_00024b90` (annotated `update_lockup_solenoid_pwm`). Each TIO channel drives
its natural pin TO(11+n): TIO0→TO11 … TIO9→TO20. This is independently confirmed
by the pin-function-select writes in the same driver — `FF015P` bit *n* selects
TO*n* (n=0–15) and `FF1620P` bits 0–4 select TO16–TO20 — which match the natural
TIO→TO assignment exactly.

### Data-flow chain (per solenoid)
current `FUN_0004a020` → duty-scale `FUN_00033f74`/slew `FUN_00033fb4` →
working duty `DAT_008047xx` → per-channel closed-loop → stage `DAT_0080505x` →
copy fn `FUN_0002a1ec/…/2a234` → PWM var `DAT_00804ef*` → `FUN_00024b90` writes
`TIOnCT/TIOnRL0/TIOnRL1`.

| Solenoid | Current var | Working duty | Duty stage | PWM var | TIO reload reg (duty) | TO channel | Chip pin | Connector pin | Evidence (function / line) |
|---|---|---|---|---|---|---|---|---|---|
| L/U (lockup) | DAT_00804770 | DAT_00804726 | DAT_0080505a | DAT_00804ef4 | TIO6CT/RL0/RL1 (0x800360/64/66) | TO17 | P94 = pin 87 | B54-23 | SSM 0x8052aa (L#8299); duty idx0 L#13789/20544; stage L#9723→FUN_0002a1ec L#8011; PWM L#4278 (FF1620P bit1=TO17) |
| P/L (line press.) | DAT_00804774 | DAT_00804728 | DAT_0080505c | DAT_00804ef2 | TIO5CT/RL0/RL1 (0x800350/54/56) | TO16 | P93 = pin 86 | B54-9 | SSM 0x8052a9 (L#8292); duty idx1 L#13805/20545; stage L#10023→FUN_0002a1f8 L#8022; PWM L#4246 (FF1620P bit0=TO16) |
| I/C | DAT_00804776 | DAT_0080472a | DAT_0080505e | DAT_00804ef6 | TIO7CT/RL0/RL1 (0x800370/74/76) | TO18 | P95 = pin 88 | B54-18 | SSM 0x8052a8 (L#8285); duty idx2 L#13806/20546; stage L#10229→FUN_0002a204 L#8033; PWM L#4310 (FF1620P bit2=TO18) |
| F/B (Fr/B) | DAT_00804778 | DAT_0080472c | DAT_00805060 | DAT_00804ef8 | TIO8CT/RL0/RL1 (0x8003c0? →TIO8) | TO19 | P96 = pin 89 | B54-24 | SSM 0x8052a7 (L#8278); duty idx3 L#13807/20547; stage L#10434→FUN_0002a210 L#8044; PWM L#4342 (FF1620P bit3=TO19) |
| D/C | DAT_0080477a | DAT_0080472e | DAT_00805062 | DAT_00804efa | TIO9CT/RL0/RL1 (→TIO9) | TO20 | P97 = pin 90 | B54-22 | SSM 0x8052a6 (L#8271); duty idx4 L#13808/20548; stage L#10639→FUN_0002a21c L#8055; PWM L#4374 (FF1620P bit4=TO20) |
| H&LR/C | DAT_0080477c | DAT_00804730 | DAT_00805064 | DAT_00804efc | TIO4CT/RL0/RL1 (0x800340/44/46) | TO15 | P107 = pin 118 | B54-15 (LC/B) ? | SSM 0x8052a5 (L#8264, known H&LR/C); duty idx5 L#13809/20549; stage L#10845→FUN_0002a228 L#8066; PWM L#4214 (FF015P bit15=TO15) |
| AWD | DAT_0080477e | DAT_00804732 | DAT_00805066 | DAT_00804efe | TIO2CT/RL0/RL1 (0x800320/24/26) | TO13 | P105 = pin 116 | B55-23 | SSM 0x8052ab (L#8306); duty idx6 L#13810/20550; stage L#11056→FUN_0002a234 L#8077; PWM L#4182 (FF015P bit13=TO13) |

Notes:
- Current→solenoid identity is fixed by the SSM staging block `FUN_...@8255+`
  which writes currents to 0x8052a5..ab in the documented order
  (H&LR/C, D/C, F/B, I/C, P/L, L/U, AWD).
- PWM period = `DAT_00804f00` (from cal 0x1cbfc); full-on sentinel = 0x4ea; in the
  0 and full-on cases the driver switches the pin to static GPIO via P8/P9-region
  data/mode registers instead of the TIO compare, but the physical pin (TOn) is
  unchanged — the FFxxxP function-select bit is what pins the mapping down.
- H&LR/C connector: the harness list names "LC/B = B54-15"; by elimination (the
  other six labels match directly) LC/B is the H&LR/C solenoid line — marked "?"
  because the label differs from the internal name.

## On/off solenoids and shift-lock — NOT on MJT TO channels

The on/off shift solenoids and shift-lock are latched by `FUN_00024af8`
(`latch_solenoid_output_bits`) into GPIO port **data** registers, not MJT timer
outputs:
- P1DATA (0x800701, mask 0x02)
- P2DATA (0x800702, mask 0xca)
- P11DATA (0x80070b, mask 0x08 = P113)

These are driven as static GPIO, so they have no TO/PWM channel. P11DATA bit3
overlaps the P113/TO3 pin (pin 100) but is used as plain output here.
Per-bit → individual-solenoid decoding was not pursued (outside the MJT-TO scope);
mark as "?" pending a dedicated GPIO-latch trace.

The MJT TOP unit (TOP0–TOP10 → TO0–TO10) is not used for solenoid drive in this
firmware (only a dummy TOP8 = 999 appears in init); those TO channels are unused.
