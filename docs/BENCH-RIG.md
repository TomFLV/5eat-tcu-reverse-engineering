# Bench rig for a 5EAT TCM

Notes toward running a TCM on a bench with simulated inputs, so shift behaviour,
solenoid output and logging can be exercised without a car.

Everything below is derived from the 2006 Tribeca USDM service manual. **The pinout is
reconstructed from the fault-finding procedures, not read off a terminal table** — the
manual has no single table for these connectors. Verify any pin against the manual
before you put power on it. The pinout that circulates on the forum is for a different
unit (see [FINDINGS.md](../FINDINGS.md) §18d).

Regenerate with `python tools/extract_tcm_pinout.py <TRANSMISSION_SECTION.txt>`.

## Connectors

Two: **B54** (A) and **B55** (B).

### Power and ground — wire these first, and nothing else

| pin | circuit |
|---|---|
| B54 7, 8, 10 | TCM power input (P0882) |
| B55 21 | Transmission ground |
| B55 1, 10 | Referenced against chassis ground in the power checks |

The manual's power checks measure 9–16 V at the supply pins with the ignition on.

### Solenoid outputs — what the TCM drives

| pin | solenoid | DTC |
|---|---|---|
| B54 24 | Shift A | P0753 |
| B54 18 | Shift B | P0758 |
| B54 17 | Shift C | P0763 |
| B54 22 | Solenoid D | P0768 |
| B54 15 | Shift E | P0773 |
| B54 9 | Pressure control A (line pressure) | P0748 |
| **B54 23** | **Torque converter clutch (lock-up)** | **P0743** |
| B55 23 | AWD transfer | P1707 |

Each needs a load or the TCM will log an open circuit. A solenoid of roughly the right
resistance is ideal; a power resistor of similar value works for signal testing.

### Sensor inputs — what has to be simulated

| pin | signal | DTC |
|---|---|---|
| B54 16, B55 16 | Input / turbine speed sensor | P0715 |
| B55 22 | Turbine speed 2 | P1710 |
| B55 7 | Output speed sensor | P0720 |
| B55 18 | Vehicle speed (rear) | P1706 |
| B54 2, 13 | ATF temperature sensor 1 | P0712 |
| B54 11 | ATF temperature sensor 2 | P1716 |

Speed sensors are pulse inputs — a signal generator or a microcontroller timer output
drives them. Temperature sensors are thermistors, so a resistor network or a digital
potentiometer stands in; the encoding is `raw − 40 °C`, confirmed in
[FINDINGS.md](../FINDINGS.md) §4.

### Range switch and the rest

| pin | signal |
|---|---|
| B54 1, 5, 14, 19, 20 | Transmission range sensor (PRNDL) |
| B55 3, 4, 13, 14, 20, 21 | Transmission range sensor (PRNDL) |
| B55 11 | Back-up light |
| B55 15 | Reverse inhibit (P0801) |
| B55 19 | Starter disable (P0817) |

The range sensor is a set of discrete switched lines — a rotary switch or a bank of
relays reproduces it. The TCM will not shift out of a fail-safe state without a valid
range.

## Before wiring anything: dump the ROM

The single most valuable thing this unit can produce needs no rig at all.

The 2006 Tribeca manual quotes gear ratios of **3.841, 2.352, 1.529, 1.000, 0.839**.
Every one of the 25 firmwares this project holds — including both later Tribecas —
carries **3.540, 2.264, 1.471, 1.000, 0.834** instead. So the early Tribeca's
calibration is one nobody here has, and reading it would add a *variant* rather than
another member of a family already covered.

Check by searching the dump for five consecutive values decoding to the 3.841 set:
`uint16 / 1024` if the unit is M32R, IEEE-754 float if Denso. In the images here that
table sits at `0x0844C` on M32R and between `0xB9234` and `0xCE658` on Denso.

See [FINDINGS.md](../FINDINGS.md) §39.

## Reading and writing on the bench

### It is not BDM

BDM is Motorola and Freescale terminology. Neither controller here has it. The
Hitachi M32R and the Denso SH705x each have a **serial boot mode**: hold the mode
pins in a particular state at reset and the part comes up running a small ROM
loader that accepts a program over a UART, which then does the flash work.

### What the tooling actually supports

FastECU's `modules/` on the development branch, which is where the TCU work lives:

