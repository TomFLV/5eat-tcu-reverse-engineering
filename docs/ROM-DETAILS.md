# The ROMs

*Addresses re-checked 2026-08-07: `tools/validate_xml_defs.py` and
`tools/validate_denso_defs.py`, 11,023 table addresses across 25 firmwares, all
matching the image they belong to. The DTC section was corrected the same day -
it had said the stored table was never located, and the memory map above it still
listed the `0x4090` address the page itself refutes.*

Sixteen M32R 5EAT firmwares are held in [`rom/`](../rom/), all with verified
checksums and all mapped. The collection table is at the bottom.

The sections below describe **`91D1206000`** in detail — it is the reference
firmware the others were mapped against. Structure, memory map, checksum
algorithm and DTC format are shared across the family; **specific addresses are
not** and differ per firmware.

---

## File

| | |
|---|---|
| Filename | `91D1206000_5EAT.bin` |
| Size | 393,216 bytes (0x60000 — 384 KB) |
| Byte order | Big-endian |
| SHA-256 | `8a014d3e22052e76c3cca7f12dc7cbed38137c90fc300c6f7411dd59dc020382` |
| MD5 | `b0f1f9c7c65657570bc70bfdbb42cbd8` |

If your hashes don't match, you have a different dump — the table addresses in this
project won't apply.

---

## Identity block

The calibration ID sits at `0x8008`, immediately after the two checksum words:

