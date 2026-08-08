# Bench rig for a 5EAT TCM

*Re-checked 2026-08-07. The addresses in the diagnostics section at the end were
read back out of the reference ROM and the disassembly before publishing.*

Notes toward running a TCM on a bench with simulated inputs, so shift behaviour,
solenoid output and logging can be exercised without a car.

> ## Check this pinout against your own unit before using it.
>
> See [TCM-PINOUT-VERIFY.md](TCM-PINOUT-VERIFY.md) — every solenoid pin has a
> resistance the manual specifies, so the numbering can be confirmed with a
> multimeter on an unplugged, unpowered unit before anything is at risk.
>
> On a Hitachi `31711AJ675` (2006 B9 Tribeca) the connector identification holds:
> **white is B54** and carries every output device, **grey is B55**.
>
> This page said the pinout came from "the 2006 Tribeca USDM service manual". The
> PDF does not support that: across 269 pages it never names a model — no Tribeca,
> no Legacy, no Outback — and identifies itself only by engine family, `H6DO`, 44
> times. That fits a Tribeca and fits a Legacy or Outback 3.0R equally.
>
> It was then checked against a real unit and **did not match**. The manual draws
> its two connectors with these top-row pin groupings:
>
>     B54    4 | 2 | 1 | 2
>     B55    4 | 3 | 2
>
> A TCM in hand has both connectors grouped **3 | 2 | 4**. Pin grouping is a
> physical property of the connector housing, so this manual describes a different
> module — and every pin number below, including the CAN lines, is wrong for that
> unit.
>
> **Before using any pin here**, compare the groupings on your own connectors with
> the diagram on PDF page 233 (`5AT(diag)-11`, TCM I/O Signal, under
> `A: ELECTRICAL SPECIFICATION`). If they do not match, this page does not describe
> your TCM and you need the wiring diagram section of an FSM for your exact
> vehicle. See [FINDINGS.md](../FINDINGS.md) §18d — the pinout circulating on the
> forum is not a substitute; it maps MCU pins to PCB programming pads on a
> different chip family.

The terminal table itself IS in that manual, contrary to what this page used to
say: section `5AT(diag)-11`, *Transmission Control Module (TCM) I/O Signal*, PDF
page 233, with the connector diagrams above it. It gives every terminal with signal
name, measuring condition, expected voltage and resistance to ground — including
the two CAN lines, which the fault-finding pages never name because they defer to
the LAN section. Earlier revisions reconstructed the pinout from fault-finding
steps because that table had not been found.

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

### The CPU pin numbers are confirmed

Forum topic 13725 post 368 - Gmguy, recovering a bricked Denso TCU, part number
30919AB600 - traced his board's programming pads to CPU pins. Those pin numbers
check out exactly against Table 1.3 of the Renesas SH7058 hardware manual
(REJ09B0046, Rev 3.00), package **FP-256H, 256-pin QFP**:

    pin   1   PD8/PULS0
    pin  55   MD1
    pin  56   FWE
    pin 164   PB15/PULS5/SCK2
    pin 165   PC0/TxD1
    pin 166   PC1/RxD1

Verified three ways in the manual - Figure 1.2, Table 1.2 and Table 1.3 - and stable
across SH7055S, SH7058S and SH7059, which share the numbering. They are **not**
valid for the BP-272 BGA package, whose designators are different, and not valid for
older SH705x parts such as the SH7050, where the same pin numbers are entirely
different functions.

### The pad numbers are a different matter

Gmguy's `P4xx` numbers are **his board's test pads, not CPU pins**, and they are not
the same as the ones in Tactrix's diagram. That diagram is titled *"ECU test pad
schematic (for reference only)"* and was taken from an '05 STi DBW **engine** ECU,
so its pad numbers describe that board:

    Tactrix engine ECU        Gmguy's Denso TCU
    P405 = FWE                P431 = FWE
    P413 = MD1                P441 = MD1
    P407 = PB15               P813 = PB15
    P411 = TxD1               P439 = TxD1
    P409 = RxD1               P808 = RxD1

The document is `shbootmode.pdf`, not `shbootrecover.pdf` - that filename 404s.
It is public at `tactrix.com/downloads/shbootmode.pdf`.

**`P431` still appears twice in post 368**, against both FWE and PD8, and one of
those is wrong. Trace the pads to the CPU pins yourself before connecting anything;
the pin numbers above are what to trace *to*.

### Entering boot mode

From Tables 4.1 and 23.1 of the manual. Normal operation is mode 3: FWE low, MD2,
MD1 and MD0 all high. Boot mode is **FWE high, MD2 high, MD1 low**, MD0 don't care -
so assert FWE and pull *only* MD1 down.

    FWE    pin 56    to +5 V
    MD1    pin 55    to ground
    PB15   pin 164   toggle at ~125 Hz, TTL
    TxD1   pin 165   to the adapter's RX
    RxD1   pin 166   to the adapter's TX

**PB15 has to keep toggling.** The external watchdog expects to see it change every
6.6 ms or it resets the part, which is why the published procedures drive it from a
555 or a microcontroller at about 125 Hz.

**PD8 is not connected by any procedure.** It appears in the schematic because the
CPU drives the FWE net through it; forcing the FWE pad high overrides it.

**Voltages, from Table 27.2.** MD0-MD2 and FWE (pins 50, 55, 56, 59) are rated to
5.8 V absolute and are 5 V-tolerant. PD8, PB15, TxD1 and RxD1 sit on PVCC2, which
Table 27.4 gives as 5.0 V ±0.5 V, so 5 V TTL is right for the serial and watchdog
lines. Note the core VCC is **3.3 V**, not 5 V - that does not constrain the mode
pins, which are separately rated, but it is worth knowing before probing anything
else. Published accounts also use a **separate 5 V supply** for FWE and the timer,
not derived from the ECU's 12 V.

