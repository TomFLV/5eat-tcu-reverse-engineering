# The ROM: `91D1206000`

Everything known about this specific binary.

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
| `0x004000`–`0x005AFF` | Early/fallback boot code — includes the DTC table at `0x4090` |
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

Use `tools/checksum.py` to verify or fix. **RomRaider cannot fix this checksum** —
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

## Diagnostic trouble codes

19 records at `0x4090`, 8 bytes each, format `[flags:u16][code:u16][data:u32]`:

```
P0700  P0704  P0708  P070C  P0710  P0714  P0720  P0724  P0728  P072C
P0730  P0734  P0745  P0745  P0746  P0748  P074C  P0750  P0754
```

All decode as real SAE/Subaru transmission codes — `P0730` is *Incorrect Gear
Ratio*, `P0745`–`P074C` are pressure control solenoid faults, `P0750`/`P0754` are
shift solenoid A. `P0745` appears twice at different addresses, presumably two
trigger conditions for one code.

The `flags` field varies per record (`0xA241`, `0xA221`, `0xA792`, `0xA702`,
`0xA022`, `0xA042`) in a way that isn't random, but the bit meanings are **not
decoded**. The code that reads this table wasn't located in the decompiled output —
it most likely lives in the K-Line SSM diagnostic path.

---

## The rest of the collection

Eleven M32R 5EAT firmwares are held in [`rom/`](../rom/). All eleven have valid
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
| `MB5300` | `ABD1207000` | 384K | 06 JDM Legacy GT | **yes** (no DTC) |
| `MB558D20` | `ACD1A06000` | 512K | JDM 2007 | **yes** (no DTC) |
| `MB558D01` | `ACD1207000` | 512K | LGT06 JDM | **yes** (no DTC) |
| `MB562EH1` | `ADE0236000` | 512K | — | not yet |

`ACD1207000` was uploaded under the filename `AC91207000_...`; the ID here is the
one actually stored in the binary.

### Two checksum region conventions

Solving for the checksummed range across all eleven shows the family uses two:

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

### Still open

`ADE0236000` has **13** table call sites rather than 12, so positional mapping is
unsafe for it; it is excluded until the extra site is identified.

`ABD1207000`, `ACD1207000` and `ACD1A06000` emit 53 tables rather than 72 — their
DTC records did not match the expected layout at `0x4090`. These are the later
calibrations and may relocate that table.

### One archive excluded

`A3DE207100` (1 MB) is not in `rom/`. Its reset vector is `0000 0bf8` rather than
M32R's `ff00 005e`, and its initial stack pointer is `0xFFFFBFA0` — Renesas SH
territory. It is a Denso SH7055/SH7058 unit, a different chip family that shares
nothing with this work.
