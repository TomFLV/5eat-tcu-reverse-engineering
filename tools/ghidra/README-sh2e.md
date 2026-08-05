# An SH-2E processor language for Ghidra

Ghidra ships SH-1, SH-2 and SH-2A. The Denso TCUs in this project use an **SH7058S**,
whose core is **SH-2E**: the SH-2 integer instruction set plus a single-precision
FPU. Neither shipped language describes it, and both get it wrong in a way that
matters.

**SH-2 has no floating-point at all.** Every FPU constructor in `superh.sinc` sits
behind `@if defined(FPU)`, which only `sh-2a.slaspec` defines. So under SH-2 the
entire `0xF000`-`0xFFFF` opcode space has no constructor and simply fails to decode.
In one Denso image that left **165 `halt_baddata` markers** and cost about **5.6
percentage points** of instruction coverage.

**SH-2A decodes the FPU but accepts too much.** It also allows roughly twenty
SH-2A-only instructions this core cannot execute, so it will decode data or padding
as valid code with no indication anything is wrong.

## What is here

| file | purpose |
|---|---|
| `sh-2e.slaspec` | the language: SH-2 integer core, FPU on, SH-2E restrictions on |
| `superh-sh2e.patch` | gates four FPU instructions the SH7058 does not have |

## The four excluded instructions

Section 2.4.1 of the SH7058 hardware manual (REJ09B0046 Rev 3.00, page 46) lists the
floating-point instruction set in full:

    FABS FADD FCMP FDIV FLDI0 FLDI1 FLDS FLOAT FMAC FMOV FMUL FNEG FSTS FSUB FTRC

`FSQRT`, `FSCHG`, `FCNVDS` and `FCNVSD` are absent. The last two are double-precision
conversions, and this FPU is single-precision only, so they could not work even in
principle. The patch wraps those four in `@ifndef SH2E` so SH-2A keeps them and
SH-2E does not.

## Installing it

```bash
GH=$HOME/ghidra_12.1.2_PUBLIC
LANG=$GH/Ghidra/Processors/SuperH/data/languages

cp tools/ghidra/sh-2e.slaspec "$LANG/"
patch -d "$LANG" -p0 < tools/ghidra/superh-sh2e.patch
```

Then add a language entry to `$LANG/superh.ldefs`, alongside the existing SH-2 block:

```xml
  <language processor="SuperH"
            endian="big"
            size="32"
            variant="SH-2E"
            version="1.0"
            slafile="sh-2e.sla"
            processorspec="superh.pspec"
            id="SuperH:BE:32:SH-2E">
    <description>SuperH SH-2E processor 32-bit big-endian (SH-2 core with single-precision FPU)</description>
    <compiler name="default" spec="superh.cspec" id="default"/>
  </language>
```

and compile:

```bash
"$GH/support/sleigh" "$LANG/sh-2e.slaspec"
```

The compiled size is a quick sanity check that it did what it should. SH-2E has to
land between the other two: `sh-2.sla` 13,051 bytes, **`sh-2e.sla` 15,739**,
`sh-2a.sla` 28,502.

## Verifying it

Assemble `F010 F06D F3FD 000B 0009` - `FADD FR1,FR0`, `FSQRT FR0`, `FSCHG`, `RTS`,
`NOP` - into a flat binary and disassemble it under both languages. SH-2A decodes all
five. SH-2E must decode `fadd`, `rts` and `nop`, and **fail** on `fsqrt` and `fschg`.

That check is worth running rather than trusting the build, because SLEIGH's
preprocessor accepts `@if !defined(X)` silently and does nothing with it. The first
version of this patch used that form, compiled without a warning, and changed
nothing. `@ifndef X` is the form that works.

## What it is worth in practice

The FPU gap is the big one: 165 failed decodes and 5.6 points of coverage in a single
image, and every one of the nine Denso images improved by 3.5 to 5.7 points.

The four excluded instructions are a much smaller correction. Across all nine images
those bit patterns occur **twice** - a single `0xF06D` at `0x0C9F5A` in two of them,
in code territory rather than masked calibration data, so each was being decoded as a
spurious `fsqrt fr0`. Two instructions out of roughly 600,000. Worth fixing because it
is free and it is correct, not because it changes any conclusion.