### Boot mode erases the part first

This is the part that matters most. Serial boot mode **erases the entire user MAT
and the user boot MAT** before it will program anything. There is no read-out and
no partial write: entering it destroys whatever is on the unit.

So a boot-mode session is only ever a recovery path, and only when a complete,
correct ROM for that exact unit is already in hand. It is not a way to read a unit
you have not dumped.

### Nobody has reported it working on a TCU

Gmguy said he would report back once his interface arrived. He never did, and the
thread has no account of a successful hardware-level recovery on a Denso TCU. Post
368 also notes ECUflash will not open the TCU ROM.

The pin numbers and the procedure are now verified against the manufacturer's
manual. What remains unverified is that the sequence completes on this particular
board.

### The conservative order

1. **Read over CAN first, with FastECU.** `sub_tcu_denso_sh7058_can` supports read
   and write, addressing the TCU at `0x7E1`/`0x7E9` rather than the engine ECU's
   `0x7E0`/`0x7E8`. It is non-destructive, and a dump in hand is what makes anything
   afterwards recoverable.
2. Keep that dump somewhere safe. Boot mode without one is not a recovery.
3. Only then consider boot mode, and only with the pads traced to the pins above.

Post 361 reports a Denso 7058 CAN TCU reading fine but failing at the write step
with `TCU operation failed`, so a successful read does not imply a successful
write.

## What a rig would settle

**Which channel is lock-up.** This is the one the firmware cannot answer. The pin
numbers are confirmed against the 32176 Group Hardware Manual, whose pin assignment
table reads `102 P115/TO5` and `104 P117/TO7` on a 144-pin LQFP package
(FINDINGS section 44a) - so those are the right pins to probe, and the only
remaining question is which of the two the lock-up solenoid hangs off. Note it
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

---

## What the simulator now needs a bench to answer (2026-08-07)

Three things were worked out under emulation this week and each stops at the same
place: the model has no hardware, so anything the firmware decides by reading
hardware cannot be reached. All three are cheap to settle with a Tactrix OpenPort
2.0 and a CANtact Pro, and none of them needs the transmission.

### 1. Does a fault actually latch, and which code

**The blocker.** The Denso diagnostic chain is mapped end to end — 44 codes at a
per-firmware address, one 5-byte record each, both flag arrays, the routine that
sets a bit, and a debounce threshold of 1000 counts held in ROM. No simulated fault
sets anything, because the monitors gate on hardware feedback the emulator returns
zero for. So the definition can enable and disable codes and cannot say what causes
one. See FINDINGS §81.

**Why a bench answers it immediately.** Select Monitor reads arbitrary RAM. On the
reference Denso firmware:

| Address | What it holds |
|---|---|
| `0xFFFF8876` | live fault flags, one byte per group |
| `0xFFFF21D6` | confirmed fault flags, same layout |
| `0x0008624C` | the 44 codes, P-number in hex, masked `0x3FFF` |
| `0x000864A8` | 5 bytes per code: `[enable, group, mask, kind, enable]` |

A code is set when `ram[0xFFFF8876 + record.group] & record.mask`. Read fourteen
bytes from each array on a controller powered up with nothing connected and the
answer is a list, not an inference.

**Both addresses matter.** Watching only `0xFFFF21D6` produces zeros
indistinguishable from "no fault" — every write to it in the whole firmware comes
from a clear-to-zero routine, and the aggregation copies forward only what
`0xFFFF8876` already holds. That mistake cost a day under emulation.

**Note the family.** Those are Denso addresses. A 2006 Tribeca TCU is very likely
Hitachi M32R, whose diagnostics are already settled — it will not exercise this.
Read the part number first.

### 2. Is the CAN signal map right

Holding each frame byte at two values and diffing whole RAM images produced this,
and a CANtact Pro can transmit the same frames at a real controller and watch the
published parameters move:

    frame 0x231 byte 0  ->  Engine Speed              control block FFFF8E53
    frame 0x231 byte 4  ->  Accelerator Pedal Travel  control block FFFF8E47, 4B
    frame 0x410 byte 5  ->  Engine Speed              control block FFFF8E53
    frame 0x412 byte 0  ->  Accelerator Pedal Travel  control block FFFF8E47, 4B
    frame 0x491 byte 2  ->  Gear Position

0x231 and 0x410 carry the same signals into the same slots, which is what a
controller built for more than one bus layout looks like. Nothing in the method
arranges that agreement — it either survives contact with hardware or it does not.

### 3. Is gear really in the high nibble

Byte 2 of frame 0x491 held at `0x40` against `0x80` moves Gear Position from 4 to
8, so gear appears to occupy the high nibble; sending a plain 1 or 5 selects gear 0
and nothing downstream moves. Transmitting `0x10` through `0x50` and reading Gear
Position back settles it in one pass.

### The order that wastes least

1. Read the part number. M32R or Denso decides everything below.
2. Power, ground, ignition. Nothing else.
3. Read `0xFFFF8876` and `0xFFFF21D6` before touching anything. A controller wired
   to nothing has every reason to complain, and that is the cleanest fault state
   available.
4. Then transmit frames and watch parameters, which needs the controller happy
   enough to be running its normal loop.

**One warning from the emulation work.** Expecting a positive result is exactly the
condition under which something resembling one gets believed. A bench boot left
`0xFFFF8876` holding `5a a5 a5 5a...`, which decodes to twenty plausible DTCs and is
the RAM self-test pattern. If the array reads as alternating `0x5A`/`0xA5`, that is
not a fault list.