```
00008000: 2668 221c 2668 221c 4d42 3433 314d 2020  &h".&h".MB431M
00008010: 5646 3030 3000 0000 5239 4800 0000 0000  VF000...R9H.....
00008020: 0000 255a 0008 1012 1418 91d1 2060 00f4  ..%Z........ `..
```

| Offset | Value | Meaning |
|---|---|---|
| `0x8000` / `0x8004` | `0x2668221C` | Checksum, stored twice |
| `0x8008` | `MB431M  VF000` | Calibration ID |
| `0x8018` | `R9H` | Revision / variant code |
| `0x802A` | `91 D1 20 60 00` | The ROM ID the filename comes from |

`0x802A` as the calibration ID address is independently confirmed by FastECU's
protocol configuration (`cal_id_addr=0x802a`) for this chip family.

The RomRaider definition matches on the ASCII string `MB431M` at `0x8008`, so it
will refuse to apply itself to a different firmware revision.

---

## Hardware

| | |
|---|---|
| Transmission | Subaru 5EAT (5-speed automatic) |
| TCU family | Hitachi / JECS |
| MCU | `wa12212953www` — Mitsubishi/Renesas M32R, 144-pin, 384 KB flash |
| Likely part | `M32170F3` or `M32174F3` |
| Market | JDM |
| Year | Pre-MY05 — **not confirmed**, see below |

**On the year and model:** this is genuinely not pinned down. The person who dumped
the ROM stated they could not identify it — *"I think this is pre MY05 5EAT TCU. I
have no plastic case of this TCU thus have no chance to identify OEM number."*
There was no housing or part-number label.

What can be said with evidence:

- It is **JDM** — stated in the post the ROM was attached to.
- It is **not** the 05–06 USDM TCU, which uses a different MCU (`WA12212963WWN`).
- The 5EAT launched in the JDM Legacy in 2003, and the same thread references
  `31711AJ782` as a JDM Legacy GT B 03–04MY TCU.
- Another member reports a 2004 JDM Legacy 5EAT with ROM ID `AA D1 A0 60 00` —
  structurally the same family as this one's `91 D1 20 60 00`.
- A different JDM ROM sharing this exact MCU is Hitachi part `31711AK290`.

Best inference: a **JDM Legacy (BL/BP), roughly 2003–2004**. Treat that as
inference, not fact.

---

## Provenance

The image comes from the RomRaider forum thread
[**5EAT TCM JECS ROM Image**](https://www.romraider.com/forum/viewtopic.php?f=40&t=13725)
(forum `f=40`, topic `t=13725`) — a long-running community effort on this TCU
family, spanning several hardware generations.

This ROM is the one attached to the **opening post** of that thread ("M32R based
5EAT JECS — JDM TCU ROM added"), identified in the replies as `MB431M - 91D1206000`.

**A caution when using that thread as reference:** it covers *multiple* TCU
generations — this 384 KB M32R, a 512 KB M32R (`M32176F4`), and a later Denso
SH7058-based unit used in the Tribeca and later Outback. Architecture discussion
generally transfers between them. **Specific addresses do not.** Several
interesting-looking findings in that thread turn out to be for the SH7058 chip and
use `0xFFxxxx`-style RAM addresses that don't exist in this M32R's address space at
all.

---

## Memory map

Derived from an entropy scan and confirmed against the boot code.

| Range | Contents |
|---|---|
| `0x000000`–`0x0001FF` | Vector table |
| `0x000200`–`0x003FFF` | Blank (`0xFF` fill) |
| `0x004000`–`0x005AFF` | Early/fallback boot code — port and register initialisation, *not* a DTC table, see below |
| `0x005B00`–`0x007FFF` | Blank |
| `0x008000`–`0x01D200` | **Calibration data** — all tables live here |
| `0x01D200`–`0x01FFFF` | Blank |
| `0x020000`–`0x05F600` | Main code, banked in 64 KB chunks |
| `0x05F600`–`0x05FFFF` | Blank |

Runtime memory, from the M32R chip specification and confirmed by the boot code
setting `FP = 0x804000`:

| Range | Contents |
|---|---|
| `0x800000`–`0x803FFF` | Peripheral registers |
| `0x804000`–`0x81FFFF` | RAM |

The CPU executes from address `0x0`. The reset vector branches to `0x178`, sets up
stacks at `0x806000`, checks for a `55 AA CC 33` signature near `0xFFFC`, and then
jumps to `0x20100` — the main code entry point.

---

## Checksum

A 32-bit big-endian two's-complement additive checksum, stored **twice** (identical
value) at `0x8000` and `0x8004`.

```
C = -(sum of every 32-bit BE word in the ROM, excluding both checksum slots) mod 2^32
```

Stock value: `0x2668221C`. Verified numerically — the sum excluding both slots is
`0xD997DDE4`, and `-0xD997DDE4 mod 2^32` is exactly `0x2668221C`.

Independently confirmed against FastECU's implementation for this chip family,
which computes the same thing byte-wise.

Use `tools/checksum.py` to verify or fix from the command line. The patched build in `romraider-5eat/` also implements this as a RomRaider checksum plugin and corrects it on save; **stock RomRaider cannot** —
see [ROMRAIDER-SETUP.md](ROMRAIDER-SETUP.md).

### A checksum that does *not* apply

FastECU also implements a second check for this family: the sum of all 32-bit words
from `0x8020` to end-of-file equalling a magic `0x5AA5A55A`, with a balance value
stored at `0x8020`.

**This does not hold for this ROM** — the actual sum is `0x6A7B5AA5`. Since a
factory ROM necessarily satisfies whatever checksum its own firmware enforces, that
check belongs to a different variant (likely the 512 KB `M32176F4`). It's
deliberately not implemented in `tools/checksum.py`.

It would also be actively destructive here: `0x8020` falls *inside* this ROM's
calibration ID block, so "fixing" a balance value there would corrupt real ID data.

---

## The DTC table is not at `0x4090` — a corrected error

An earlier version of this project claimed a DTC table at `0x4090` with 19
records of `[flags:u16][code:u16][data:u32]`, decoding to `P0700`, `P0704`,
`P0708` and so on. **That was wrong and has been removed.**

`0x4090` is not data. It is M32R instruction stream inside `FUN_00004000`:

```
00004080: a041 0074  a041 0078  a041 007c  6200 f000
00004090: a241 0700  6200 f000  a241 0704  6200 f000
```

`a041` and `a241` are opcodes; `0x0074`, `0x0078`, `0x007C`, `0x0700`, `0x0704`
are their displacement operands, incrementing by 4 because they address
consecutive words. It is port and register initialisation, in the region this
document already described as early boot code.

The error came from scanning for `uint16` values in `0x0700`–`0x07FF`, finding a
cluster, and assuming a P07xx code range without checking whether the bytes were
code. Two tells were missed: the "codes" incremented by exactly 4, which real SAE
lists do not, and **nothing in the ROM referenced `0x4090` as data**.

It also mattered beyond mislabelling. Each generated switch's "off" state zeroed
bytes 2–3 of a "record" — instruction operands — so toggling one would have
corrupted boot code.

Identified by **rimwall**, who pointed out the region is *"just general
initialisation of ports etc."*

### Where the real DTC handling is

DTCs are transmitted on **CAN `0x422` bytes 3–4**, encoded as a 16-bit word with
the **top 2 bits as a DTC index (0–3)** and the **remaining 14 bits as the DTC
number**; successive messages cycle through up to four active codes. Source: the
community [CAN decoding thread](https://www.romraider.com/forum/viewtopic.php?f=40&t=20850).

**This has since been done.** That encoding is a distinctive thing to search a
decompilation for, and `FUN_00032cac` builds exactly it — the index shifted into
the top two bits, the code masked with `0x3FFF`. The loop above it walks twelve
status bytes of eight fault flags each, indexing a table of 96 `uint16` codes
stored as the P-number in hex, so `0x705` is P0705. Fifty-three real codes per
firmware, and the definition ships them all, individually switchable. See
`tools/extract_dtc_table.py`, which locates the table per image rather than
assuming a fixed address — it is not at one.

The Denso family works the same way and was located later, by searching each image
for the first eight codes as a sixteen-byte key: 44 codes per firmware across all
nine, cross-checked against the instruction that indexes them.

What is still **not** established for the Denso family is which fault sets which
code. Both flag arrays, the per-code records and the routine that sets a bit have
been found, but no fault has been made to latch one under emulation. See
`FINDINGS.md` §81.

---

## The rest of the collection

Sixteen M32R 5EAT firmwares are held in [`rom/`](../rom/). All sixteen have valid
checksums. Only the first two have had their tables mapped so far.

| Cal ID | ROM ID | Size | Notes | Tables mapped |
|---|---|---|---|---|
| `MB431M` | `91D1206000` | 384K | JDM | yes |
| `MB436G` | `91FE216300` | 512K | USDM, Early 2005 Outback XT | yes |
| `MB436T` | `91D0207500` | 384K | JDM | **yes** |
| `MB436P` | `91F0217100` | 384K | USDM Outback 03 | **yes** |
| `MB4434` | `ABD1A03100` | 384K | JDM Legacy GT 2005 | **yes** |
| `MB4373` | `91D1207900` | 384K | Hitachi 31711AG589 | **yes** |
| `MB440X` | `AAD1A07100` | 384K | Hitachi 31711AJ782 | **yes** |
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT | **yes** |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 | **yes** |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM | **yes** |
| `MB562EH` | `ADE0236000` | 512K | — | **yes** |

`ACD1207000` was uploaded under the filename `AC91207000_...`; the ID here is the
one actually stored in the binary.

### Two checksum region conventions

Solving for the checksummed range across all sixteen shows the family uses two:

- **`0x60000`** — every 384 KB image, and 512 KB images carrying a 384 KB payload
  with the tail left as blank `0xFF` (`91FE216300`).
- **Whole file** — 512 KB images that genuinely populate all 512 KB: the later
  `MB558xx` / `MB562xx` calibrations.

`tools/checksum.py` detects which an image uses rather than assuming, by testing
which candidate reproduces the value the ROM already stores.

### How the mapping was done

Byte-pattern matching was tried first and rejected: the flatter tables
(`Pressure B` is all 20s, `Shift Stage D` is `6,6,6,10,10`) recur elsewhere in the
image, so multiple candidate offsets pass a structural check and only four of nine
families resolve unambiguously.

The mapping instead comes from enumerating lookup-routine call sites in each ROM's
decompiler output. Every firmware issues the same twelve table call sites in the
same address order, so roles map positionally; the gear-indexed pointer arrays are
then dereferenced to get the real table addresses.

**The offsets cannot be extrapolated.** Two traps, both caught by verification
rather than inspection:

- The pointer-array delta is *not* the gear-table delta. Using it produced
  plausible-looking wrong addresses.
- `SpeedTrimA` sits at **+142** on five firmwares where every other family in the
  same ROM is at +144.

`tools/generate_romraider_def.py` re-derives every address and checks it against
the target ROM's own embedded count field, refusing to emit anything if they
disagree.

Both of the gaps noted earlier are now closed:

- `ADE0236000` had **13** call sites rather than 12. The extra one is a second
  signal-response curve at `0x0119C4`; dropping it restores the standard twelve
  and all eight families verify.
- The DTC table is **not** at a fixed address. The later `MB5300` / `MB558xx` /
  `MB562xx` calibrations relocate it *and* carry a different code set
  (`P072C`/`P0730`/`P0734`/`P0736`/`P0760` rather than `P0700` onward). It is now
  located by scanning the `0x4000` block for the longest run of 8-byte records
  with a valid `P07xx` code field.

### Shift schedule addresses

The `gear x 2 + mode x 10` pointer array also relocates per firmware and cannot be
offset-derived. It is found by fingerprinting that index expression in each
decompiler output:

| Firmware | Array | Firmware | Array |
|---|---|---|---|
| 91D1206000 | `0x17714` | 91D1207900 | `0x17828` |
| 91FE216300 | `0x174B4` | AAD1A07100 | `0x17AAC` |
| 91D0207500 | `0x17DD4` | ABD1207000 | `0x17F9C` |
| 91F0217100 | `0x176F8` | ACD1207000 | `0x180F0` |
| ABD1A03100 | `0x17F5C` | ACD1A06000 | `0x180E8` |
| ADE0236000 | `0x180DC` | | |

All sixteen yield 8/8 real curves. The `ACD1A06000` entry independently reproduces
the `0x180E8` address rimwall stated in the forum thread.

### One archive excluded

`A3DE207100` (1 MB) is not in `rom/`. Its reset vector is `0000 0bf8` rather than
M32R's `ff00 005e`, and its initial stack pointer is `0xFFFFBFA0` — Renesas SH
territory. It is a Denso SH7055/SH7058 unit, a different chip family that shares
nothing with this work.
