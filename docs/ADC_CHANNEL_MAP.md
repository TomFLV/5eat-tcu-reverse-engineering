# A/D0 Channel Map — Renesas M32R 32176 5EAT TCU (8AF0237300 / MB500NJ0)

Traced from firmware, not statistics. Sources:
- Decompile: `decompiled/8AF0237300_MB500NJ0.c`
- Annotated: `decompiled/8AF0237300_MB500NJ0.annotated.c`
- Datasheet: `the 32176 datasheet`
- SSM params: `tools/ssm_parameters.json`

## Hardware base addresses (datasheet, lines 3159–3217)

- A/D0 10-bit data registers **AD0DT0..AD0DT15 = H'0080 0090 .. H'0080 00AE** (word each, `AD0DTn = 0x800090 + 2*n`). These are the real A/D data registers.
- Scan-mode control: AD0SCM0/1 = 0x800084; single-mode AD0SIM0/1 = 0x800080.
- The prior note's `DAT_0000802a` is **not** an A/D data register (those live at 0x800090+). 0x802a is a low-RAM byte with no A/D-scan writer — see CAN note below.

## Firmware A/D data path (the anchor)

1. `FUN_00021a68` (annotated "copy_adc_results_block", line 2500): on scan-complete it copies all 16 registers into a RAM shadow — `(&DAT_00804c18)[i] = (&AD0DT0)[i]`. So **RAM shadow = 0x804c18 + 2*channel** (confirmed: AD0DT14 → 0x804c34).
2. `FUN_00028f88(ch)` (line 7562 "get_adc_channel"): returns `shadow[ch]`, the raw 10-bit value for a channel.
3. `FUN_00030000` (line 11830 "adc_accumulate_samples") and `FUN_0003020c` (line 11900 "adc_compute_averages") are the consumers that route each channel to a sensor variable.

## Channel → sensor map

| AD0IN | chip pin | AD0DTn / RAM shadow | RAM result var | sensor | SSM param | conversion | evidence |
|------:|---------:|---------------------|----------------|--------|-----------|------------|----------|
| 0 | 44 | 0x800090 / 0x804c18 | avg 0x804c5c → ctrl ch2 | Linear-solenoid pressure/current feedback (one of H&LR/C, D/C, F/B, I/C, P/L, L/U, AWD) **?** | Solenoid Valve Current/Pressure (SSM 320–334) | 2-pt linear `off − gain*raw/0x4000` | accum FUN_00030000:11860; avg FUN_0003020c:11909; ctrl FUN_...@ line 9840 |
| 1 | 45 | 0x800092 / 0x804c1a | avg 0x804c5a → ctrl ch1 | Linear-solenoid feedback **?** | Solenoid Valve Current/Pressure | 2-pt linear | accum :11856; avg :11908; ctrl @9540 |
| 2 | 46 | 0x800094 / 0x804c1c | avg 0x804c5e → ctrl ch3 | Linear-solenoid feedback **?** | " | 2-pt linear | accum :11862; ctrl @10051 |
| 3 | 47 | 0x800096 / 0x804c1e | avg 0x804c60 → ctrl ch4 | Linear-solenoid feedback **?** | " | 2-pt linear | accum :11865; ctrl @10257 |
| 4 | 48 | 0x800098 / 0x804c20 | avg 0x804c62 → ctrl ch5 | Linear-solenoid feedback **?** | " | 2-pt linear | accum :11868; ctrl @10462 |
| 5 | 49 | 0x80009a / 0x804c22 | avg 0x804c64 → ctrl ch6 | Linear-solenoid feedback **?** | " | 2-pt linear | accum :11871; ctrl @10667 |
| 6 | 50 | 0x80009c / 0x804c24 | avg 0x804c66 → ctrl ch7 | Linear-solenoid feedback **?** | " | 2-pt linear | accum :11874; ctrl @10873 |
| 7 | 51 | 0x80009e / 0x804c26 | — | **unused** (never read via getter) | — | — | no `FUN_00028f88(7)` call |
| 8 | 52 | 0x8000a0 / 0x804c28 | — | **unused** | — | — | no getter call |
| 9 | 53 | 0x8000a2 / 0x804c2a | DAT_008053ec → filt DAT_00804b3c | Slow-filtered analog input, range-checked for DTC **?** (line-pressure or reference voltage — unconfirmed) | staged to SSM buffer 0x80527f (`>>2`) | low-pass FUN_0005cf94 | read FUN_00030000:11886; filter FUN_0005c2a8:40997; range/DTC bands 0x1306e–0x13074 |
| 10 | 54 | 0x8000a4 / 0x804c2c | — | **unused** | — | — | no getter call |
| 11 | 55 | 0x8000a6 / 0x804c2e | DAT_008047fb → DAT_00804813 | **ATF Temperature** (sensor 1) | ATF Temperature (SSM 86) | `raw>>2, *2/3`, invert `0xff−x`, thermistor table @0x8080 → SSM `−50 °C` | read :11883; table lookup FUN_00045320 @35561–35570; SSM stage line 8862 |
| 12 | 56 | 0x8000a8 / 0x804c30 | _DAT_00804f8c | analog input, no downstream consumer found **?** (spare/monitor) | — | raw | read FUN_00030000:11887 (only write) |
| 13 | 57 | 0x8000aa / 0x804c32 | DAT_008047fc → DAT_00804825 | **ATF Temperature 2** (sensor 2) | ATF Temperature 2 | `raw>>2, *2/3`, invert, thermistor table @0x81ea → `−50 °C` | read :11884; table FUN_00045320 @35587–35596; SSM stage line 8869 |
| 14 | 58 | 0x8000ac / 0x804c34 | DAT_00804c68 (= AD0DT14>>2) | **TCU supply / ignition voltage** (ignition-off detector) | (Battery Voltage, likely) | `>>2` (10→8 bit) | direct reg read @2100/2920/3227; ign-off compare `< DAT_0001ce4e` @2259; SSM stage 0x805279 line 8840 |
| 15 | 59 | 0x8000ae / 0x804c36 | — | **unused** | — | — | no getter call |

## CAN-sourced (NOT A/D) — verified

- **Brake Booster Pressure** = `DAT_0000802a` (SSM index 1, staged at buffer 0x805272, line 8833). There is **no A/D-scan writer** for 0x802a–0x802e; the surrounding low-RAM bytes 0x8024–0x8029 are flash page-select pointers, and 0x802a–802e are populated as received data (CAN), not by the A/D shadow copy. The earlier note calling 0x802a an "A/D data value" is incorrect.
- Engine Speed, wheel speeds, throttle/accelerator, gear position: arrive via CAN / timer-capture inputs, not A/D0 (e.g. `DAT_008042c0` = staged throttle at SSM 6/7 is computed from `DAT_00804faa`, line 11308, not an A/D channel).

## Confidence summary

- **Strong**: ch11 = ATF Temperature, ch13 = ATF Temperature 2, ch14 = supply/ignition voltage (each traced through a named linearization/monitor path).
- **Group-strong, per-channel tentative**: ch0–ch6 = the seven linear-solenoid pressure-control feedback inputs (7 channels ↔ the 7 solenoids H&LR/C, D/C, F/B, I/C, P/L, L/U, AWD). The exact solenoid-to-channel binding is inferred, not proven — marked **?**.
- **Weak**: ch9 (filtered/range-checked analog, identity open), ch12 (written, no consumer found).
- **Unused**: ch7, ch8, ch10, ch15 (never read by the channel getter).