| unit | CAN | K-line | boot mode |
|---|---|---|---|
| Hitachi M32R TCU | yes | yes | **yes** — `modules/bootmode/flash_ecu_subaru_unisia_jecs_m32r_bootmode.cpp` |
| Denso SH705x TCU | yes | — | **no module exists** |

So for the Denso there is a CAN path and nothing else. The only boot-mode module
in the tree is the Unisia JECS M32R one, and it is an *ECU* module. There is a
`kernels/ssmk_tcu_can_sh7058.bin`, which is the CAN route again.

### The pads are real, and someone has traced them

Forum topic 13725 post 368 — Gmguy, recovering a bricked Denso TCU, part number
30919AB600. He identified the PCB programming pads and confirmed they match
Tactrix's `shbootrecover` diagram, which is the standard SH boot mode wiring:

    P441 – MD1   – MCU pin 55    (100 Ω)
    P431 – FWE   – MCU pin 56    (100 Ω)
    P431 – PD8   – MCU pin 1     (1 kΩ)      <- see below
    P813 – PB15  – MCU pin 164   (0 Ω)
    P808 – RxD1  – MCU pin 166   (0 Ω)
    P439 – TxD1  – MCU pin 165   (1 kΩ)

Board photographs are linked from posts 368 and 373.

**`P431` is listed twice**, against both FWE and PD8. One of them is wrong, and
it is not recoverable from the post. Ring both out against the MCU pins before
connecting anything — tying FWE to the wrong pad is how a working unit becomes a
second brick. The MCU pin numbers likewise want checking against the datasheet
for the exact package on your board.

### Nobody has reported it working

Gmguy said he would report back once his interface parts arrived. He never did,
and the thread has no other account of a successful hardware-level recovery on a
Denso TCU. Post 368 also notes **ECUflash will not open the TCU ROM**, so its
recovery path is not usable as-is.

Treat this as a documented starting point, not a procedure. What is established:
the pads exist, they are boot mode pads, and they correspond to a published
diagram. What is not established: that the sequence completes on this unit.

### The conservative order

1. **Read over CAN first, with FastECU.** It is supported, it is non-destructive,
   and a dump in hand is what makes everything else recoverable.
2. Keep that dump. A known-good image of the same part number is what turns a
   brick into an afternoon.
3. Only then consider boot mode, and only with the pads verified by continuity.

Post 361 reports a Denso 7058 CAN TCU reading fine but failing at the write step
with `TCU operation failed`, so a successful read does not imply a successful
write.

## What a rig would settle

**Which channel is lock-up.** This is the one the firmware cannot answer. Note it
is an **M32R** question: `0x804EB2` and `0x804EB6` are M32R addresses and section
29 works from the 32176 manual, so it is settled on an M32R unit, not a Denso one.
The Select Monitor cannot answer it either - what it reports for lock-up is derived
from the commanded value rather than read back from the timer output (section 40c). `0x804EB2`
drives TIO5 on package pin 102 and `0x804EB6` drives TIO7 on pin 104; their software
drivers are exact mirrors (§29). On a bench, continuity or a scope from those MCU pins
to **B54 pin 23** identifies it directly — no logging or driving required.

**What the shift condition byte means.** §33 found the schedule index is
`condition × 2 + group × 10` but not what each condition value represents. Holding
inputs steady and varying one at a time — ATF temperature especially — while watching
which schedule applies would map it.

**The line pressure discrepancy.** §34 found the Select Monitor reports P/L up to
2520 kPa where the tables hold 1370. With a controlled input and a measured solenoid
duty, the relationship between table value and reported pressure can be established
rather than guessed.

**Whether a modified ROM is accepted.** The most safety-relevant untested claim in this
project is the checksum. A bench TCM that starts and communicates after a reflash
proves it, and risks nothing.

## Order of work

1. Identify the unit from its label — M32R or Denso decides the protocol and which
   definition applies.
2. Power and ground only. Confirm it draws current sensibly and does not get hot.
3. Establish communication before anything else is wired. If it answers on the
   diagnostic line, the rest can be debugged; if it does not, nothing else matters.
4. Add the range switch, so it leaves fail-safe.
5. Add speed and temperature simulation.
6. Load the solenoid outputs and measure them.

Steps 1–3 need almost no hardware and answer whether the unit is alive.
