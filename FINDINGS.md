# 5EAT TCU ROM — Reverse Engineering Findings

**Living document.** Updated on every discovery so nothing gets lost across sessions.
Target: Subaru 5EAT (5-speed automatic transmission) TCU, Mitsubishi/Renesas M32R CPU.
ROM file: `91D1206000_5EAT.bin`, 393,216 bytes (0x60000), big-endian.

> ### Read this as a log, not as a specification
>
> This file is kept in chronological order, including the parts that turned out to
> be wrong. Some findings here were later disproved, and the retraction is written
> where it happened rather than by deleting the original — otherwise there is no
> record of *why* a wrong answer looked right, which is the part that stops it
> being made twice.
>
> **Later sections supersede earlier ones.** In particular:
>
> - §13a corrects several earlier findings, including a "DTC table" at `0x4090`
>   that is actually instruction stream (port initialisation), and a "solenoid PWM
>   bank" at `0x8047EA` that is really the Interrupt Controller at `0x8007EA` — the
>   address was inflated by the frame-pointer bug described in §14a.
> - §14c supersedes §12d: pressure units *are* established, in kPa. §12d was right
>   that they cannot be derived from the ROM alone, which is precisely why the
>   answer came from the factory service manual instead.
>
> For what is currently true and verified, read [README.md](README.md) and
> [docs/TECHNICAL-NOTES.md](docs/TECHNICAL-NOTES.md) — those are maintained as
> statements of the present state. This file is the trail that got there.

---

## 1. Toolchain setup (WSL Ubuntu)

- radare2 was tried and **rejected** — confirmed via `rasm2 -L` (installed radare2 6.0.7 in WSL) that it has no M32R architecture plugin at all. Closest relatives (ARC, V850, NDS32) do not decode M32R.
- **Ghidra 12.1.2** is set up in WSL at `~/ghidra_12.1.2_PUBLIC`, using OpenJDK 21 (`openjdk-21-jdk-headless`, installed via apt).
- M32R support added via the community module [ripnet/ghidra-m32r](https://github.com/ripnet/ghidra-m32r), cloned to `~/ghidra-m32r`, installed into `~/ghidra_12.1.2_PUBLIC/Ghidra/Processors/M32R/data/languages/`.
  - Its precompiled `.sla` was stale for Ghidra 12.1.2 (matches a known GitHub issue, [NationalSecurityAgency/ghidra#5935](https://github.com/NationalSecurityAgency/ghidra/issues/5935): "Can't read language spec"). Fixed by recompiling from the `.slaspec` source with this Ghidra's own `support/sleigh` compiler.
  - `m32r.pspec` also failed schema validation: its 6 `<memory_block>` elements (under `<default_memory_blocks>`) predate a Ghidra schema change requiring one of `bit_mapped_address` / `byte_mapped_address` / `initialized`. Fixed by adding `initialized="false"` to each.
  - `Module.manifest` must be an **empty file** (not text) — Ghidra's other bundled processors all ship it empty; a non-empty one throws a manifest parse error (non-fatal, but fix it anyway).
  - Language ID to use for import is **not** the usual `Proc:endian:size:variant` convention — the ldefs sets it explicitly to `m32r:2:default`.
- The module's `m32r.pspec` `<default_memory_blocks>` documents this M32R variant's real memory map (useful reference, independent of our ROM):
  - `CS0` 0x100000, len 0x100000 (chip-select region 0 — likely where flash/ROM is mapped)
  - `CS1` 0x200000, len 0x200000
  - `CS2` 0x400000, len 0x200000
  - `CS3` 0x600000, len 0x200000
  - `SFR` 0x800000, len 0x4000 (special function / peripheral registers)
  - `RAM` 0x804000, len 0x1C000
- ROM imported into a headless Ghidra project, raw `BinaryLoader`, language `m32r:2:default`.
  - **First attempt used base address 0x100000 (CS0, per the pspec's `default_memory_blocks`) — this was WRONG.** Only 5 bogus "functions" turned up and nothing meaningful cross-referenced.
  - **Corrected: base address 0x000000 is right.** This TCU runs directly from on-chip flash at address 0, not through the CS0 external chip-select window (CS0-CS3 in the pspec are for *external* memory this single-chip MCU likely doesn't use). Confirmed conclusively — see §2a below. Current working project uses base 0x0 (in `~/ghidra_project2`).
  - Headless post-scripts are the practical way to drive this (no GUI in WSL for this session): write a `.java` `GhidraScript` subclass into `~/my_scripts/`, run with
    `analyzeHeadless <project_dir> <project_name> -process 5eat.bin -noanalysis -scriptPath ~/my_scripts -postScript YourScript.java`.
    Gotcha: run this from the WSL home directory (`cd ~` first) — if invoked from a path under `/mnt/c/...`, Ghidra's script loader tries to resolve the bare script name relative to cwd first and fails even though `-scriptPath` is correct.

### Reproducing the environment
```bash
wsl -u root -e bash -c "apt-get install -y radare2 openjdk-21-jdk-headless git unzip"
cd ~
curl -L -o ghidra.zip https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.2_build/ghidra_12.1.2_PUBLIC_20260605.zip
unzip -q ghidra.zip
git clone --depth 1 https://github.com/ripnet/ghidra-m32r.git
GHIDRA=~/ghidra_12.1.2_PUBLIC
mkdir -p $GHIDRA/Ghidra/Processors/M32R/data/languages
cp ghidra-m32r/data/languages/m32r.{cspec,ldefs,pspec,sinc,slaspec} $GHIDRA/Ghidra/Processors/M32R/data/languages/
: > $GHIDRA/Ghidra/Processors/M32R/Module.manifest
# fix pspec schema (add initialized="false" to the 6 memory_block elements), then:
$GHIDRA/support/sleigh -x $GHIDRA/Ghidra/Processors/M32R/data/languages/m32r.slaspec
# import:
cp "/mnt/c/Users/Tom/OneDrive/Desktop/5eat tcu reverse engineering/91D1206000_5EAT.bin" ~/5eat.bin
$GHIDRA/support/analyzeHeadless ~/ghidra_project 5eatProj -import ~/5eat.bin \
    -processor 'm32r:2:default' -loader BinaryLoader -loader-baseAddr 0x100000
```

---

## 2. ROM layout (from entropy/fill-byte mapping)

Blank/unprogrammed flash reads as `0xFF` fill. Mapped with a 256-byte-block entropy scan:

| Range | Content |
|---|---|
| 0x000000 – 0x0001FF | Vector table (reset/interrupt vectors; dense pointer-like entries) |
| 0x000200 – 0x003FFF | Blank (0xFF fill) |
| 0x004000 – 0x005AFF | Small code/data block |
| 0x005B00 – 0x007FFF | Blank |
| **0x008000 – ~0x01D200** | **Calibration data region** — dense, many small tables interleaved with short 0xFF gaps (this is where all tables found so far live) |
| 0x01D200 – 0x01FFFF | Blank |
| 0x020000 – 0x05F600 | Main code region, banked in ~0x10000 (64KB) chunks, each bank's code padded to its boundary with 0xFF |
| 0x05F600 – 0x05FFFF | Blank tail |

---

## 2a. Reset vector / boot code (disassembled, base address 0) — CONFIRMED

Forcing disassembly at address 0x0 in Ghidra (M32R language) produces clean, coherent code — strong proof the CPU really executes from address 0 and that our understanding of the ROM layout is correct:

```
00000000  BRA 0x00000178
00000178  LD24 R0,#0x806000
0000017c  MVTC R0,SPU              ; set user stack pointer = 0x806000
00000180  LD24 R0,#0x806000
00000184  MVTC R0,SPI              ; set interrupt stack pointer = 0x806000
00000188  SETH FP,#0x81
0000018c  ADD3 FP,fp(0x804000)     ; FP = 0x804000  <-- exactly the pspec's RAM base! confirms chip variant match
00000190  LD24 R1,#0xfffc
00000194  LDUB R2,@R1
00000198  LD24 R3,#0x55
0000019c  BNE R2,R3,0x000001d8
... (repeats, checking bytes for 0x55, 0xAA, 0xCC, 0x33 in sequence — looks like a magic-number / signature scan, possibly checksum-related or a "valid ROM" signature check)
000001c4  LD24 R0,#0x5ffff         ; 0x5FFFF = last valid byte offset of this exact ROM (0x60000 bytes) — loop bound
000001c8  BNE R1,R0,0x000001d0
000001cc  BRA 0x00020100           ; <-- jumps into the main code region we mapped via entropy scan (starts ~0x020000)
000001d0  LD24 R0,#0xfffd
000001d4  ADD R1,R0
000001d6  BRA 0x00000194           ; loop
000001d8  BRA 0x00004000           ; fallback path -> the small early code block we found at 0x004000-0x005AFF
```

Confirms, independently of the earlier Python entropy scan:
- RAM really is at 0x804000 (matches community pspec exactly) — good sign the M32R variant/pspec is a real match for this chip, not just "close enough."
- The main code region genuinely starts around 0x020000 (reset handler branches to 0x00020100 after passing the signature check).
- The small block at 0x004000 is a real, reachable code path (a fallback/diagnostic boot route, taken if the 0x55/0xAA/0xCC/0x33 signature check at 0xFFFC fails).
- There's a boot-time signature/checksum check reading 4 bytes starting near the end of a 64KB page (0xFFFC) against fixed magic bytes `55 AA CC 33`, with a loop that walks forward through the whole 0x60000-byte ROM looking for it (bound `0x5FFFF`). Worth understanding fully before doing any byte-level modification of the ROM — this looks like exactly the kind of check that would reject a modified image if broken.

**Not yet done:** only traced this single boot path so far (~30 instructions). Need to disassemble at the real target 0x00020100 (not 0x00020000 — tried that address by mistake first and got garbage, since it's mid-instruction-stream/misaligned, not a real code start) and get full auto-analysis running from a proper entry point so Ghidra's control-flow-following disassembler covers the whole code region and can resolve real cross-references to the calibration tables in §3.

---

## 3. Calibration table encoding (confirmed format)

Tables are **big-endian 16-bit** values, laid out as:

```
[count N (u16 BE)] [N-point axis, usually monotonic, often arithmetic step] [N-point data row (u16 BE)]
```

- Axis termination: last axis value is frequently a sentinel meaning "max/and above" — seen as `0xFFFF`, `0xFF00`, or (for byte-range axes) `0x00FF` rather than a continuation of the step.
- Multiple tables commonly **share an identical axis**, stored back-to-back — strongly suggests a family of related curves (e.g. one per gear, or per mode) reusing the same breakpoints.
- Confirmed real (not coincidental) via **32-bit BE absolute pointers elsewhere in the ROM that literally point at these table headers** — cross-referenced 307 pattern-matched candidate tables against every 4-byte-aligned scan of the file; 38 have at least one genuine pointer reference pointing at the exact file offset of their header. Those 38 are high-confidence real tables (see catalog below); the rest of the 307 are unconfirmed pattern matches (likely a mix of real tables not pointer-referenced this way, and coincidental monotonic runs in code).

### Table catalog (high-confidence, pointer-cross-referenced)

Full machine-generated catalog of all 307 pattern candidates (with pointer refs annotated where found) is at `table_catalog.txt` in the project root (a fixed artefact now — the script that produced it was removed, §15f).

Key confirmed families:

1. **0x01040A, 0x01043C, 0x01046E, 0x0104A0, 0x0104D2** — 5 tables, identical 11-pt axis `0, 5120, 10240, ..., 51200` (+0xFFFF sentinel = 12 entries). Data rows are monotonically increasing curves that saturate at the top end (classic pressure/torque-vs-RPM shape). If axis is raw units at a /12.8 scale, maps cleanly to **0–4000 RPM in 400 RPM steps** — plausible turbine/engine speed axis. **5 tables = plausibly one per forward gear** (5EAT has 5 forward gears).

2. **0x010D1A / 30 / 46 / 5C / 72** and **0x010D9C / DB2 / DC8 / DDE / DF4** — two groups of 5 tables, axis `2048, 4096, 8192, 12288, 16384`, **flat data = 20 everywhere**. Referenced by a pointer array at 0x010D88–0x010E1C. Flat data suggests a constant (e.g. a fixed timer/threshold) that's nominally indexed by load/RPM but doesn't actually vary — possibly a placeholder or a genuinely flat calibration.

3. **0x0112D0 / E6 / FC / 011312 / 011328** — 5 tables, same 2048–16384 axis, data `[6,6,6,10,10]` (step function). Referenced by **two separate, back-to-back, identical 5-pointer arrays** at 0x011340–0x011364 — i.e. two different logical contexts (e.g. two modes, or upshift/downshift) both indexing the *same* 5 gear-keyed tables.

4. **0x011468, 0x0114A8, 0x0114D2, 0x0114FC, 0x011526, 0x011550, 0x011590, 0x0115D0, 0x0115FA, 0x011624, 0x01164E, 0x011678** — 12 tables, shared 10-pt axis `5120..51200` (+0xFF00 sentinel = same RPM-like axis family as #1, offset start). Data rows are increasing curves of varying steepness (gentle to steep) — classic family of **pressure/duty-cycle-vs-RPM curves, one per gear or throttle bin**.

5. **0x0116BA, 0x0116E8, 0x011716, 0x011744, 0x011772** — 5 tables, 11-pt axis `0..46080` (+0xFFFF). First table's data is all zero (likely a default/disabled case); the other 4 have data that starts positive then goes **negative** (two's-complement small values, e.g. 65147 = -389) and levels off — shape typical of a **shift-shock / torque-phase correction curve vs RPM**.

6. Two **ATF-temperature-shaped axes** found (not yet pointer-cross-referenced):
   - 0x015B00-ish: 10-pt axis `0, 20, 40, ..., 180` (terminated 0xFFFF), followed by a decreasing data row (positive then negative-ish, e.g. 615, -288, -738, -888…) — plausible oil-temp-based correction.
   - 0x01549E / 0x0154C0: 14-pt axis `10, 20, ..., 140` terminated `0x00FF`, repeated back-to-back at least twice — very plausibly **ATF temperature in °C**, a classic axis for line-pressure/TCC-engagement/shift-timing-vs-temp compensation tables.

7. **0x041682** — 3-pt candidate, weak/likely coincidental (not a real table; too short and non-arithmetic to trust without more context).

### Open questions / hypotheses to verify against Ghidra disassembly
- Confirm the "5 tables = 5 gears" hypothesis by finding the code that indexes family #1/#3/#4/#5 and seeing what selects the index (gear number register/variable).
- Determine the real engineering units and scale factors for the RPM-like axis (raw/12.8 → RPM guess) and the two temperature-like axes (°C guess) by finding the code that reads raw sensor values and compares/scales them against these breakpoints.
- Find the base-address mapping actually used at runtime — we assumed CS0 (0x100000) for the Ghidra import per the pspec's memory map; need to confirm this against reset-vector targets / branch targets once disassembly is reviewed.
- Full catalog only checked pointer refs as literal 4-byte absolute addresses; there may be more real tables referenced via 16-bit relative/indexed addressing that the pointer scan missed.

---

## 4. Scripts (in `tools/`, this project folder — persistent)

These four were removed once their findings were recorded here; they are described
for the record, not as tooling you can run (§15f).

- `scan_rom.py` — 256-byte-block Shannon entropy map, used to find the calibration-data region and code/blank boundaries.
- `find_tables.py` — arithmetic-progression scanner (BE16, configurable width/sign/endian) that first surfaced the repeated-axis pattern.
- `extract_tables.py` — full `[count][axis][data]` pattern extractor + 32-bit pointer cross-referencer; wrote the catalog.
- `table_catalog.txt` (project root) — full machine-generated dump of all 307 pattern candidates, with pointer-reference annotations where found. Not regenerable now that the script is gone.

---

## 5. Ghidra project state (as of this session)

- Working project: `~/ghidra_project2/5eatProj` inside the **WSL Ubuntu filesystem** (not under the Windows project folder — WSL's own ext4 disk, persists across Windows/WSL reboots as long as the `Ubuntu` WSL distro isn't uninstalled, but isn't backed up by anything outside WSL). If this matters, worth exporting/copying out at some point — **not done yet**.
- Seeded entry points at 0x0 (reset vector), 0x4000 (fallback boot path), 0x20100 (main code region entry, per §2a). Ran full default headless analysis (`analyzeAll`).
- Result: **132 functions found**, ~9,300 instructions / ~25KB disassembled. Control flow was followed from 0x20100 out to as far as 0x0005EC4C — a good chunk of the ~0x020000–0x05F600 code region, but far from all of it (that region is ~256KB; we've covered roughly a tenth by byte count, though function *count* coverage may be better since not every byte in a code region is itself an instruction).
- Ghidra auto-typed several calibration-table pointer-array entries as address/pointer data on its own (e.g. `addr 00010d1a`, `addr 000112d0`) — nice independent confirmation of the pointer-table hypothesis from §3, done purely from Ghidra's own data-reference analyzer, no manual pointing-out needed.
- The vector-table region (0x0–0x1FF) resolved to named functions straight from the community pspec's built-in M32R exception-vector symbol table: `RI` (reset), `SBI` (software break), `RIE` (reserved instruction exception), `AE` (address exception), `TRAP0`–`TRAP15`, `EI` (external interrupt?), `FPE` (floating point exception?) — all standard M32R exception vectors, another good confirmation this pspec really matches our chip.
- **Not yet found:** any disassembled instruction that references the calibration-table pointer arrays (0x010D88, 0x011340, 0x011468, etc.) themselves. Checked explicitly — zero code xrefs to those array addresses so far. This means the code that walks these tables either (a) hasn't been reached yet by control-flow analysis from our 3 seed points — most likely, since we've only covered a fraction of the code region — or (b) is reached only from an interrupt vector we haven't individually traced (the `EI`/hardware-interrupt vectors, e.g. a periodic timer tick, would be the natural place for TCU shift-control logic to live).

### Practical note for next session
Scripts used this session (Ghidra `GhidraScript` Java subclasses) are now in `tools/` in this project folder: `DisasmTest.java` (force-disassemble at a given address, used to validate base address 0), `SeedAnalyze.java` (seed entry points + run full auto-analysis), `XrefDump.java` (list functions + report references to a list of target addresses). To use them again, copy into WSL (`~/my_scripts/`) and run from the WSL home directory:
```bash
cp "/mnt/c/Users/Tom/OneDrive/Desktop/5eat tcu reverse engineering/tools/XrefDump.java" ~/my_scripts/
cd ~ && ~/ghidra_12.1.2_PUBLIC/support/analyzeHeadless ~/ghidra_project2 5eatProj -process 5eat.bin -noanalysis -scriptPath ~/my_scripts -postScript XrefDump.java
```

---

## 5a. Calibration ID block (found — needed for RomRaider/EcuFlash ROM identification)

At the very start of the calibration data region:
- **0x008008**: ASCII `"MB431M  VF000"` + null padding — looks like a Subaru part-number-style calibration ID.
- **0x008018**: ASCII `"R9H"` + null padding — a shorter secondary code (revision/variant?).
- **0x00802A**: raw bytes `91 D1 20 60 00` — this is literally where the ROM filename (`91D1206000`) comes from; standard practice is naming a dumped ROM after its internal ID bytes, confirmed here.

This block is exactly what a RomRaider (or EcuFlash) `<romid>` identification section needs — no further digging required for that piece specifically.

## 5b. Checksum algorithm — SOLVED

**32-bit big-endian two's-complement additive checksum**, stored redundantly (identical value written twice) at file offsets **0x008000** and **0x008004** (value in the stock ROM: `0x2668221C`).

Algorithm: treat the ROM as an array of 32-bit big-endian words. `C = -(sum of every other dword in the ROM) mod 2^32`. Verified algebraically and numerically — not a coincidence match:
- Sum of the entire 393,216-byte file as BE32 words (including both checksum slots) ≡ `C` (mod 2^32) — because storing `C` twice means the whole-file sum works out to `S + 2C = -C + 2C = C`, where `S` is the sum of everything else.
- Directly confirmed: `S` (sum excluding both checksum slots) = `0xD997DDE4`; `-S mod 2^32` = `0x2668221C` = the stored value, exactly.

Reusable implementation in **`tools/checksum.py`**: `compute_checksum(data)`, `verify_checksum(data)` (currently `True` for the stock ROM), `fix_checksum(data)` (returns a copy with both slots corrected — use this after any table edit before flashing).

This was found on the first serious attempt by brute-force trying standard checksum forms (byte sum, word sum, dword sum, XOR, ones'-complement, CRC-16/32, each over several candidate ranges) against the repeated 4-byte value that sits immediately before the calibration-ID block — the search script `find_checksum.py` has since been removed (§15f), though the method is worth repeating if this ever needs redoing (e.g. if a different ROM revision stores things differently).

**Not yet known:** whether this is the *only* checksum. The boot-time `55 AA CC 33` signature check (§2a) at 0xFFFC is separate and still unexplained — worth revisiting once table semantics work resumes, in case it's a second, independent integrity check (e.g. a smaller checksum over just the boot block) rather than a pure magic-number/presence check.

---

## 6. What's needed for a RomRaider (or EcuFlash-style) tuning definition file

1. **ROM identification** — done, see §5a above (ID string + byte match at 0x008008 / 0x00802A).
2. **Checksum algorithm** (`<checksummodule>` in RomRaider) — **SOLVED, see §5b**. 32-bit BE two's-complement additive checksum, redundantly stored at 0x008000/0x008004, `C = -(sum of all other dwords) mod 2^32`. Reusable implementation in `tools/checksum.py`.
3. **Table definitions** (address, dimensions, storage type/endianness, scaling formula, units) — **partially done**. Encoding is known (BE uint16, `[count][axis][data]`), ~38 high-confidence table locations are cataloged (§3), but real-world units/scale factors for the axes (RPM? °C? kPa?) are still unconfirmed — needs the code-tracing work in progress (see Next Steps below).
4. **Tool choice caveat** — RomRaider's live tuning/logging is built around Subaru *engine* ECUs over the SSM protocol; TCU support there is thin-to-nonexistent. The Subaru TCU-tuning community more commonly uses EcuFlash-style `.xdf` definitions instead. The underlying pieces (ID match, checksum, address/scaling table defs) transfer either way — only the file format/wrapper changes — but worth confirming RomRaider can actually open/edit a TCU bin before committing to writing its XML format specifically, rather than an `.xdf`.

---

## 8. Interrupt vectors fully mapped, and the table-lookup code FOUND (major breakthrough)

### 8a. Real vector structure (corrected — the earlier "31 tiny stubs" read in an old draft of this doc was wrong)

Three levels, not a flat table:
1. **Hardware vectors** (file 0x0–0x83): `RI`/`SBI`/`RIE`/`AE` at 0x0/0x10/0x20/0x30 (16 bytes apart), `TRAP0`–`TRAP15` at 0x40–0x7C (4 bytes apart), `EI` at 0x80 — all standard M32R exception vectors (names come straight from the community pspec), each a literal `BRA` instruction.
2. **A pointer-to-pointer table** at file 0x94–0x10C: 31 entries, each holding the address of one slot in level 3 (`0x00020000, 0x00020004, ..., 0x00020078` — i.e. entry *i* just equals `0x20000 + 4i`, pointing at itself/level 3's array).
3. **The real interrupt handler address table**, at file 0x20000–0x2007C (31 × 4-byte slots): almost all slots hold the same default value `0x00020100` (the main code entry point — i.e. "unhandled/unused interrupt, fall through to main"), except **four slots with genuinely distinct handler addresses**: `0x000245BC`, `0x00020A14` (appears twice), `0x00026748`, `0x00025828` (appears twice).

Seeding Ghidra with just those 4 real addresses (instead of guessing every slot was individually meaningful code) took disassembly from **167 functions / 25KB** to **1,090 functions / 234KB** (~90% of the ~256KB code region) in one pass — this was the actual key that had been missing, not a full brute-force sweep of every vector slot.

### 8b. Calibration-table pointer arrays: real code references found

With that much more of the ROM disassembled, Ghidra now shows genuine code (not just data-to-data) cross-references into two of the pointer arrays from §3:

- **0x010D88** (the "flat data=20" gear-table family) ← referenced from **0x0005CD5A**, inside `FUN_0005CD04`.
- **0x011340** (the "data=[6,6,6,10,10]" gear-table family) ← referenced from **0x0005D53E**, inside `FUN_0005D4E8`.

Both functions are structurally identical (same code, different table addresses/output variables) — clearly a repeated pattern used for multiple similar lookups. Decoded logic (registers as Ghidra named them, M32R calling convention: R0/R1/R2... are args/scratch):

1. Preamble clamps some input value into the full signed 16-bit range `[-0x8000, 0x7FFF]` and holds it in R5 — this is the interpolation **X value** (a sensor/computed quantity, still unidentified in engineering units).
2. A function parameter (masked to its low byte) is compared to `1`. This looks like a **mode selector** — value `1` picks pointer-array base `0x10D88`, anything else picks base `0x10E0C` (the *other* half of the same 10-table family from §3 item 2). Two-way branch only seen so far; there may be more cases elsewhere.
3. A **global byte at RAM address `0x0080885A`** is read, multiplied by 4, and added to the chosen pointer-array base to select one of the **5 tables** in that family. Given each family has exactly 5 tables and a 5EAT has 5 forward gears, **`0x0080885A` is a very strong candidate for "current gear number."**
4. The resolved table pointer + the clamped X value (R5) are passed to a **shared lookup subroutine at `0x0004515C`**.
5. The subroutine's return value is stored via `STH` (store halfword) into a fixed RAM location — `0x00808B40` for the 0x10D88/0x10E0C call site, `0x00808B3C` for the 0x11340/... call site. These are presumably named ECU RAM variables (outputs of these lookups) — not yet identified.

### 8c. The table-lookup subroutine at 0x0004515C — CONFIRMS the table format from §3 by disassembly, not just pattern-matching

214-byte function. Fully decoded:

```
R1 = pointer to table, R0 = X value to look up, R2 = flag byte (0 in the calls found so far)
if flag == 0:
    count = *(uint16*)R1      ; matches our [count] header field exactly
    R1 += 2                    ; advance past the count, R1 now = start of axis array
axis_ptr = R1
if X < axis[0]:                ; below first breakpoint
    return data[0]              ; (clamp-low case, roughly — exact edge handling not fully traced)
else:
    loop i = 0 .. count-1:
        if X < axis[i]: break
    if X == axis[i]:            ; exact breakpoint hit
        return data[i]
    else:                        ; genuine interpolation between i-1 and i
        x0 = axis[i-1];  x1 = axis[i]
        y0 = data[i-1];  y1 = data[i]
        result = y0 + (X - x0) * (y1 - y0) / (x1 - x0)      ; <-- standard linear interpolation, confirmed via MUL then DIV
result = clamp(result, 0, 0xFFFF)    ; final output forced into unsigned 16-bit range regardless of internal signed math
return result
```

This is a completely standard, textbook 1D lookup-table interpolation routine. It independently confirms, from real disassembled code rather than inference:
- The `[count][axis][data]` layout guessed from Python pattern-matching (§3) is exactly right.
- Axis and data entries are read with **signed 16-bit loads** (`LDH`) during the interpolation math (even though the initial count/first-axis check uses unsigned `LDUH`) — consistent with families like #5 (§3) whose data looked like small negative numbers in two's complement.
- Tables are genuinely **interpolated**, not stepped/nearest-neighbor — meaning edited values will blend smoothly at runtime, same as a typical fuel/ignition map. Good news for tuning.
- A near-identical second function immediately follows at **0x00045234** — not yet traced, likely a variant (2D lookup building on this, or a slightly different signed/unsigned handling). Worth checking.

---

## 8d. `0x0080885A` CONFIRMED as current/commanded gear number, and the gear state-machine function found

`0x0080885A` is read from over 100 distinct locations scattered across nearly the whole code region (consistent with "current gear" being something almost every shift/pressure/diagnostic routine needs), but written from exactly **one** function: **`FUN_0004CA24`** (0x0004CA24, 612 bytes). That function is the gear determination / commit state machine, and it's rich enough to be worth documenting in full:

- Four-then-two "shift request" evaluation blocks (0x4CA2C–0x4CB9C) each call a helper subroutine at **`0x00045070`** with a pointer into a small run of consecutive RAM/pointer-table structures (`0x00808A00, 0x00808A08, 0x00808A0C, 0x00808A10, 0x00808A24, 0x00808A28`), compare the result against a byte at `0x00808879`, and adjust two working "candidate gear" counters — `0x0080885C` (upshift-related) and `0x0080885D` (downshift-related) — each clamped to **[0, 4]** (5 values — matches 5 forward gears exactly).
- Two distinct **fail-safe / limp-mode paths**:
  - One (0x4CBE4–0x4CBF0), gated by bit-tests on flag bytes at `0x008094E0`/`0x008094EC`, forces the gear to whatever's stored at **`0x0080886E`** (a configurable/default fail-safe gear value).
  - Another (0x4CBFE–0x4CC0C), gated by a bit-test on `0x008094E8`, hard-codes gear **= 2** (0-indexed, i.e. "3rd" if gears are 0=1st..4=5th) — a classic automatic-transmission "limp home" gear.
- Normal path (0x4CC10–0x4CC44): commits the working candidate (`0x0080885C`) into `0x0080885A` when it differs from the current value, clearing two solenoid-status bits (`0x00809634`, `0x00809638`) as part of the change.

Working RAM map (addresses confirmed by this function; meanings inferred from usage, not yet from any string/label):

| Address | Inferred meaning |
|---|---|
| 0x0080885A | current/commanded gear, raw range 0–4 (5 forward gears) |
| 0x0080885B | secondary/previous gear snapshot (written alongside 0x5A in a couple of spots) |
| 0x0080885C | upshift working candidate / target gear |
| 0x0080885D | downshift working candidate |
| 0x0080885E | a mode/state flag (checked, not obviously written, in this function) |
| 0x0080886E | fail-safe default gear value |
| 0x00808879 | threshold/debounce compare value used by the four shift-request checks |
| 0x008094E0, 0x008094E4, 0x008094E8, 0x008094EC | bit-flag bytes, likely solenoid/pressure-switch feedback status |
| 0x00809634, 0x00809638 | solenoid command bits, cleared on committed gear change |

This is strong, disassembly-confirmed proof of the "5 tables = 5 gears" hypothesis from §3/§8b: `0x0080885A` is exactly the value used (×4) to index into the 5-entry pointer arrays at 0x010D88/0x010E0C/0x011340/etc.

**Not yet traced:** the helper at `0x00045070` (called 6× in this function — likely a generic "read+hysteresis-compare" utility, worth understanding since it gates every shift decision), and the readers of the output variable `0x00808B40` (found in `FUN_0004A4AC`, `FUN_0005C568`, `FUN_0005CC70`) — tracing those should reveal what physical quantity the gear-indexed lookup tables actually produce (pressure? duty cycle?).

## 8e. Helper `0x00045070` and the table-lookup output readers — a SECOND table format found

Traced both remaining open threads from §8d:

**`0x00045070`** is itself another table-lookup function, but over a **different table layout** than §8c's `[count][axis][data]` format: here the table is an array of **8-byte (4×uint16) records**, terminated by a `0xFFFF` sentinel, with the search loop stepping 8 bytes at a time comparing the lookup key against one field of each record before landing on a matching/bracketing record and doing arithmetic across that record's 4 fields (same multiply-then-divide interpolation shape as §8c, just operating on 4 fields-in-one-record instead of two parallel arrays). Likely purpose, given where it's called from (`FUN_0004CA24`, the shift state machine, passing pointers like `0x00808A00`, `0x00808A08`, etc.): a **shift-point table with built-in hysteresis** — i.e. each record probably encodes something like (breakpoint, value-if-rising, value-if-falling, next-breakpoint) so upshift and downshift trigger points can differ, which is standard practice for AT shift-point calibration. Not fully confirmed — worth revisiting with the decompiler (see §9 below) rather than more manual register tracing.

**Readers of `0x00808B40`** (output of the §8b gear-indexed lookup):
- `FUN_0004A4AC` (~0x4A530): conditionally uses `0x00808B40` OR a constant table at **file offset `0x00010106`** (a previously uncatalogued table address — worth adding to the pointer-scan catalog) depending on a bit-flag test, then takes an absolute value of a related quantity — consistent with a delta/rate-of-change calculation.
- `FUN_0005C568` (~0x5C738): compares `0x00808B40` against another RAM variable `0x00809312`, feeding a chain of bit-mask tests (testing individual bits 0x2/0x4/0x8/0x20 of some status byte — plausible PRNDL-range or shift-mode bitfield decode) that select between several candidate values.
- `FUN_0005CC70` (~0x5CCAC): compares `0x00808B40` against an **adjacent** variable `0x00808B44`, producing a tri-state (0/1/2, i.e. below/equal/above) classification result.

**Readers of `0x00808B3C`** (output of the 0x11340 family lookup) show the same tri-state comparison pattern (`FUN_0005D468`, comparing against `0x008092D2`), right next to an identical comparison of a *different* pair (`0x00808B34` vs `0x00808F3A`).

**Working hypothesis** (not yet confirmed): these gear-indexed table outputs represent **target/commanded values** (e.g. target line pressure, target duty cycle) that get compared against **live measured/feedback values** stored in the paired RAM variables, producing simple below/equal/above results for closed-loop control or fault detection — rather than being sent straight to an actuator. This would explain the consistent "table output vs. nearby RAM variable, three-way branch" pattern seen at every reader site.

---

## 10. Decompiler unlocked — full program decompiled, shift-schedule architecture found

**Tooling upgrade:** Ghidra's decompiler (`DecompInterface`, headless-scriptable) works cleanly on this M32R program and produces readable, C-like pseudocode — far faster and more reliable than manually tracing raw disassembly register-by-register (manual tracing had already produced at least one wrong read earlier in this session, corrected in §8b). **This should be the default approach for all further code tracing.** Whole program (all 1,090 functions) decompiled in one pass and saved as **`full_decompile.c`** in the project root (1.1MB, ~46,500 lines) — grep this file first for any RAM address or function before doing anything manually. Script: `tools/DecompileAll.java`; single-function version: `tools/Decompile.java`.

Re-decompiling §8b/8c/8d's functions immediately paid off — cleaner and more precise than the hand-traced version:

```c
void FUN_0005cd04(char param_1)   // was: reference site into table family 0x010D88/0x010E0C
{
  int iVar1 = (uint)DAT_008087d0 * 0x100 - (uint)DAT_008092ce;   // X value for the lookup
  if (iVar1 < 0x8000) { if (iVar1 < -0x8000) iVar1 = -0x8000; } else { iVar1 = 0x7fff; }  // clamp to s16
  if (param_1 == '\x01')
      DAT_00808b40 = FUN_0004515c(iVar1, (&PTR_PTR_00010d88)[DAT_0080885a], 0);   // gear-indexed pointer array, confirmed
  else
      DAT_00808b40 = FUN_0004515c(iVar1, (&PTR_PTR_00010e0c)[DAT_0080885a], 0);
}
```

`FUN_00045070` (called 6× from the gear state machine, §8d) decompiles to a **second, distinct table format** — 8-byte records (4×uint16), terminated by `0xFFFF`, with a mode parameter selecting between "rising" and "falling" interpolation branches using the same 4 fields (essentially the same multiply/divide interpolation as §8c, just laid out differently and computed twice with swapped sign for hysteresis). This is a **shift-schedule table format with built-in upshift/downshift hysteresis** — exactly what a real AT shift schedule needs.

### Shift-schedule table locations found, and confirmed gear-dependent selection

Grepping `full_decompile.c` for the RAM pointer variables `FUN_00045070` reads from (`DAT_00808A00/A08/A0C/A10/A24/A28`) led to their initializers:

- Boot-init routine (`FUN_0003d7ec`) sets default pointers to four ROM addresses: **`0x00015CA8`, `0x00017698`, `0x00019324`, `0x0001A2FE`** — most likely the four shift-schedule tables for a 5-speed transmission's four gear-pair boundaries (1↔2, 2↔3, 3↔4, 4↔5), each already containing rising/falling hysteresis per §8e/FUN_00045070's format.
- A separate function (`FUN_00044a6c`) commits "staging" pointer variables into the live ones every cycle:
  ```c
  void FUN_00044a6c(void) {
    DAT_00808a08 = DAT_008089f8;  DAT_00808a10 = DAT_008089fc;
    DAT_00808a00 = DAT_008089f0;  DAT_00808a0c = DAT_008089f4;
    DAT_00808a28 = DAT_00808a20;  DAT_00808a24 = DAT_00808a1c;
  }
  ```
- The staging variables themselves are set **conditionally on `DAT_0080885A` (current gear)** — e.g. (from around line 27515 of `full_decompile.c`):
  ```c
  if (DAT_0080885a == '\0') {           // gear == 0 (1st)
      DAT_008089f0 = 0x176fe; DAT_008089f4 = 0x176fe; DAT_00808a1c = 0x176fe;
  } else if (DAT_0080885a == '\x01') {  // gear == 1 (2nd)
      DAT_008089f8 = &DAT_00017698; DAT_008089fc = &DAT_00017698; DAT_00808a20 = &DAT_00017698;
  }
  ```
  This is **direct, disassembly-confirmed proof that which shift-schedule table gets evaluated depends on the currently-selected gear** — the core architecture of a real AT shift-schedule system, exactly as expected.
- There's a cluster of closely-spaced related small table/pointer addresses around this same area worth treating as one region for future cataloging: `0x000176A2`, `0x000176FE`, `0x00017708`, `0x00017714` (itself a pointer array, indexed by `DAT_00808b94`), `0x00017718` (another pointer array).

### Other new addresses surfaced (not yet fully characterized)

- **`0x00010106`** — read by `FUN_0004A4AC` as an alternate source to the `0x00808B40` table-lookup output (§8e), selected by a bit-flag test.
- **`0x000116A4`** — a pointer array (indexed by a byte, `& 0xff`) used by **`FUN_00045234`** (the "sibling" function noted but not traced in §8c) — this result feeds directly into `DAT_008092CE`, one of the two operands that make up the X value for the §8b gear-table lookups. So that X value isn't a raw sensor reading — it's itself derived from another table lookup. Worth fully decompiling `FUN_00045234` next.
- Several ROM scalar-constant addresses referenced during boot init (`FUN_0003d7ec`), likely single calibration constants rather than 2D tables: `0x0001286A`/`0x0001286B`, `0x00011850`/`0x00011851`, `0x0001549A`/`0x0001549B`, `0x0001553E`, `0x0001C3CF`, `0x0001B99C`, `0x00010840`, `0x00010126`. Also **`0x00010000`** itself is read as a bit-flag configuration byte at boot (`DAT_00010000 & 2`, `& 4`) selecting between fixed constants — likely a model/variant option byte very close to the ROM's very start.

---

## 11a. `FUN_00045234` traced — X-value computation chain for the gear tables (partially resolved)

`FUN_00045234` decompiles to almost exactly the same algorithm as the confirmed interpolation routine `FUN_0004515C` (§8c/§10) — **count-prefixed axis+data lookup with linear interpolation** — except its breakpoint parameter is `ushort` (unsigned) instead of `short` (signed). It's the unsigned counterpart of the same table format, not a different format.

Its real caller (`FUN_0005ba7c`, found by grepping `full_decompile.c` for `DAT_008092ce = `) reveals the computation chain feeding the §8b/§8c gear-table lookups:

```c
void FUN_0005ba7c(void) {
  if (<fault condition on DAT_00809640 / DAT_0080811c>) {
      uVar6 = 0; uVar3 = 0;
  } else {
      uVar6 = (uint)DAT_0080886e;   // used here as a general gear-like index, not just the failsafe target from §8d
      uVar3 = (uint)DAT_00808ae6;   // raw input value
  }
  // select one of three gear-indexed table-pointer arrays based on more flags:
  puVar5 = (DAT_008094c8/DAT_008087db condition) ?
             ((DAT_0080889f == 3 || DAT_0080889f == 0) ? (&PTR_DAT_0001157c)[uVar6] : (&PTR_DAT_000115bc)[uVar6])
           : (&PTR_DAT_00011494)[uVar6];

  DAT_008092cc = FUN_00045234(uVar3, puVar5, 0);
  DAT_008092ce = FUN_00045234(uVar3, (&PTR_DAT_000116a4)[uVar6 & 0xff], 0);   // <-- this feeds §8b's X value
}
```

So the full chain for the §8b gear-table interpolation input is:
```
X = DAT_008087D0 * 256  -  table_lookup( table_116A4[gear_index], DAT_00808AE6 )
```
i.e. **not a raw sensor reading** — it's a coarse reference value (`DAT_008087D0`, scaled ×256) minus a gear-indexed table lookup evaluated at another RAM value (`DAT_00808AE6`). Consistent with a **measured-vs-expected comparison** (e.g. actual vs. calculated turbine speed for slip detection), but not yet proven — would need tracing where `DAT_008087D0` and `DAT_00808AE6` themselves get set (likely in sensor-capture/interrupt code, not yet located).

Also notable: **`DAT_0080886E` is used here as a general gear-like index** (`uVar6`), not exclusively as the "fail-safe default gear" role found in §8d's `FUN_0004CA24`. Its exact meaning is now less certain — could be a second/reference gear value (e.g. a gear-position-sensor reading distinct from the commanded gear `0x0080885A`) that only *doubles* as the fail-safe target. Worth resolving before assuming it's purely a constant.

**New table/pointer-array addresses found this pass** (all in the same 0x0110xx-0x0118xx neighborhood as previously cataloged tables, reinforcing that this whole range is one dense calibration block): `0x0001157C`, `0x000115BC`, `0x00011494`, `0x000116A4`, `0x00011836`, `0x00011898`, `0x000118DA`.

---

## 11b. Full signal chain traced back to a CAN bus message — major architectural discovery

Continued tracing `DAT_008087D0` and `DAT_00808AE6` (the two operands of the §11a X-value) back to their origins turned up two more generic building blocks and, at the very end of the chain, a CAN bus receive/parse routine.

**Generic exponential smoothing filter** (a third reusable building block, alongside the interpolation and hysteresis-lookup functions from §8c/§8e):
```c
int FUN_0005c8a0(int target, int current, int gain) {   // unsigned variant, clamps to [0, 0xFFFF]
    delta = gain * (target - current);
    if (0 < delta && delta < 256) delta = 256;      // minimum-step floor, avoids stalling from truncation
    if (-256 < delta && delta < 0) delta = -256;
    result = (current*256 + delta) / 256;            // = current + delta/256
    return clamp(result, 0, 0xFFFF);
}
```
`FUN_0005c8fc` is the same thing clamped to signed 16-bit `[-0x8000, 0x7FFF]` instead. Classic first-order IIR low-pass filter with a calibratable gain (read from ROM, e.g. `0x1137C` for the specific instance traced).

**Full chain for the §11a X-value inputs:**
```
DAT_00808AE6 = smoothing_filter(target = DAT_008082BC << 3, current = DAT_00808AE6, gain = DAT_0001137C)   // FUN_0005c8a0
DAT_008082BC = min(DAT_00808F6A, DAT_0001C2A8)                                                              // ceiling clamp, ROM constant
DAT_00808F6A = DAT_008087AE                                                                                  // (with a reset-to-ROM-constant 0x1C3C0 path)
DAT_008087AE = CONCAT(byte@DAT_00808C86[i], byte@DAT_00808C85[i])   where i = (mailbox_index)*8
```

That last assignment is inside a **CAN bus message receive/dispatch routine** (`FUN_00028e88`): a loop over 16 message "mailboxes" (`uVar7 = 0..15`), each with a stored CAN ID (`DAT_00808C50[i]`) and an 8-byte payload buffer (`DAT_00808C80..DAT_00808C87`, stride 8 per mailbox). `DAT_008087AE` gets set from **payload bytes 5:6 of the message with CAN ID `0x410`**.

**Full list of CAN IDs this routine handles** (from every `sVar2 == 0x...` comparison in the same function): **`0x410, 0x411, 0x412, 0x511, 0x512, 0x513, 0x514, 0x515, 0x520, 0x600, 0x740, 0x741`**. The `0x740`/`0x741` pair is a strong candidate for a manufacturer-specific **UDS-style diagnostic request/response pair** (that convention — odd/even adjacent IDs for tester-request vs. ECU-response — is extremely common on OBD/UDS-capable modules); the `0x410`-`0x412` and `0x511`-`0x520` clusters are most likely powertrain broadcast messages from other modules (engine ECU, etc.) that the TCU listens to.

**Revised understanding of the system architecture:** the gear-pressure/duty tables (§8b/§3) aren't driven by a locally-sampled sensor — their X-axis input originates from a **CAN-received value (ID 0x410, bytes 5:6)**, ceiling-clamped against a calibration constant, smoothed through a calibratable first-order filter, then run through a second gear-indexed table lookup (§11a) before being combined with a separate discrete/filtered reference (`DAT_008087D0`) to form the final interpolation input. This is a materially different (and more specific) picture than "raw RPM sensor" — it's most likely a **cross-module signal (e.g. engine RPM or a torque-related value) delivered over the vehicle CAN bus**, matching how transmission control actually works on CAN-networked (rather than standalone-sensor) Subaru platforms.

**Not yet confirmed:** what physical quantity CAN ID `0x410` bytes 5:6 actually represents — would need either an external reference (a Subaru CAN ID/DBC listing for this platform/year) or further correlation (e.g. checking whether other bytes of the same message get used elsewhere in ways that hint at units). This is likely a case where static reverse engineering alone has diminishing returns without an external reference or live bus logging.

**`0x740`/`0x741` handlers checked** — `0x740` captures all 8 payload bytes into fixed globals plus a status-bit test, consistent with staging an incoming diagnostic-tester request. `0x741`'s handler is more complex than a simple UDS response capture: it uses a low-nibble index (1-7) and a high-nibble page-select bit to write into one of two paired buffer sets (`0x808D94`/`0x808DB0` vs `0x808DA2`/`0x808DBE`) — doesn't cleanly match the standard single-frame UDS PCI-byte pattern, so the "0x740/0x741 = diagnostic req/resp" read is still just a strong guess, not confirmed. Not pursued further this session.

---

## 11c. First RomRaider definition file written: `5eat_tcu_91D1206000_romraider_def.xml`

Built and validated against a real RomRaider schema example (fetched from the `Merp/SubaruDefs` GitHub repo — RomRaider's own EditorXMLReferenceGuide wiki page 403's WebFetch, so used an actual definition file instead). Confirmed the real `<romid>`/`<table>` attribute names (`internalidaddress`, `internalidstring`, `storageaddress`, the `type="X Axis"`/`"Z Axis"` sub-table pattern, `base="..."` inheritance) rather than guessing the schema.

**Important discovery about RomRaider's checksum handling**: its "Checksum Fix" mechanism (seen in the real example as a `<table type="Switch" name="Checksum Fix">`) is backed by **hardcoded Java logic keyed to known, supported ECU/memmodel families** — it is not a generic formula defined in the XML. Since this M32R-based TCU isn't a family RomRaider knows, **RomRaider cannot correctly fix this ROM's checksum on save**. Deliberately did *not* include a Checksum Fix table (would be actively misleading — could look like it works and silently corrupt the checksum). Documented prominently in the XML file's own header comment: any `.bin` exported from RomRaider must have its checksum corrected afterward with `tools/checksum.py`'s `fix_checksum()` before flashing anywhere.

**Scope of what's included**: the 4 most confidently-understood, disassembly-confirmed gear-indexed table families (20 tables total — 5 gears × 4 families), all with addresses cross-validated programmatically (every table's embedded count field checked against its declared `sizex`, every Z-axis address checked against its X-axis address + size — see `tools/validate_xml_defs.py`, 40/40 checks passed):
- **Family A "Pressure Curve A"** (0x01040A/0x01043C/0x01046E/0x0104A0/0x0104D2) — 12-point RPM-like axis, real saturating curves. The most "interesting" tunable family so far.
- **Family B "Threshold B"** (0x010D1A/30/46/5C/72, pointer array 0x010D88) — flat data=20.
- **Family C "Threshold C"** (0x010D9C/DB2/DC8/DDE/DF4, pointer array 0x010E0C) — flat data=20, the "other mode" counterpart to B.
- **Family D "Step Table D"** (0x0112D0/E6/FC/011312/011328, pointer arrays 0x011340 & 0x011354) — step function data.

All 20 use **"Raw" scaling** (`expression="x"`) since real engineering units aren't confirmed yet (see §11a/§11b) — still fully editable/tunable, just not yet labeled with real-world units.

**Deliberately excluded from this first pass** (to keep the file trustworthy rather than padded): the 12-table family at 0x011468+ (real tables, but indexing/selection logic not yet confirmed via decompiler — only found via the Python pointer-cross-reference scan) and the four shift-schedule tables (0x15CA8/0x17698/0x19324/0x1A2FE — different record-based format, would need a different RomRaider table representation since RomRaider doesn't natively support the hysteresis dual-branch format found in §8e).

**RomRaider usage caveat** (also in the XML's header comment): RomRaider's live tuning/logging/flashing is built for Subaru engine ECUs on the SSM protocol over a completely different CPU family (Renesas SH). This M32R-based TCU almost certainly can't be read/written live through RomRaider's normal vehicle connection — this definition is for opening an already-dumped `.bin` file to view/edit tables, not for connecting to the car through RomRaider.

---

## 11d. RomRaider actually tested — bugs found and fixed, definition file expanded to 30 tables

Testing the §11c definition file in the user's actual installed RomRaider (1.0.0 DEC01 2023, `C:\Program Files (x86)\RomRaider`) surfaced real problems, found by decompiling the installed `RomRaider.jar` (via CFR, see `~/romraider_inspect` in WSL) rather than guessing:

- **First "no tables" cause**: not a bug at all — `C:\Users\Tom\Downloads\91D1206000_5EAT.bin` turned out to be a *folder* (from extracting a downloaded zip with a same-named file inside), not the file. RomRaider was opening an empty/nonexistent path. Fixed by pointing at the project folder's copy instead.
- **Second "no tables" cause (the real bug)**: decompiling `TableScaleUnmarshaller.unmarshallTable` proved RomRaider's 2D tables have **no "Z Axis" child element** — that was invented, not real schema. For a 2D table, RomRaider only recognizes an `X Axis` (or `Y Axis`) child for the breakpoint axis; **the data address belongs on the outer `<table>` element itself**. Our original 20 tables all had `storageaddress` on the (ignored) fake "Z Axis" child, leaving the real table's address unset — silently skipped, no error logged anywhere (confirmed by also enabling RomRaider's DEBUG-level logging, see below, and seeing nothing). Fixed by moving `storageaddress` onto the outer `<table type="2D">` element and dropping the fake child entirely.
- **Enabled DEBUG logging** for future troubleshooting: RomRaider's log level is set in `C:\Program Files (x86)\RomRaider\lib\log4j.properties` (`log4j.rootLogger=info,...` → changed to `debug,...`, done via a UAC-elevated PowerShell edit since the install directory isn't user-writable). Log file: `C:\Users\Tom\.RomRaider\rr_system.log`.

**Definition file is now generated, not hand-written**: `tools/generate_romraider_def.py` builds `5eat_tcu_91D1206000_romraider_def.xml` from a `FAMILIES` list (each entry: category, name template, list of ROM header addresses, axis label, description template) plus a `romid` block, computing every axis/data address programmatically from the ROM's own embedded `[count]` fields. Regenerate with `python tools/generate_romraider_def.py` rather than hand-editing the XML — avoids the copy-paste address bugs found earlier. `tools/validate_xml_defs.py` re-verifies every generated address against the ROM afterward (60 checks across 30 tables, all passing).

**Table families expanded from 4 to 6 (20 → 30 tables)**, with corrected understanding from further decompilation:

- **Correction to Family A** (now "Speed Trim A", 0x01040A group): earlier writeup incorrectly attributed the same X-value formula as the B/C/D families. Its *actual* confirmed caller (`DAT_00808b16 = FUN_00045234(DAT_00808ae6, (&PTR_DAT_00010504)[DAT_0080886e], 0)`, found by grepping `full_decompile.c`) shows it's indexed by **`DAT_0080886E`** (not `0x0080885A`/current-gear) and takes **`DAT_00808AE6` directly** (the CAN-derived value from §11b) as its X input — not a difference formula.
- **`DAT_0080886E` identified as a second, distinct gear-like index variable**, separate in role from `DAT_0080885A` (current commanded gear from the §8d state machine) — used to index several table families rather than being the shift-decision gear itself.
- **Two new families found and fully traced** via a pointer-array cross-reference scan of the `0x011468`-`0x011678` region (the family flagged as "indexing not yet confirmed" in earlier notes — now resolved):
  - **"Slip Detection Threshold"** (5 tables, 0x114A8/114D2/114FC/11526/11550, pointer array 0x01157C): output `DAT_008092CC`, repeatedly compared `<` against `DAT_008087D0*256` elsewhere in the code — reads like a fault/slip detection threshold curve.
  - **"Reference Speed Baseline"** (5 tables, 0x115D0/115FA/11624/1164E/11678, pointer array 0x0116A4): output `DAT_008092CE`, which is exactly the value already known (§11a) to feed the X-formula for the Slip Comp Pressure B/C and Shift Stage D families (`X = DAT_008087D0*256 - DAT_008092CE`). This ties the whole system together — confirmed, not assumed.
  - (Two single flat/fallback curves, ROM 0x011468 and 0x011590, also found in the same region — used instead of the above under certain flag conditions, each referenced identically from all 5 index slots. Not added as separate tables since they don't vary by index; noted in descriptions instead.)
- **Romid block enriched**: added `<caseid>R9H</caseid>`, combined `<ecuid>` string listing all three ID fragments found (`91D1206000 (MB431M / VF000 / R9H)`), and added `<year>`/`<market>` (both "Unknown" — genuinely don't know, but RomRaider's logger-side code checks these are non-empty before it'll treat a ROM as fully identified, so empty was worse than an honest "Unknown"). Also added `<version>91D1206000_5EAT (MB431M / VF000 / R9H)</version>` and put the same string in `<model>` — the firmware's own on-chip identity, made visible in RomRaider's UI so a human can tell at a glance which exact firmware a loaded definition/ROM pair is (the `internalidaddress`/`internalidstring` match already prevents RomRaider from silently applying this definition to a *different* firmware revision — this just surfaces that same identity to the person looking at the screen).

---

## 11e. SSM/logging investigated, paused mid-way at user's request — resume notes

User asked about adding Subaru SSM (Select Monitor) live-logging support and provided https://www.alcyone.org.uk/ssm/protocol.html. Findings so far (decompiling `RomRaider.jar`'s protocol classes, not guessing):

- RomRaider ships **two different SSM protocol drivers**: `com.romraider.io.protocol.ssm.iso9141` (classic K-line, what engine ECU logging normally uses) and **`com.romraider.io.protocol.ssm.iso15765` (SSM-over-CAN)**. Given this TCU is confirmed CAN-based (§11b), the CAN variant is the relevant one.
- Decompiled `SSMProtocol` (iso15765 variant): `ADDRESS_SIZE = 3` (full 3-byte/24-bit addresses — unlike classic SSM's 2-byte addressing), `READ_ADDRESS_COMMAND = 0xA8` (matches the community protocol doc exactly), default connection speed 500,000 baud (standard CAN bit rate). Read/write *memory* (block) commands explicitly throw `UnsupportedProtocolException` "not supported on CAN" — only read/write *address* (single address per command, but multiple addresses batchable per request) works over this transport.
- Requests are built as `[module.getTester(), command_byte, address_bytes...]` — i.e. RomRaider's `Module` abstraction carries a configurable "tester" (device) byte per module, which is exactly the mechanism the community docs describe (0x78 engine, **0x45 transmission**, 0x89 A/C, 0x92 4WS) — meaning targeting the TCU specifically (not the engine ECU) may genuinely be configurable, not hardcoded to engine-only. **Was about to decompile `com.romraider.logger.ecu.definition.Module` to confirm how tester bytes and per-module CAN request/response IDs are actually defined (XML or hardcoded) when the user asked to pause.**
- Because the CAN variant uses full 3-byte addresses, our already-confirmed RAM addresses (all within 0x800000-0x820000, comfortably fitting 3 bytes) could plausibly be used **as-is**, with no address-space translation needed — unlike classic 2-byte SSM (used by engine ECUs), where our addresses wouldn't fit at all. This also lines up suggestively with the `0x740`/`0x741` CAN IDs already found in this TCU's own message table (§11b) — a very plausible diagnostic req/resp pair, though not yet confirmed to *be* SSM-over-CAN specifically.
- **Nothing has been added to any definition file for this yet** — deliberately paused before writing anything, since (a) the `Module` class (tester-byte/CAN-ID configuration) wasn't checked yet, and (b) none of this can be verified without live communication against a real vehicle/TCU, which requires hardware access. If resumed: finish checking `Module`, then (if it looks buildable) produce a clearly-labeled **candidate/untested** logger.xml so the user can actually try it against real hardware — not to be treated as confirmed working.

---

## 11f. Real DTC table found in the ROM (P07xx transmission codes)

User's insight: since Subaru transmission DTCs are all standardized in the public `P07xx` range (P0730 = incorrect gear ratio, P0745/0746/0748 = TCC pressure solenoid, P0750/0754 = shift solenoid A, etc.), a literal DTC table should show up as a cluster of 16-bit values in that numeric range. Scanned the whole ROM for exactly that — found one immediately, not noise:

**Table starts at file offset `0x004090`.** Each record is 8 bytes: `[flags: uint16][DTC code: uint16][data: 4 bytes]`. First ~19 records decode cleanly to real, recognizable Subaru transmission DTCs:

```
0x004090  flags=0xA241  code=P0700  data=6200f000
0x004098  flags=0xA241  code=P0704  data=6200f000
0x0040A0  flags=0xA241  code=P0708  data=6200f000
0x0040A8  flags=0xA241  code=P070C  data=6200f000
0x0040B0  flags=0xA241  code=P0710  data=6200f000
0x0040B8  flags=0xA221  code=P0714  data=6200f000
0x0040C0  flags=0xA241  code=P0720  data=623af000
0x0040C8  flags=0xA241  code=P0724  data=d2c02800
0x0040D0  flags=0xA241  code=P0728  data=6200f000
0x0040D8  flags=0xA241  code=P072C  data=6200f000
0x0040E0  flags=0xA241  code=P0730  data=6200f000    <- "Incorrect Gear Ratio", the classic AT DTC
0x0040E8  flags=0xA221  code=P0734  data=1281f000
0x0040F0  flags=0xA792  code=P0745  data=600107e0
0x0040F8  flags=0xA702  code=P0745  data=600ff000    <- P0745 appears twice (two conditions/thresholds for one code?)
0x004100  flags=0xA022  code=P0746  data=d0c03000
0x004108  flags=0xA042  code=P0748  data=6000f000
0x004110  flags=0xA042  code=P074C  data=6000f000
0x004118  flags=0xA042  code=P0750  data=6000f000
0x004120  flags=0xA022  code=P0754  data=603ff000
```
(record walk starts drifting into unrelated data around 0x004128/P0202 onward — that's past the real table's end, not more DTCs; exact end boundary not yet pinned down precisely.)

Most records share the same `data` (`62 00 f0 00` or similar defaults); a handful have unique data (P0720, P0724, P0734, both P0745s, P0746, P0754) — consistent with most DTCs using a shared default threshold/debounce config and a few having their own calibrated values. **The `flags` field is the most promising candidate for the "enable/disable" bit the user wants** — varies per record (0xA241, 0xA221, 0xA792, 0xA702, 0xA022, 0xA042) in a way that doesn't look random, but the actual bit-meaning (which bit = enable, which = MIL request, which = severity) hasn't been decoded yet — that's the next concrete step before this can become an editable RomRaider table.

---

## 11g. Community reverse-engineering thread found — major independent validation (and important scope caveat)

User found and had me pull the **entire RomRaider forum thread "5EAT TCM JECS ROM Image"** (`romraider.com/forum/viewtopic.php?f=40&t=13725`, 26 pages / 380 posts, fetched in full to `forum_full_thread.txt` in the project root — WebFetch got a 403 on this URL, plain `curl` with a browser User-Agent worked fine). This is a real, active, years-long community project reverse-engineering and tuning this exact TCU family. Massive value, but also a real risk: **the thread covers multiple TCU hardware generations across many Subaru model years** (our Hitachi M32R chip, and separately a Denso SH7058-based chip used in later Tribeca/Outback TCUs) — details from the wrong chip generation must not be conflated with ours.

**Confirmed applicable to our exact chip/firmware family** (independently, from a completely different codebase — `miikasyvanen/FastECU` on GitHub, `config/protocols.cfg`):
- Protocol entries `sub_tcu_hitachi_m32r_kline` / `sub_tcu_hitachi_m32r_can` — MCU `M32176F4`/`M32R_512KB` (a larger-flash sibling in the same chip family as ours; the forum itself separately confirms early/pre-MY05 TCUs like ours use a 384KB M32R variant, `M32170F3` or `M32174F3` — see forum posts 7-8, "This is an early version of M32R 144 pin with 384 kB").
- **`<cal_id_addr>0x802a</cal_id_addr>`** — exact match to our own independently-found calibration-ID address (§5a). Strong independent confirmation.
- **`<checksum>yes</checksum>`** confirmed for this protocol family, consistent with our own confirmed checksum (§5b). Forum post separately states "This is assuming the ROM uses a 32 bit checksum like most Subaru ROMs" — matches our confirmed 32-bit algorithm exactly.
- **Transport split confirmed**: `<flash_transport>iso15765</flash_transport>` (CAN) but `<log_transport>K-Line</log_transport>` + `<log_protocol>SSM</log_protocol>` — i.e. **flashing happens over CAN, live logging happens over classic K-Line SSM, not SSM-over-CAN**. This resolves the open question from the paused §11e investigation (which was looking at RomRaider's SSM-over-CAN driver) — the real-world working tool uses K-Line for logging on this TCU family, not CAN.
- Forum post independently confirms SSM command bytes actually observed in a real TCU's disassembly: `0xA0` (read memory), `0xA8` (read address), `0xB0` (write memory), `0xB8` (write address), plus `0x81`/`0x83`/`0x27` — matches exactly the command byte values decompiled from RomRaider's own `SSMProtocol` class in §11e (`0xA8` = `READ_ADDRESS_COMMAND` etc. — same protocol family, independently confirmed from two directions).
- **Whole signal-chain architecture independently confirmed**, forum post (page ~8): *"CET is sent from the ECU via bytes 3 & 4 of CAN ID 0x412. The TCU calculates slip via the ratio between Turbine Speed and Engine Speed. A factor is looked up from a table based on the slip... CET is then smoothed and further factored by a lookup based on ATF Temp... used to lookup a Line Pressure target."* This is a near-exact match to what we independently derived via decompilation (§11a/§11b/§11c): CAN-derived signal → gear-indexed table lookups (our Slip Detection Threshold / Reference Speed Baseline families) → smoothing filter → feeds into gear-indexed pressure tables. Real, independent confirmation that we reverse-engineered the actual architecture correctly, not just a plausible-looking pattern.
- CAN ID meanings partially confirmed: **0x412 carries CET (Calculated/Corrected Engine Torque)**, bytes 3-4. **0x514 carries shift events** (a forum member logged it directly: byte value 2 = upshift, byte value 4 = downshift) — both fall within the `0x410-0x412`/`0x511-0x515` clusters we found in the CAN receive routine (§11b), now with real meaning attached to at least two of them.

**NOT yet confirmed applicable to our exact ROM** (found in the thread, but likely a different chip generation or a different firmware than 91D1206000):
- The "SSM Set Params" pressure-correction feature (`T024`-`T027` ecuparams: Direct Clutch/High-Low-Reverse/Input Clutch/Front Brake/Forward Brake/4WD/Line Pressure corrections, "Temp Basis") uses RAM addresses like `0xFF2189`/`0xFF218A`/`0xFF218B` — these do **not** fall in our confirmed M32R RAM range (`0x800000-0x820000`) at all, and `0xFFxxxx`-style addresses are far more typical of a Renesas SH-series (SH7058) memory map than M32R. This feature is very likely specific to the **Denso SH7058-based Tribeca/later-Outback TCU**, a different chip covered later in the same thread — not directly usable for our ROM. The *concept* (line pressure has a temperature-basis correction) still supports prioritizing our own two candidate ATF-temperature-axis table families from §3 (~0x0154A0, ~0x015B00 — found early this session, not yet added to the RomRaider def) as the most likely place to find the real "ATF Temp lookup" the forum describes, in our own address space.
- Specific table addresses discussed elsewhere in the thread (shift curves, line pressure calc tables) are for whatever firmware ID those specific posters were working with — **our exact firmware (`91D1206000`) is only mentioned once, in the very first identification post** (§ this file, "MB431M - 91D1206000"). The deep table-hunting work later in the thread was done on other cal IDs. Architecture transfers; addresses don't.
- Real kPa-per-raw-step relationships were shared (e.g. "logged offset 186 = 7 kPa, offset 178 = 30 kPa" for a "Line Pressure Correction" parameter) — useful as a sanity-check reference for what a plausible kPa/raw slope looks like on this transmission family, but tied to the SH7058 correction feature above, not directly transplantable to our tables without finding the equivalent mechanism in our own ROM/firmware.

**Not yet done, appropriately scoped as next steps rather than attempted this pass**: decoding the DTC `flags` field's bit meanings; finding real conversion factors for our own confirmed table families (would mean locating the M32R-side equivalent of the "ATF Temp lookup"/CAN-transmit-with-real-units code, analogous to what the forum found for the SH7058 chip); adding the two ATF-temperature table families to the RomRaider def now that there's a strong external reason to prioritize them.

---

## 11h. DTC table added to the definition file; category names aligned to real RomRaider convention

Extended `tools/generate_romraider_def.py` with `extract_dtc_records()` (walks the confirmed DTC table at ROM 0x004090 programmatically — not hand-typed — stopping cleanly when the code field leaves the 0x0700-0x07FF range; 19 records found) and `build_dtc_table_xml()`, which emits each DTC's raw 16-bit `flags` field as its own named `type="1D"` (single-cell) table, e.g. "DTC P0730 Flags". Two records share DTC code P0745 (different addresses) — disambiguated as "P0745 (A)"/"P0745 (B)" to avoid a duplicate table name. Descriptions give the general, publicly-documented SAE J2012 meaning of each P07xx code family, explicitly caveated that the exact bit-level enable/disable meaning of `flags` isn't decoded yet (§11f) — these are exposed as plain editable raw values for inspection/experimentation, not asserted to have a known effect.

**Also checked a real, mature RomRaider definition (`Merp/SubaruDefs`) for its category-naming convention** and re-aligned ours to match, rather than using made-up category names:
- `TCU - Speed Trim A` → `Transmission - Speed Trim A`
- `TCU - Slip Detection Threshold` → `Transmission - Slip Detection`
- `TCU - Reference Speed Baseline` → `Transmission - Reference Speed`
- `TCU - Slip Comp Pressure B/C` → `Transmission - Pressure Control B/C`
- `TCU - Shift Stage Value D` → `Transmission - Shift Solenoid Control`
- DTC tables use `Diagnostic Trouble Codes` — a real, standard category name used verbatim in mature RomRaider defs (confirmed by inspecting `ecu_defs.xml`'s actual category list), not invented.

**Current definition file total: 49 tables (30 in the 6 confirmed 2D families + 19 DTC 1D tables) across 7 categories.** Deliberately still excludes the two ATF-temperature-axis candidate families from §3 — their exact address boundaries turned out ambiguous on closer inspection this pass (two overlapping byte-offsets both parse as superficially "valid" tables, only 2 bytes apart) and neither has a confirmed code reference yet; adding either to a file meant for real edits without resolving that first would risk shipping a wrong address. Regenerate via `python tools/generate_romraider_def.py`; re-verify via `python tools/validate_xml_defs.py` (60/60 address checks passing for the 2D tables).

---

## 11i. DTC entries converted to real `type="Switch"` enable/disable tables; one more real-units lead checked (negative result)

**DTC enable/disable**: checked the real `Merp/SubaruDefs` `ecu_defs.xml`'s own "Diagnostic Trouble Codes" tables directly — they use `<table type="Switch" ... sizey="N"><state name="on" data="..."/><state name="off" data="..."/></table>`, where "off" replaces the DTC-identifying bytes with a null pattern (e.g. a real example: P0011's "on"=`04 00 11`, "off"=`05 00 00` — the code bytes get zeroed, not a single flag bit flipped). `tools/generate_romraider_def.py`'s `build_dtc_table_xml()` rewritten to match: each of our 19 DTCs is now a `type="Switch"` table (`sizey="8"`, matching our confirmed 8-byte record), with `"on"` = the exact 8 bytes found in the ROM and `"off"` = the same bytes with the 2-byte DTC code field zeroed, flags/data untouched.

**Important honesty flag, explicit in each table's description**: this "off" behavior is **modeled on the confirmed convention from a different Subaru ECU's real definition file — it is NOT independently confirmed for this M32R TCU.** Searched `full_decompile.c` broadly for any code that reads the DTC table (literal address references to `0x004090`+, and 8-byte-stride array access patterns) and found nothing — the code that actually processes this table almost certainly lives in the K-Line SSM diagnostic-request path, which hasn't been disassembled/decompiled this session (our Ghidra coverage was seeded from the CAN-side interrupt handlers, not the diagnostic path). Treat every DTC "off" state as an experimental hypothesis until verified on real hardware/logging — though DTC suppression is a lower physical-risk category of edit than an actuator/pressure table (worst case it just doesn't work, not that it damages anything).

**Real-units search, one lead checked**: found a function (`FUN_00031a78`) that branches on `DAT_0080885A` (current gear) 0-4 and assigns a constant per gear — but the constants are `0x10, 0x20, 0x30, 0x40, 0x50` (clean, evenly-spaced code values), not real gear-ratio numbers. Almost certainly a gear-indicator/display code (e.g. for a dash readout or diagnostic report), not a physical constant — doesn't help with unit scaling. Recorded here so this lead isn't re-investigated later. Real units for any of our tables are still unconfirmed.

**Applied one estimated scale — ⚠️ THIS WAS LATER PROVEN WRONG, see §11s for the correction to `x/8`.** The three families sharing the `0, 5120, 10240, ..., 51200` axis shape (Speed Trim A, Slip Detection, Reference Speed) were given an X axis of `RPM (est.)` via `expression="x/12.8"` — motivated by 12.8 = 64/5, a clean shift-and-multiply divisor an embedded fixed-point implementation would plausibly use, giving a tidy 0-4000 RPM range in 400 RPM steps. This is a structural argument, not a confirmed value — labeled "(est.)" directly in the axis name (not just buried in a description) so it can't be mistaken for a proven conversion. Declined to apply anything to the 2048-16384-shaped axis (Pressure B/C, Shift Stage D — a different, difference/error-type quantity, not a direct speed value, so the same divisor doesn't obviously apply) or to any DATA/output column (no clean divisor or code evidence found for those at all — would be outright fabrication, not estimation, so left as raw).

---

## 11j. FastECU's real, tested checksum implementation found — confirms our algorithm exactly, and catches a second checksum that does NOT apply to us

User asked whether other community work exists defining these TCU ROMs — checked `miikasyvanen/FastECU`'s `modules/checksum/` and `modules/tcu/` folders (both have dedicated files for `subaru_hitachi_m32r_can`, our exact chip/protocol family; there's a separate `_cvt_` set of files for the CVT transmission variant, correctly ignored per user's steer to stay 5EAT-only).

**`checksum_tcu_subaru_hitachi_m32r_can.cpp`'s "checksum 2" is an exact, independent, byte-for-byte match to our own algorithm** (§5b): sum of all 32-bit BE words in the ROM excluding the 8-byte range `[0x8000, 0x8007]`, then negate via `0xFF - byte` (top 3 bytes) / `0x100 - byte` (low byte) — arithmetically identical to our `-(sum) mod 2^32`, just implemented byte-wise instead of as one 32-bit operation. Strong, independent, code-level confirmation of `tools/checksum.py`.

**But the same file also implements a "checksum 1" we did not know about**: sum of all 32-bit BE words from file offset `0x8020` to end-of-file must equal a fixed magic constant `0x5AA5A55A`, with a "balance value" stored at `0x8020` itself adjusted to make that hold. **Checked this against our actual stock, unmodified ROM — it does NOT hold** (computed sum = `0x6A7B5AA5`, not `0x5AA5A55A`). Since a real factory-shipped ROM should already satisfy any checksum its own firmware enforces, this is strong evidence **checksum 1 does not apply to our specific 384KB firmware** — it's likely specific to a different M32R sub-variant (e.g. the 512KB `M32176F4` chip) that this same FastECU handler is generically written to also cover. Reinforced by the fact that file offset `0x8020` falls *inside* our own already-confirmed calibration-ID block (§5a, ID data spans `0x8008`-`0x802F`) — treating it as a checksum balance value to "fix" would have corrupted real ID data. **Deliberately NOT added to `tools/checksum.py`** — verified before incorporating, exactly the kind of check that prevents importing something that looks authoritative but doesn't actually apply here.

---

## 11k. Info section cleaned up — one entry instead of three

User feedback: the earlier 3-table "Info - Read This First" category (§11c/11h) looked cluttered/confusing in RomRaider's actual UI — three separate table-looking entries for what's really just documentation. Checked how a real definition handles this (`CarBerryROM`, `github.com/Crowley2012/SubaruTuning` — note: the copy on this PC at `C:\Users\Tom\OneDrive\Documents\CarBerryROM-*.xml` turned out to be a *saved GitHub webpage*, not the raw XML — that's what caused the "crossorigin" parse errors seen in RomRaider's log early this session; fetched the real raw file from GitHub instead). Confirmed: RomRaider has no dedicated "notes/readme" schema element at all — the convention is just an ordinary table with a rich `<description>`. Consolidated to **one single locked, non-editable `type="1D"` table named "Read This First" under category "Info"**, with all three caveats (ID block, static-file-only limitation, checksum fix requirement) combined into one description block. `INFO_ENTRIES` list replaced with a single `INFO_README` string constant and `build_info_table_xml()` takes no arguments now.

---

## 11l. Real Subaru factory service manual found — authoritative reference data (2004 Legacy, matches our TCU generation)

User asked whether the 5EAT service manual exists online — yes: a 2004 Legacy factory service manual (Fuji Heavy Industries, Subaru's parent company), hosted at `subaruport.ru/leg4/leg4_trans_4-1.pdf`, matches our pre-MY05 TCU generation. WebFetch couldn't extract text from it directly (compressed PDF streams), but the binary saved automatically; installed `poppler-utils` in WSL and ran `pdftotext -layout` to get real text. Saved permanently in the project root: `subaru_5eat_service_manual.pdf` (original) and `subaru_5eat_service_manual_extract.txt` (extracted text, also mirrored in WSL `~/5eat`).

**Confirmed, authoritative specs extracted:**

- **Gear ratios** (§4, "TRANSMISSION GEAR RATIO"): 1st = 3.540, 2nd = 2.264, 3rd = 1.471, 4th = 1.000, 5th = 0.834, Reverse = 2.370.
- **Line pressure test** ("P/L Solenoid Target Pressure", read directly off the Subaru Select Monitor in kPa): D range, throttle full closed → target 490 kPa, standard range 385-555 kPa (55.8-80.5 psi). D range, throttle full open, ATF 45-55°C (104-131°F) → target 1370 kPa, standard range 1235-1475 kPa (179.1-213.9 psi). R range, full closed → target 1370 kPa, standard range 1530-1925 kPa (221.9-279.2 psi).
- **Transfer clutch pressure test** ("T/F Solenoid Target Pressure", AWD models): D, full open → target 900 kPa (800-915 kPa / 116-132.7 psi). D, partial throttle → target 500 kPa (400-535 kPa / 58-77.6 psi). N, full closed → target 0 kPa (0-50 kPa).
- **ATF test condition**: 45-55°C (104-131°F) — the manual's own standard test temperature for pressure checks, not necessarily the sensor's full working range.

**Not yet done**: mapping these real kPa/psi numbers onto any of our own ROM tables. None of our current tables' raw values (e.g. flat "20", step "6,6,6,10,10") land anywhere near these kPa magnitudes under any simple scale factor tried so far — these look like small correction/offset values (consistent with the forum's "pressure correction" concept from §11g), not the absolute line pressure targets themselves, which are likely computed/stored elsewhere in the ROM and still need to be located. This service manual data is now a solid, authoritative reference to check any future candidate table against — real numbers to validate a scale factor against, rather than the estimated/structural-argument approach used for the RPM axis (§11i).

---

## 11m. Open-source SSM tools checked for real unit-conversion formulas — negative result (FreeSSM)

User asked to check open-source SSM tools for a leg up on decoding real values. Checked `Comer352L/FreeSSM` (the tool the RomRaider forum thread references as having real TCU pressure/kPa handling, §11g) across **all** its branches (`master`, `freessm-v1.2`, `gh-pages`, and `e5at-permanent-adjustments`):

- The `e5at-permanent-adjustments` branch does add real Transmission Control Unit support to the FreeSSM UI (`TransmissionDialog.cpp`/`CUinfo_Transmission.cpp`) — but it's **generic wiring**, not per-model data: it just enables the same DTC/measuring-block/switch/adjustment panels used for every other control unit type, driven entirely by whatever `SSM1defs_*.xml` file is loaded (`SSMDefinitionsInterface`/`SSMLegacyDefinitionsInterface` parse an XML keyed by ROM ID bytes, same style as our own RomRaider `<romid>` matching).
- **No `SSM1defs_Transmission.xml` (or equivalent) exists anywhere in the repo, on any branch.** Only `SSM1defs_ABS.xml`, `SSM1defs_AirConditioning.xml`, `SSM1defs_CruiseControl.xml`, `SSM1defs_Engine.xml` were ever shipped, on master and on the e5at branch alike.
- **Conclusion: FreeSSM does not give us real per-parameter unit-conversion formulas for any TCU, ours included.** The forum's "steps"/kPa comment refers to that poster's own manual work, not something bundled in FreeSSM's public repo. Dead end for this specific question — not pursued further.

---

## 11n. Major correction: real shift-schedule table architecture found (supersedes the wrong 3-address guess in §10)

**The three addresses guessed in §10 (`0x017698`, `0x019324`, `0x0001A2FE`) as "the other three shift-schedule tables" were wrong** — confirmed by direct byte inspection: none of them parse as a real multi-point hysteresis-record table (each terminates after 0-1 real records; `0x019324`/`0x0001A2FE` in particular are never referenced anywhere in `full_decompile.c` as table pointers — pure coincidental pattern matches from the original Python scan, not real tables). Re-derived the real structure directly from decompiled code instead of guessing addresses from an incomplete branch excerpt.

**The real mechanism** (function `FUN_00043428`, `full_decompile.c` ~line 26651):

```c
short sVar1 = 0;
if (DAT_00808858==-0x7c || DAT_00808858==-0x80 || DAT_00808858==-0x74) sVar1 = 0;
else if (DAT_00808858 == -0x7b) sVar1 = 1;
else if (DAT_00808858 == -0x7f) sVar1 = 2;
else if (DAT_00808858 == -0x7e) sVar1 = 3;
else if (DAT_00808858 == -0x7d) sVar1 = 4;
...
DAT_00808b94 = (ushort)DAT_0080885a * 2 + sVar1 * 10;      // gear*2 + mode*10
DAT_008089f0 = (&PTR_DAT_00017714)[DAT_00808b94];           // "A" slot (pointer array @ 0x017714)
DAT_008089f8 = (&PTR_DAT_00017718)[DAT_00808b94];           // "B" slot (= PTR_DAT_00017714[idx+1] — same array, offset by one pointer)
```

- **`DAT_0080885A`** = current gear (0-4), already confirmed (§8d).
- **`DAT_00808858`** takes exactly 5 distinct byte values (`-0x7c/-0x80/-0x74`→mode0, `-0x7b`→mode1, `-0x7f`→mode2, `-0x7e`→mode3, `-0x7d`→mode4) — the shape (a small fixed set of discrete codes, gating which full set of shift curves is active) is strongly consistent with a **shift-range/PRNDL selector reading** (Subaru 5EAT shifters expose ranges like D/3/2, sometimes plus a manual/power mode) — plausible but **not proven**; no string table or other confirmation found this pass.
- **`0x017714`** is a genuine 50-entry (0-49) pointer array — indexed by `gear*2 + mode*10`, i.e. **5 modes × 5 gears × 2 slots ("A"/"B")**. `0x017718` is not a separate array; it's literally `0x017714 + 4` (one pointer later), confirming slots A and B for a given gear/mode are simply consecutive entries in the one array.

**Mapped the full 50-entry array** (`base + idx*4`, each entry a 32-bit BE pointer) against the record format from §8e/§10 (8-byte records `[A,B,C,D]` uint16, terminated by a leading `0xFFFF`):

| Gear | Mode 0 (full) | Mode 1 | Mode 2 | Mode 3 | Mode 4 |
|---|---|---|---|---|---|
| 0 A | **0x015CA8 (n=8)** | same | same | same | 0x0176A2 (n=1, placeholder) |
| 0 B | 0x017698 (n=1, placeholder — shared by ALL modes) | | | | |
| 1 A | **0x015D14 (n=8)** | same | same | 0x0176A2 (placeholder) | 0x0176A2 |
| 1 B | **0x015CEA (n=5)** | same | same | same | 0x015ECA (n=2) |
| 2 A | **0x015D90 (n=9)** | same | 0x0176A2 (placeholder) | 0x0176A2 | 0x0176A2 |
| 2 B | **0x015D56 (n=7)** | same | same | 0x015EE6 (n=2) | same as mode3 |
| 3 A | **0x015E1C (n=9)** | 0x0176A2 (placeholder) | 0x0176A2 | 0x0176A2 | 0x0176A2 |
| 3 B | **0x015DDA (n=8)** | same | 0x015F02 (n=2) | same as mode2 | same |
| 4 A | 0x0176A2 (placeholder — every mode, no real curve ever) | | | | |
| 4 B | **0x015E66 (n=11)**, mode0 only | 0x015F1E (n=2), shared by modes 1-4 | | | |

(Bold = genuine multi-point calibration curve, 5-11 records each, all in the same tight cluster `0x015CA8`-`0x015F1E` right after the already-confirmed §10 table. `0x0176A2` is a single-record flat/disabled placeholder reused dozens of times wherever a mode/gear/slot combo has no real distinct schedule.)

**Reading of the pattern**: mode 0 has real, unique, multi-point curves for essentially every gear/slot (8 real curves total: g0A, g1A, g1B, g2A, g2B, g3A, g3B, g4B) — clearly the "full" operating mode. Modes 1-4 progressively fall back to the 1-2-record placeholder for higher gears while still real for lower ones — consistent with **range-restricted operation** (a shift-range selector position that mechanically/logically caps the highest usable gear, so higher-gear schedules genuinely don't need real curves in that mode) rather than 5 independent full schedules. This is a hypothesis, not confirmed — the actual meaning of `DAT_00808858`'s 5 codes is still unknown.

**Not yet added to the RomRaider definition file.** Same limitation already noted for this record format in §11c/§11d: RomRaider's native 2D table storage assumes a **contiguous** uint16 array (fixed 2-byte stride); these records interleave 4 fields with an 8-byte stride, which RomRaider's schema has no way to express (confirmed by decompiling its own unmarshaller code, §11d — no stride/increment attribute exists). Forcing a fake contiguous-table definition over strided data would silently write to the wrong bytes on save — exactly the class of bug already caught and fixed once this session (§11d). Leaving this undone in the def file is the correct call, not an oversight; it's tracked here so it isn't lost, and revisited if RomRaider ever gains stride support or if a hex-editor-based workflow becomes acceptable for just these curves.

**Field-level structure of each curve** (using `0x015CA8` as the reference, already confirmed in §8e/§10): record *i*'s field A = breakpoint *i*, field C = breakpoint *i+1* (redundant lookahead), field B/D = a rising/falling value pair for that breakpoint. Each curve ends with a `0xFFFF` sentinel record whose trailing field is a small value (8, 0x18, 0x1A, 0x24, 0x2B, 0x2A, 0x3A, 0x60, 0xFF, 0x12...) that doesn't fit the interpolation pattern — likely a chain/link value read by whatever code processes the *end* of the table (not yet traced).

---

## 11o. Exhaustive lookup-table sweep + scalar constants — def file grows from 50 to 60 tables

User asked to keep locating more tables/settings ("there has to be tons"). Did this systematically rather than more manual address-guessing:

**Step 1 — re-ran the pointer/reference cross-check against all 307 pattern-matched candidate tables**, this time against the full decompiled program (`full_decompile.c`, ~90% code coverage) instead of the raw disassembly used originally. Found 7 candidates with a string match; verified each one's actual usage (indexed array access = real table, vs. plain scalar read = false positive) rather than trusting the string match alone:
- `0x008688` — **false positive**: read as a single scalar (`DAT_008087fe <= DAT_00008688`), not indexed. Not a real table.
- `0x01CEE8` — **false positive**: read as a single scalar bitmask (`uVar5 = uVar5 | DAT_0001cee8`), not indexed. Not a real table.
- The other 5 (below) are genuine, code-confirmed 2D interpolation tables.

**Step 2 — went further and grepped every direct call site of all three known interpolation functions** (`FUN_0004515C`, `FUN_00045234`, `FUN_00045300`) across the entire 1090-function decompiled program. Exactly **13 call sites exist in the whole program**, and every one is now accounted for in the definition file — this means the standard 2D lookup-table format search is **complete**: there are no more hidden curves of this kind left to find (short of the separate 8-byte hysteresis-record format from §8e/§11n, which uses a 4th function, `FUN_00045070`, and is still blocked from RomRaider by the stride issue).

**5 new real tables added** (families `PressureThresholdE`, `CAN511Threshold`, `SignalResponseCurves` in `tools/generate_romraider_def.py`):
- **`0x010844`/`0x01086E`** ("Pressure Threshold E", 2 modes) — same confirmed X-formula as Pressure Control B/C/D (`X = ref*256 - RefSpeedBaseline lookup`), just mode-selected instead of gear-indexed. Flat/zero currently, same as B/C.
- **`0x011836`** ("CAN 0x511 Byte 4 Threshold Curve") — X-input is **CAN ID 0x511, payload byte 4**, scaled by a confirmed fixed 333/256 (~×1.301) factor. First table found fed by a CAN ID other than 0x410/0x412 — extends the CAN signal map from §11b/§11g. Flat/zero currently.
- **`0x011898`** ("CAN 0x410 Chain Response Curve") — X-input is the already-known §11a/§11b CAN 0x410 chain value (pre-×256). **Real, populated hump-shaped curve**: rises 61→127 then falls back to 0 — genuinely tunable, not a placeholder.
- **`0x0118DA`** ("Signal FE Response Curve") — X-input traced to an internal RAM value (`DAT_008087FE`) through several conditional assignments, not yet tied to a specific sensor/CAN ID. Real, populated step curve (64→256).
- **`0x0117BE`** ("Smoothed Signal Response Curve") — X-input is `DAT_008087FE` smoothed through a calibratable filter (gain at `0x01137E`). Shares the same 5120-step breakpoint convention as the existing RPM-(est.) families, so labeled the same way. Real, populated rising curve (200→1189).

**4 new scalar "settings" added** (`SCALARS` list, category "Transmission - Calibration Constants") — single tunable values rather than curves, each found by enumerating every call site of the confirmed smoothing-filter function (`FUN_0005c8a0`) plus threshold constants traced while chasing the new tables' inputs:
- **`0x01137C`** / **`0x01137E`** — the two calibratable filter gains (both stock value 128) for the CAN-0x410 chain and Signal-FE chain smoothing filters respectively.
- **`0x010840`** — single byte (stock value 2), compared directly against current gear (`0x0080885A`) and the second gear-like index (`0x0080886E`) in several places in one function — reads like a "logic applies above/below gear N" cutoff.
- **`0x010842`** — a threshold compared against a computed signal delta in the same fault-detection routine that reads Pressure Threshold E. Storage width (byte assumed) wasn't independently double-confirmed the same way as the others — flagged as such in its description.

**Did NOT dump the other ~1300 code-referenced ROM addresses in the 0x008000-0x01D200 region wholesale** — a first attempt at this cross-reference (matching every `DAT_`/`PTR_DAT_` symbol in that address range, not just table-lookup-function call sites) surfaced ~1324 distinct addresses, i.e. essentially every byte of the calibration region is touched by *some* piece of code. Dumping all of them would be pure clutter (explicitly against the user's own stated preference for a clean, non-"word-vomit" definition file) with no way to tell which are genuinely meaningful tunable settings vs. incidental byte-level accesses (flags, state-machine bytes, parts of the calibration ID block, etc.) without individually tracing each one. The 4 added here were chosen because they had a *clear, individually-confirmed, meaningful role* (filter gain / named threshold), not just "some code reads this address."

**Definition file now: 60 tables** (36 in 9 families + 4 scalar constants + 19 DTC Switch tables + 1 Info table) across 10 categories. Re-validated: `tools/validate_xml_defs.py` now also checks `type="1D"` scalar tables (address bounds + prints the raw stored value), in addition to the existing 2D address-relationship checks — 72 checks / 36 2D tables + 4 scalars, all passing.

---

## 11p. `FUN_00045070` (hysteresis-record lookup) has ~75 call sites — a whole second family of tables, plus a promising RomRaider representation found (not yet shipped)

Following up "there has to be tons more" — grepped every call site of `FUN_00045070` (the confirmed 8-byte hysteresis-record lookup function from §8e/§11n), not just the ones already traced through the shift-schedule state machine. **Found ~75 call sites across the whole program** — this function is used far more broadly than just shift scheduling:

- Several more **gear-indexed pointer-to-pointer arrays** in the same style as our confirmed 2D families, all in the already-familiar `0x0001xxxx` cluster: `0x00010E74`/`0x00010EDC`, `0x00010F44`/`0x00010FAC`, `0x00011014`/`0x0001107C`, `0x00010AD8`/`0x00010AEC`, `0x00010C9C`/`0x00010D04`, `0x00011AF0`/`0x00011CA0`, `0x0001122C`/`0x00011240`, `0x000112A8`/`0x000112BC` (each a `(&PTR_PTR_0001xxxx)[DAT_0080885a]`-style two-mode/gear pattern, exactly like the confirmed B/C/D families) — i.e. **at least 8 more real gear-indexed calibration-curve families**, using the hysteresis-record format instead of the plain interpolation format.
- A **large, entirely separate ROM region (~0x0000F000-0x00012800)** referenced by dozens more call sites (e.g. `0x0000F026`, `0x0000F3E8`, `0x0000F068`, `0x0000F0BA`, `0x0000F610`, `0x0000F692`, `0x0000F69C`, `0x0000FA16`, `0x0000FA70`, `0x00012478`, `0x00012314`, `0x00012034`, `0x000124..`/`0x000125..`/`0x000127..`) that has **not been explored or characterized at all this session** — indexed by a mix of `DAT_0080886E` (the second gear-like index), other RAM variables, and in a couple of spots what looks like a completely different subsystem (possibly TCC lockup control, given it's a large, separate block from the shift-schedule cluster). This is a substantial unexplored area, likely containing many more real settings.

**Why none of this has been added to the definition file yet**: same reason as §11n — RomRaider's native 2D/1D storage assumes a contiguous, fixed-stride array, which the 8-byte interleaved record format doesn't fit.

**A genuinely promising fix was found, but deliberately NOT shipped without live verification**: fetched a real, large (122K-line) reference definition (`Merp/SubaruDefs`, `RomRaider/ecu/standard/ecu_defs.xml`, 245 real `type="3D"` tables) to check RomRaider's actual 3D-table schema (never previously checked this session — all our own tables so far are `2D`). Confirmed:
- RomRaider's convention splits a table into a **shape definition** (name/scaling/sizex/sizey, no address) and a separate, independently-addressed **override** block — e.g. `<table name="Target Boost (MT)" storageaddress="0x2B506"><table type="X Axis" storageaddress="0x2B4F4" /><table type="Y Axis" storageaddress="0x2B4E1" /></table>` — i.e. **the outer table's data block, the X axis array, and the Y axis array are three fully independent addresses**, not one contiguous structure the way our 2D tables' X-axis-then-data layout is.
- This means a 3D table's **data block** could point directly at one of our hysteresis-record tables' raw bytes (`sizex=4` fields × `sizey=n` records, contiguous — which is exactly how the ROM actually stores them, record after record) with **no stride problem at all** for the data itself, since a full contiguous grid read matches the physical layout exactly.
- The open question (not yet verified against real, installed RomRaider — same caution that caught the fake "Z Axis" bug in §11d): whether the `X Axis`/`Y Axis` sub-tables can be **static/label-only with no `storageaddress`** (so we wouldn't need a real ROM-backed axis for "field name" or "record number" — sidestepping the one thing that WOULD still have a stride problem), or whether RomRaider requires every axis to have a real address to load a table at all. The one example checked so far omits `storageaddress` on X/Y Axis entirely, but that specific instance is a `logparam`-only definition (paired with live SSM logging, not proven to load as a static/edit-only table the way ours need to).

**Concrete next step**: build one small test 3D table (using the fully-understood, already-catalogued `0x015CA8` hysteresis table from §11n as the guinea pig — `sizex=4, sizey=8`, data storageaddress `0x015CA8+2` i.e. right after the leading `[0,0]` pair, X/Y axis static or omitted) and **actually load it in the user's installed RomRaider** before committing to this representation for real — exactly the same "test before trusting the schema" discipline that caught the original Z-axis bug in §11d. If it works, this unlocks not just the 4 shift-schedule gear-tables already found but potentially **all ~75 `FUN_00045070` call sites** as real, editable RomRaider tables — a substantial expansion beyond the current 60.

---

## 11q. ~21 more real hysteresis-format tables confirmed across two ROM regions — full picture of `FUN_00045070`'s ~75 call sites

Continuing "find more" — dumped the raw byte structure at every `FUN_00045070` target address surfaced by §11p's call-site sweep (not just the shift-schedule cluster). Result: **the great majority parse as clean, valid, sentinel-terminated multi-record tables** (3 to 17 records each), confirming this is a widely-reused format across the whole firmware, not just shift scheduling:

`0x008332`(n=7), `0x0083D8`(n=9, pointer array), `0x008428`(n=4), `0x008488`(n=11, pointer array), `0x0084E2`(n=10), `0x008534`(n=7, pointer array), `0x00856E`(n=6), `0x011854`(n=3), `0x01186E`(n=3), `0x00F026`(n=8), `0x00F068`(n=10, pointer-to-pointer array), `0x00F0BA`(n=10, pointer array), `0x00F610`(n=16), `0x00F692`(n=1, flat/placeholder — same role as `0x0176A2` in §11n), `0x00F69C`(n=11), `0x00FA16`(n=11), `0x00FA70`(n=9, pointer array), `0x012034`(n=17, pointer-to-pointer array), `0x00EE30`(n=7), `0x00EE6A`(n=7), `0x00EEA4`(n=7), `0x008376`(n=12), `0x00836C`(n=1, flat/placeholder). (`0x0085AA`, `0x00F3E8`, `0x012314`, `0x012478`, `0x00807E`, `0x0081E8`, `0x01B8D4` didn't parse as flat tables themselves — confirmed as **pointer arrays** referencing further tables, consistent with the call-site grep already showing `PTR_DAT_`/`PTR_PTR_` prefixes for those.)

**Grouped by shared X-input** (from the call sites, without fully re-tracing every branch's ultimate physical meaning — that would need much more time per group):
- **`0x008087FB`** feeds `0x00011854`/`0x0001186E` (mode-selected pair) and `0x00008428`.
- **`0x008082AC`** feeds `0x00008332` and (via a second function) `0x00008376`.
- **`0x008087D0`** feeds the `0x000083D8` pointer array directly — this is our **already-confirmed central CAN-0x410-derived reference signal** (§11a/§11b), so this cluster is a further consumer of it.
- **`0x008087FE`** feeds `0x00008488`/`0x000084E2` (mode pair) and `0x00008534`/`0x0000856E` (mode pair) and `0x000085AA` — the **same signal already confirmed** (§11o) to feed the "Signal FE Response Curve"/"Smoothed Signal Response Curve" standard-interpolation tables. So `DAT_008087FE` alone drives at least 6 confirmed table/family entries across both lookup formats.
- **`0x00808954`** feeds the largest single group — `0x0000F026`, `0x0000F068`, `0x0000F0BA`, `0x0000F3E8` (gear-indexed via `DAT_0080886E`), `0x0000F692`, `0x0000F69C`, `0x0000FA16`, `0x0000F728`(gear-indexed), `0x0000FA70`(gear-indexed) — **9 tables**. Traced `DAT_00808954`'s own assignment (`full_decompile.c` ~line 38634-38650): in most branches it's set **identically to `DAT_008087D0`** (`DAT_008087D0 = DAT_00808954 = DAT_000127DE`), i.e. it's a parallel copy/alias of the same central CAN-derived reference signal in the common case, diverging from it only under specific flag conditions (one branch sets them from two different sources, `DAT_0080892E` vs `DAT_00808C0C`). This means the entire 9-table `0xF000-0xFA70` cluster is very likely a **third major consumer group** of that one central reference signal, alongside the already-known gear-pressure tables and the §11o CAN-response curves.
- **`0x008082FA`**, gear-indexed via a **fourth distinct gear-like variable** `DAT_0080885F` (not `0x0080885A` or `0x0080886E`) — feeds `0x00012478`/`0x00012314`, output `DAT_00808A82`. `DAT_0080885F`'s own role isn't traced yet.
- **`0x00012724`/`0x0001275C`/`0x000125FC`** are accessed via raw pointer dereference (`*(undefined4*)(iVar5+0x12724)`) rather than a plain named symbol — `iVar5`'s origin wasn't traced this pass.
- Three parallel tables `0x0000EE30`/`0x0000EE6A`/`0x0000EEA4` (all n=7, same input `uVar1`) feed three adjacent output variables `0x0080888E`/`0x0080888F`/`0x0080888D` — likely three related outputs from one calibration (e.g. a 3-solenoid duty-cycle set), not traced further.

**None of this is in the definition file** — same reason as §11n/§11p (RomRaider stride limitation, pending the 3D-schema verification step already identified as the concrete next action). This entry exists so the addresses, record counts, and input groupings aren't lost — tracing every group's exact physical meaning would take substantially more time than a single pass and has fast-diminishing returns without either the 3D-table fix landing or live hardware access, per the pattern already seen with CAN ID meanings and RPM estimates elsewhere in this document.

**Running total of real, code-confirmed hysteresis-format tables found**: 7 (shift-schedule cluster, §11n) + ~21 (this pass) = **~28 tables**, none yet exposed in RomRaider, all blocked on the same schema question.

**Bonus: a fourth, previously-unseen selection mechanism found** while resolving the `0x00012724`/`0x0001275C`/`0x000125FC` raw-pointer-dereference call sites (`full_decompile.c` ~line 30140-30184): these aren't plain pointer arrays — each is a **byte-keyed pointer-array search**: an 8-byte-stride array of `[key:byte][pad:3][table pointer:4 bytes]` records (at `0x00012720`/`0x00012758`/`0x000125F8` respectively), walked linearly (`while key[i] < search_value: i++`) to find the first bracketing entry, then that entry's stored pointer is passed into `FUN_00045070`. The search key is `DAT_008087FB` (already known — feeds other Group-1 tables in this same section) or, under one flag condition, a new scalar `DAT_00011CF6`. This is a **generalized, non-gear/non-mode selector** — indexed by comparing against an arbitrary byte value rather than a fixed 0-4 range — output feeds `DAT_008086E6` (a running minimum across all three branches: `if (uVar2 < DAT_008086E6) DAT_008086E6 = uVar2`, i.e. this is computing a worst-case/limiting value across three parallel lookups). Not pursued further this pass — logged so it isn't lost. Also confirmed `DAT_0080885F` (the 4th gear-like variable from this section) is a distinct state variable, zeroed together with `DAT_0080885E` at reset and separately checked against a 15-entry ID-matching table at `0x000142EC` (a byte value equality search, not an interpolation) — a genuinely different kind of table (lookup/match, not curve) not investigated further.

---

## 11r. BREAKTHROUGH — first CONFIRMED real-world scale factor found (gear ratios), plus a new table format that RomRaider can represent natively

Searched for a table format not previously looked for at all: **plain contiguous arrays read by ordinary indexed access**, with no lookup/interpolation function involved. Regex-scanned `full_decompile.c` for `(&DAT_0001xxxx)[index]`-style direct reads. **Found 90 such ROM addresses.** Crucially, these are contiguous and fixed-stride, so unlike the hysteresis-record tables (§11n/§11p/§11q) they map onto RomRaider's native storage **with no stride problem** — they can be shipped immediately.

### The gear ratio table — first proven scale factor in this project

**`0x01234C`, 5 × uint16, indexed by current gear (`DAT_0080885A`): raw `[3625, 2318, 1507, 1024, 854]`.**

Divided by 1024, these are `[3.5400, 2.2637, 1.4717, 1.0000, 0.8340]` — matching the factory service manual's published 5EAT ratios (§11l: 3.540, 2.264, 1.471, 1.000, 0.834) **to within 0.0007 on every single gear**.

This is confirmed **two independent ways**, not just by the numeric coincidence:
1. **External authoritative reference** — the Subaru factory service manual ratios match exactly.
2. **The code itself divides by 0x400** — `full_decompile.c` ~line 34051: `uVar1 = (DAT_008082ba * DAT_0001234c) / 0x400;` (0x400 = 1024). The firmware's own arithmetic confirms the scale factor independently of the manual.

**This is the first table in the entire project with a genuinely proven real-world scale factor** — everything prior was either raw or an explicitly-labeled "(est.)" structural guess (§11i). Added to the definition file with real `ratio` units, `expression="x/1024"`, 3-decimal display.

Its role, from the call sites: computing expected output speed per gear (`speed × ratio / 1024`) and comparing that against measured values — i.e. it underpins **gear-ratio fault detection (DTC P0730, "Incorrect Gear Ratio")**, which is already in our DTC list. The description in the def file notes explicitly that editing these does *not* change physical gearing — it changes what the TCU *believes* the gearing is.

**Useful corollary**: because `DAT_008082BA × ratio / 1024` is compared directly against `DAT_008082CC` (the output of the **Slip Detection Threshold** family) and `DAT_008082BC`, those tables' *data* values are confirmed to be **in the same units as the speed variable `DAT_008082BA`** — a real, code-proven relationship between two already-shipped table families, even though that unit's absolute scale still isn't pinned to RPM/MPH.

### Five parallel shift-state bit-pattern arrays (added, marked expert-only)

**`0x0087AA`, `0x0087B8`, `0x0087C6`, `0x0087D4`, `0x0087E2`** — five 14-entry uint8 arrays, packed perfectly contiguously (each exactly 14 bytes after the last, filling 0x0087AA-0x0087EF with no gaps), all indexed by the same internal shift-state variable `DAT_0080885F` (range 0-13), each feeding a different control output (`0x00808885`, `0x00808883`, `0x00808861`, `0x00808863`, `0x0080886B`). **Every stock value is a power of two** (0/1/2/4/8/16/32/64/128) — these are unambiguously **bit patterns, not scalar quantities**.

Initially sampled these at 8 entries and would have shipped a wrong size — caught it by noticing the arrays are spaced exactly 14 bytes apart, which pins the real length at 14. Worth remembering as a general check: for parallel arrays, the spacing between them *is* the length.

All five are gated by the same `DAT_008094E0`/`DAT_008094E4` flag bytes that §8d already identified as solenoid/pressure-switch feedback status, with a hardcoded fallback value of 7 when a fault condition holds — consistent with these being clutch/solenoid engagement patterns per shift state, though **which specific output each bit drives is NOT decoded**.

Added to the def file but marked **`userlevel="5"`** (RomRaider's real convention for expert-only tables — confirmed by inspecting the 176 tables that use it in `Merp/SubaruDefs`' `ecu_defs.xml`) with an explicit safety warning in each description: an invalid clutch pattern on an AT can command two elements simultaneously and bind the driveline, which is genuine mechanical-damage territory, not just a "doesn't work" edit.

### Other direct arrays found, not yet added

`0x01BB1A`/`0x01BB1F`/`0x01BB24` (3 × 5 bytes, gear-indexed, values like `[2,1,1,1,2]`), `0x0134D2`/`0x0134E0`/`0x0146D0`/`0x014708`/`0x015470` (indexed by the shift-state variable `DAT_0080885F`), `0x012498`/`0x0124C0` (8-byte-stride records indexed by `DAT_0080886E`), `0x00F020`, `0x015C44`, and ~70 more. Not added this pass — each needs its length and role confirmed individually (exactly the check that caught the 8-vs-14 error above), and shipping unverified sizes/addresses into a file meant for real edits is the specific failure mode this project has already corrected twice (§11d, §11n).

**Definition file now: 66 tables** — 36 2D curves, 6 direct arrays (1 gear-ratio + 5 bit-pattern), 4 scalar constants, 19 DTC switches, 1 Info entry.

---

## 11s. RPM SOLVED — real speed units found, and the old "(est.)" axis scale CORRECTED (it was wrong by 1.6x)

Chased the speed-unit question directly. Found the actual sensor input path, which settles RPM properly and **corrects an earlier estimate that was wrong**.

### The RPM formula, found in code

`FUN_00030A84` and `FUN_00030AF4` are two near-identical routines, each reading a hardware capture value and converting it:

```c
uVar1 = FUN_00029bd0();                          // channel 1 raw pulse period
if (((uVar2 & 1) == 0) && (uVar1 != 0))
    uVar1 = (60000000 / DAT_0001c2c1) / uVar1;    // <-- period-to-RPM
DAT_00808366 = min(uVar1, DAT_0001c2a8);          // clamp
```

`60000000 / (N × period)` is the **textbook period-to-RPM conversion**: 60 seconds × a 1 MHz timer, divided by pulses-per-revolution `N`, divided by the measured period. Two independent channels, each with its own `N`:
- **`0x01C2C1` = 16** — channel 1 pulses per revolution
- **`0x01C2C2` = 22** — channel 2 pulses per revolution
- **`0x01C2A8` = 10000** — shared upper clamp (10,000 RPM ceiling)

(Confirmed these are adjacent *byte* constants, not a misaligned 16-bit read, by dumping the surrounding region — the odd address `0x1C2C1` alone already ruled out a word read.)

### The correction: table axes are RPM = raw / 8, NOT raw / 12.8

§11i applied an **estimated** axis scale of `x/12.8` to the Speed Trim A / Slip Detection / Reference Speed families, labeled "RPM (est.)" on a purely structural argument (12.8 = 64/5 being a plausible fixed-point divisor). **That estimate was wrong.** The real chain, all confirmed in code:

```
DAT_00808AE6 = smoothing_filter(DAT_008082BC << 3, ...)      // <<3 = x8, explicit
DAT_008082BC = min(CAN 0x410 bytes 5:6, DAT_0001C2A8)        // clamp = 10000
```

`DAT_00808AE6` is the confirmed X-input for all three of those families. Since it is the speed signal **multiplied by 8**, the axis converts as **`RPM = raw / 8`**. Two independent supports:
1. The `<< 3` is explicit in the decompiled code — not inferred.
2. `DAT_0001C2A8` (=10000) is the **same clamp constant** applied to both hardware speed channels whose RPM formula is confirmed above. One shared ceiling across all three signals is strong evidence they carry the same unit.

The resulting breakpoints are far more convincing than the old estimate:

| | raw/8 (corrected) | raw/12.8 (old estimate) |
|---|---|---|
| Speed Trim A | 0, 640, 1280 … 5760, **6400**, 8192(sentinel) | 0, 400, 800 … 3600, 4000, 5120 |
| Slip Detection | 640, 1280 … 5120, **6400**, 8160(sentinel) | 400, 800 … 3200, 4000, 5100 |

Clean 640 RPM steps topping out at **6400 RPM** with an ~8192 RPM "and above" sentinel is exactly right for a Subaru's rev range; the old estimate's 4000 RPM ceiling never made sense for this engine family. Axes now ship as `units="RPM"`, `expression="x/8"` — **the "(est.)" qualifier is dropped**, since this is now code-derived rather than guessed.

### A second correction: one table was mislabeled RPM and shouldn't have been

§11o labeled `0x0117BE` ("Smoothed Signal Response Curve") with the same RPM (est.) scale purely because it shares the 5120-raw breakpoint *step convention*. Re-checking its actual input shows a **different chain entirely** — `DAT_00808AE8 = smoothing_filter(DAT_008087FE << 8, ...)`, i.e. a 0-255 byte scaled ×256, not the ×8 speed signal. Reverted to raw, with the reason stated in its description. Shared step spacing is not evidence of a shared unit — a mistake worth not repeating.

### Also traced (not fully resolved)

`DAT_008087D0` — the operand in the Pressure Control B/C/D/E X-formula (`X = DAT_008087D0 × 256 − DAT_008092CE`) — resolves back to **CAN ID 0x412, payload byte 0** (via `DAT_0080892E` ← `DAT_0080895E`). The forum (§11g) independently established that 0x412 **bytes 3-4** carry CET (Calculated Engine Torque), so byte 0 of that same message is a different signal from the engine ECU, still unidentified. Because those families' X is a *difference* of two quantities rather than a direct signal, their axes remain raw — correctly left alone.

### Added to the definition file

Three new confirmed scalars under a new "Transmission - Speed Sensors" category: both pulses-per-revolution constants and the shared RPM ceiling — genuinely tunable settings (they matter if a tone ring or sensor is ever changed) with explicit warnings that changing them corrupts every speed-derived calculation.

**Definition file now: 69 tables.** Running total of confirmed real-world scale factors: **2** (gear ratios raw/1024 §11r, engine speed raw/8 §11s). Temperature and pressure units remain unidentified.

---

## 11t. TEMPERATURE SOLVED — two thermistor channels found, encoding confirmed as (raw − 40) °C

### How they were found

Searched for the analog sensor path. The peripheral register map (0x804000-0x806000, 147 addresses) turned up a bank at `0x8047EA/EC/EE/F0/F2` — five consecutive 16-bit registers — but those are **written**, not read: they're the **5-channel solenoid PWM output bank** (`register = ROM_constant + variable`), a useful find but the wrong subsystem.

The sensors were found instead via two structurally identical routines, `FUN_00054BC8` and `FUN_00054C78`:

```c
DAT_008087F9 = 0xff - DAT_008087E3;                        // channel 1: INVERT raw reading
DAT_0080835C = ((0xff - DAT_008087E3)*0x20 + DAT_0080835C*0x17) / 0x18;   // smooth (stored x32)
DAT_008087FB = FUN_00045070(&DAT_0000807E, 0, ...);        // linearize via ROM table

DAT_008087FA = 0xff - DAT_008087E4;                        // channel 2: same shape
DAT_0080880D = FUN_00045070(&DAT_000081E8, 0, ...);        // different linearization table
```

The `0xFF - raw` inversion is a **thermistor signature** — an NTC thermistor's voltage falls as temperature rises, so the firmware inverts it to get a value that climbs with temperature. Two channels = **two temperature sensors**.

### The linearization tables

- **Channel 1: `0x00807E`** — 45 records
- **Channel 2: `0x0081E8`** — 41 records

Both in the 8-byte record format (§8e), read as `[adc_in, temp_out, adc_next, temp_next]` pairs. The output column steps in clean 5s (`15, 20, 25 … 195, 200, 210, 215 …`) against a non-linear ADC curve that flattens at both ends — textbook thermistor linearization.

### Encoding: **(stored byte − 40) = °C** — CONFIRMED

Both tables map the full ADC range `0..255` onto output `0..255`. With the −40 offset that is exactly **−40 °C to +215 °C** — the standard automotive unsigned temperature encoding (−40 being where °C and °F coincide). The no-offset reading (0..255 °C) is impossible: it could not represent sub-zero temperatures at all, and 255 °C is far beyond ATF's thermal breakdown.

**Validated against the factory service manual**, not just internal consistency:

| ROM constant | raw | as (raw−40) | manual reference |
|---|---|---|---|
| `0x012930` | 111 | **71 °C** | inside manual's stated normal operating range **70-80 °C** |
| `0x012945` | 115 | **75 °C** | inside the same 70-80 °C range |
| `0x00EFC7` | 95 | **55 °C** | exactly the top of the manual's test range **45-55 °C** |
| `0x008690`, `0x011894/96` | 0 | −40 °C | encoding floor, used as a min sentinel |
| `0x008466/67`, `0x00EF8C/8D` | 255 | 215 °C | encoding ceiling, used as a max sentinel |

Three independent constants landing inside two different manual-published temperature ranges settles it.

### Temperature thresholds found (23 constants)

All decode to sensible ATF temperatures: `-10, -5, 15, 38, 55, 65, 71, 75, 95, 125, 135, 139, 145 °C` plus the −40/215 sentinels. Full address list: `0x00806E, 0x00806F, 0x008466, 0x008467, 0x008690, 0x008693, 0x00EF85, 0x00EF86, 0x00EF87, 0x00EF8C, 0x00EF8D, 0x00EFC5, 0x00EFC7, 0x01000A, 0x011894, 0x011896, 0x011CF6, 0x012930, 0x012944, 0x012945, 0x012E28, 0x012E29, 0x01C3BE`.

**Four with fully-traced roles were added to the definition file** (in °F, per user preference), under a new "Transmission - Temperature" category:
- **`0x01000A` = 15 °C** — *Cold ATF 5th Gear Lockout*. Gated on `current gear == 5th`: below this temperature the TCU substitutes the disabled/placeholder shift table (`0x176A2`), i.e. it withholds 5th until the fluid warms. A genuinely useful tuning parameter.
- **`0x011CF6` = 95 °C** — *Assumed ATF Temperature*. Substituted when the measured value is flagged unusable — a deliberately warm fallback so a failed sensor doesn't make the TCU behave as if cold.
- **`0x00806E` = −10 °C / `0x00806F` = −5 °C** — a *cold switchover hysteresis pair* selecting between two calibration constants.

The remaining 19 are documented here but not shipped — their exact roles aren't individually traced, and naming them speculatively in a file meant for real edits is the failure mode already corrected twice (§11d, §11n).

**Note on temperature-indexed tables**: the tables that take temperature as their X-input (`0x011854`, `0x01186E`, `0x008428`, plus the byte-keyed pointer-array searches at `0x012720`/`0x012758`/`0x0125F8`) are all in the 8-byte record format — still blocked from RomRaider by the stride issue (§11p), pending the 3D-schema test. None of the contiguous-format tables use temperature directly.

**Confirmed real-world scale factors now: 3** — gear ratios (÷1024, §11r), engine speed (÷8, §11s), temperature (−40 °C, §11t).

---

## 11u. Line pressure: there is NO pressure sensor on this transmission

Worth recording explicitly, because it redirects the pressure hunt entirely. The factory service manual's own Line Pressure Test procedure requires **removing a test plug and installing a mechanical oil pressure adapter (ST 498897200) and gauge (ST 498575400)**, then *separately* reading *"P/L solenoid target oil pressure"* off the Subaru Select Monitor to compare against it. If the TCU had a line pressure sensor, the gauge would be unnecessary — you would simply read actual pressure on the scan tool.

Corroborated by our own DTC table (§11f): `P0745/P0746/P0748/P074C` are all **Pressure Control Solenoid** codes — an *output* — and there is no pressure-*sensor* circuit code anywhere in the table. §8d's `0x008094E0/E4/E8/EC` were likewise identified as pressure-**switch** (on/off) feedback bits, not analog.

**Conclusion: line pressure is commanded open-loop via a duty solenoid; there is no analog pressure input to find.** The correct target for pressure units is therefore the **computed kPa target** the TCU reports to the scan tool — which the manual pins down precisely (D range closed throttle **490 kPa**, D full open **1370 kPa**, R closed **1370 kPa**), giving exact validation values for any candidate scale factor. That is the next pressure lead, not a sensor input.

---

## 11v. Published to GitHub — repo layout and what was excluded

Public repo: **https://github.com/TomFLV/5eat-tcu-reverse-engineering** (owner `TomFLV`).
Local clone at `C:\Users\Tom\Desktop\5eat-tcu-reverse-engineering` — **separate folder** from
this working directory (`C:\Users\Tom\Desktop\5eat tcu reverse engineering`). Don't confuse them.

**Published layout** (tools are repo-relative there, NOT flat like the working folder):
`README.md`, `LICENSE` (MIT, explicitly scoped to exclude the ROM/decompile),
`docs/{ROMRAIDER-SETUP,ROM-DETAILS,TECHNICAL-NOTES}.md`, `definitions/`, `tools/` +
`tools/ghidra/`, `decompiled/`, `rom/`.

**Deliberately excluded** (third-party copyright — cited, not redistributed):
`forum_full_thread.txt`, `subaru_5eat_service_manual.pdf` and its text extract.
Also excluded: `FINDINGS.md` itself — it's a working log; `docs/TECHNICAL-NOTES.md` is
the cleaned public version. `table_catalog.txt` is gitignored (regenerable).

**Fixes made during publication that also matter here:**
- Four tools had hardcoded `OneDrive\Desktop` paths (one pointed at a temp scratch dir)
  and would fail for anyone else. Fixed in the repo copies only — **the working-folder
  copies at `tools/` still use the old flat paths**, which is correct for this folder.
  If syncing tools between the two locations, the path constants differ intentionally.
- `checksum.py` had no CLI at all (just a `__main__` with a hardcoded path). The repo
  copy now has proper `--verify` / `--fix` / `-o` argparse handling.
- `.gitattributes` marks `*.bin` binary — verified the committed ROM blob's SHA-256
  matches the local file exactly, so line-ending conversion didn't corrupt it.
- The def file's descriptions referenced `FINDINGS.md §11x`; repointed to
  `docs/TECHNICAL-NOTES.md` with the section numbers dropped.

**Note on commit style for this project**: commits carry no AI/tool attribution — no
`Co-Authored-By` trailer, no generated-with footer. Keep it that way.

---

## 11w. SECOND ROM: `91FE216300` (512KB variant, Early 2005 USDM Outback XT) — checksum generalized, port path mapped

User supplied a second ROM: **`91FE216300.bin`**, from an **Early 2005 USDM Outback XT** (their identification). Working copy in the project folder; an identical date-stamped original is at `C:\Users\Tom\Downloads\91FE216300_2026-03-21_18h17m30s.bin` (looks like a tool-generated vehicle read). SHA-256 `ccd65cf2bbe96c009ca9bde8cfc2bbd59fe23372edd63968d9d700ed6e58703d`.

**It is the larger M32R variant** — 524,288 bytes (512 KB) vs our 384 KB. Same M32R *architecture* (so the whole Ghidra/decompiler toolchain transfers unchanged), different chip: `M32176F4` rather than `M32170F3`/`M32174F3`. This matches the forum's statement that 05-06 USDM TCUs use MCU `WA12212963WWN` vs our `wa12212953www`, and matches the user's vehicle ID. It is **not** the unrelated Denso SH7058 unit.

Identity block, same layout as ours:

| Offset | `91D1206000` (ours) | `91FE216300` (new) |
|---|---|---|
| `0x8000`/`0x8004` | `0x2668221C` | `0xF70D361C` |
| `0x8008` cal ID | `MB431M  VF000` | `MB436G  VF305` |
| `0x8018` | `R9H` | `QS1` |
| `0x802A` ROM ID | `91 D1 20 60 00` | `91 FE 21 63 00` |

### Checksum — same algorithm, and the tool had a latent bug

Neither the whole-file sum nor FastECU's `0x5AA5A55A` variant matched. Solving for the range showed the checksummed region is **`0x00000`-`0x60000`** — exactly 384 KB, the *same* region as our ROM. The trailing `0x60000`-`0x80000` is **100% `0xFF` blank** and excluded.

So the rule generalizes: **checksum = −(sum of BE32 words in the first 0x60000 bytes, excluding both slots)**. On a 384 KB image "first 0x60000" and "whole file" are identical, which is why this was never noticed — `tools/checksum.py` assumed whole-file and would have produced a value exactly `0x80000` too high on any 512 KB ROM. **Fixed** (`CHECKSUM_REGION_END = 0x60000`) in all three copies (working folder, WSL, public repo); re-verified against both ROMs, no regression.

This also retires the §11j open question: FastECU's `checksum_1` is not for this variant either.

### What transfers, found by byte-pattern search of our known blocks

| Block | Location in new ROM | Delta |
|---|---|---|
| DTC table | `0x004090` | **+0, byte-identical** (same 19 P07xx codes) |
| Temp linearization ch1 | `0x008080` | +2 |
| Temp linearization ch2 | `0x0081EA` | +2 |
| Speed Trim A g1 | `0x01049A` | +144 |
| CAN 0x410 curve | `0x01192C` | +148 |
| Gear ratios | `0x0124DC` | +400 |
| Slip Detection g1 | — | **content differs** |
| Reference Speed g1 | — | **content differs** |
| Shift schedule `0x15CA8` | — | **content differs** |

Two clean conclusions:
1. **Sensor/linearization/structural data is shared and merely relocated**, by a small offset that grows through the file (+0 → +2 → +144 → +148 → +400) — consistent with data being inserted, not the layout being redesigned. All three confirmed unit scales (gear ratios ÷1024, temperature −40 °C, and by extension engine speed ÷8) should therefore hold for this ROM too.
2. **The tables whose content differs are exactly the vehicle-specific calibration** — slip thresholds, reference speeds, shift schedules. Precisely what you'd expect to change between a JDM Legacy and a USDM Outback XT. Those differences are the interesting part for tuning comparison.

Note the gear-ratio pattern appears **three times** in the new ROM (`0x00844C`, `0x0124DC`, `0x015918`); `0x0124DC` is the true counterpart, identified by its trailing context (`…, 0, 9500, 1`) matching our `0x01234C` exactly.

### Porting path (not yet done)

Byte-pattern searching our known table contents against a new ROM is a reliable, automatable way to relocate them — which `tools/find_rom_offsets.py` now does. For tables whose content genuinely differs, fall back to locating them via the same call-site enumeration used originally (§11o), which requires decompiling this ROM separately. **Since resolved:** `91FE216300` now carries a full definition alongside the rest of the M32R family.

---


## 11x. SHIFT SCHEDULE FULLY DECODED — axes are Vehicle Speed (km/h) and Accelerator Angle (%)

A chart posted in the forum thread (`ShiftCurves.PNG`, "5EAT Shifting, Base Case")
plots **Accelerator Opening Angle (%)** against **Vehicle Speed (km/h)** with
exactly 4 up-shift and 4 down-shift curves. Testing our own table data against it
confirms the encoding outright.

### Encoding (CONFIRMED)

Each 8-byte record is `[speed_i, pedal_i, speed_i+1, pedal_i+1]` — a **line segment**
of a polyline in speed/pedal space. Fields C/D are simply the next record's A/B,
which is why the earlier read of "redundant lookahead" looked odd.

- **Field A / C = Vehicle Speed, km/h** — direct, no scale factor.
- **Field B / D = Accelerator Opening Angle**, raw 0-255 mapping to 0-100%.

### Validation against the chart

| Curve | Our data (km/h @ pedal) | Chart |
|---|---|---|
| 1 Up | 12 @ 19% -> 43 @ 100% | ~10 -> ~40 |
| 2 Up | 26 @ 19% -> 87 @ 100% | ~19 -> ~75 |
| 3 Up | 44 @ 19% -> 144 @ 100% | ~18 -> ~132 |
| 4 Up | **58 @ 16%** -> 217 @ 100% | **~57 @ 16%** -> ~205 |
| 4 Down | 42 @ 13% -> 202 @ 100% | matches dashed yellow |
| 1 Down | 8 @ 50%, 10 @ 63%, 11 @ 88% | matches dashed blue |

The `(58 km/h, 16%)` start of the 4-Up curve is a fingerprint-level match.

### Slot A/B resolved

- **Slot A = upshift from that gear. Slot B = downshift from that gear.**
- Gear index 0 (1st) has no slot B — cannot downshift below 1st — and indeed its
  slot B is the shared placeholder `0x17698`.
- Gear index 4 (5th) has no slot A — no 6th gear — and its slot A is the
  placeholder `0x176A2`.

Both placeholders sit exactly where this interpretation predicts, which is strong
independent confirmation of the whole `gear x 2 + mode x 10` indexing from 11n.

### Consequence for RomRaider

Now that the meaning is known, the 3D-table route becomes far more attractive: the
record block is **contiguous**, so a `type="3D"` table with `sizex="4"`,
`sizey="n"` and the data address at the record base maps onto the physical layout
exactly, with columns *Speed (km/h) / Pedal (%) / next Speed / next Pedal*.
Columns 3-4 are redundant copies of the following row's 1-2 and would need to be
kept in sync by the editor — a real caveat, but the table becomes genuinely
readable and tunable rather than hidden.

**Still requires the live RomRaider test before shipping** (11p) — the schema
question is unchanged, only the value of answering it has gone up.

**Confirmed real-world scale factors now: 5** — gear ratios (/1024), engine speed
(/8), temperature (-40 C), vehicle speed (km/h direct), accelerator angle
(raw/255 = 0-100%).

---


## 11y. TEN firmwares mapped — bulk porting via call-site enumeration

Ported the table definitions to eight further firmwares. **Ten of the eleven M32R
images are now mapped**, all selected automatically by cal ID in a single
definition file.

### Method

Per ROM: run the generic seeder + decompiler (`SeedAuto.java`, `DecompileAll.java`),
then locate the lookup routines and enumerate their call sites. The three
interpolation variants sit at fixed relative offsets (`main`, `main+0xD8`,
`main+0x1A4`), so finding the main one locates all three. Main routine per ROM:

| Firmware | interp | Firmware | interp |
|---|---|---|---|
| 91D1206000 (base) | `0x4515C` | ACD1207000 / ACD1A06000 | `0x46DC0` |
| 91FE216300 / 91D0207500 / 91F0217100 / 91D1207900 | `0x451D8` | AAD1A07100 | `0x451E8` |
| ABD1A03100 / ABD1207000 | `0x4540C` | ADE0236000 | `0x46DB8` |

Every firmware issues the **same 12 table call sites in the same address order**,
so roles map positionally. Firmwares that carry the two extra tables below
`0x10500` have them dropped before matching.

### The offsets are NOT extrapolable — two traps caught by verification

1. **The pointer-array delta is not the gear-table delta.** Deriving family offsets
   from the pointer array address produced addresses that looked plausible and were
   wrong. The arrays must be **dereferenced** and the offset computed from the
   actual first gear table.
2. **`SpeedTrimA` is +142 where every other family in the same ROM is +144** — on
   five separate firmwares. Nothing about the surrounding structure predicts this.

Both were caught by `verify_profile`, which re-derives every address and compares
against the target ROM's own embedded count field, refusing to emit a definition
if any disagree. Neither would have been caught by inspection.

### Verified offsets

| Firmware | SpeedTrimA | Pressure B/C, E | ShiftStageD | Slip / RefSpeed / CAN |
|---|---|---|---|---|
| 91FE216300, 91F0217100 | 144 | 144 | 144 | 148 |
| ABD1A03100, ABD1207000 | **142** | 144 | 144 | 148 |
| 91D0207500 | 44 | 44 | 44 | 48 |
| 91D1207900 | **42** | 44 | 44 | 48 |
| AAD1A07100 | **162** | 164 | 164 | 168 |
| ACD1207000, ACD1A06000 | **142** | 144 | **96** | 100 |

Note the 512KB `MB558xx` pair splits three ways across regions — the clearest
evidence that no single global shift exists.

### Not yet mapped

`ADE0236000` (`MB562EH1`) has **13** table call sites rather than 12 — one more
than every other firmware. Positional mapping is therefore unsafe for it and it
is deliberately excluded until the extra site is identified. Its decompiler output
is published so the work can be done.

Note also that `ABD1207000`, `ACD1207000` and `ACD1A06000` emit 53 tables rather
than 72: their DTC tables did not match the expected record layout at `0x4090`, so
none were emitted for them. Worth investigating — these are the later
calibrations and may relocate the DTC table.

---

## 11z. Attribution corrected

The repository previously implied more ownership than is accurate. Fixed in both
README and LICENSE:

- **The ROM images are not ours.** All except `91FE216300` were dumped and shared
  by members of the RomRaider forum thread. Included so work can continue, with an
  explicit offer to remove or re-credit on request.
- **`docs/shift-curves-reference.png` is not ours.** It was produced by a forum
  member and is what the shift-schedule units were verified against — the km/h and
  pedal-% encoding could not have been confirmed without it.
- **The tooling that makes any of this possible is not ours**: FastECU
  (Miika Syvänen), rimwall's OEM fork, FreeSSM (Comer352L), and the ghidra-m32r
  processor module (ripnet).
- The MIT grant now explicitly covers **only** `tools/`, `definitions/` and
  `docs/` written analysis.

---


## 12a. ALL ELEVEN FIRMWARES MAPPED — remaining gaps closed

Everything in `rom/` is now mapped: 11 `<rom>` blocks, each carrying tables, shift
schedule curves and DTC switches, auto-selected by cal ID.

### Shift schedule arrays (per firmware)

The `gear*2 + mode*10` pointer array relocates and cannot be offset-derived. Found
by fingerprinting that index expression in each decompiler output:

| Firmware | Array | Firmware | Array |
|---|---|---|---|
| 91D1206000 | 0x17714 | 91D1207900 | 0x17828 |
| 91FE216300 | 0x174B4 | AAD1A07100 | 0x17AAC |
| 91D0207500 | 0x17DD4 | ABD1207000 | 0x17F9C |
| 91F0217100 | 0x176F8 | ACD1207000 | 0x180F0 |
| ABD1A03100 | 0x17F5C | ACD1A06000 | **0x180E8** |
| ADE0236000 | 0x180DC | | |

All eleven yield **8/8 real curves**. The ACD1A06000 result independently
reproduces the `0x180E8` address rimwall stated in the thread, and its first curve
at `0x01683C` — agreement from two directions.

### DTC table is not at a fixed address

Hardcoding `0x4090` silently produced **zero** DTC tables for the later
calibrations. The `MB5300` / `MB558xx` / `MB562xx` firmwares relocate it and carry
a **different code set**: `P072C, P0730, P0734, P0736, P0760, P0764, P0770, P0780,
P0794, P07D0` rather than the `P0700`-onward sequence. Now located by scanning the
`0x4000` block for the longest run of 8-byte records with a valid `P07xx` code.

### ADE0236000's extra call site

It had 13 table call sites, not 12 — an extra signal-response curve at `0x0119C4`
(a second `C`-variant alongside `0x0119E2`). Dropping it restores the standard
twelve; all eight families then verify.

### Traps that verification caught (none findable by inspection)

1. **Pointer-array delta != gear-table delta.** Using the array offset produced
   plausible, wrong addresses. The arrays must be dereferenced.
2. **`SpeedTrimA` is +142 where every other family in the same ROM is +144** — on
   five firmwares.
3. **The 512KB `MB558xx` pair splits three ways**: +144 / +96 / +100 by region.
4. **DTC table relocation**, above.

Every one was caught by `verify_profile` re-deriving each address and comparing
against the target ROM's own embedded count field.

### Attribution

Confirmed: the shift-curve chart and the shift-table encoding are **rimwall's**
work. README and LICENSE now credit him by name, list ~20 further thread
contributors, and state plainly that the ROM images, the chart and the dumping
tooling are not ours. The MIT grant covers only `tools/`, `definitions/` and the
written analysis.

---


## 12b. RomRaider CLI verifier — the definition now verifies against RomRaider itself

Built a headless verifier (`tools/romraider-cli/DefCheck.java`, published) that
loads a definition and a ROM using **RomRaider's own parser** and reports what it
produced. Nothing in it re-implements the schema.

**Why this is a different check from everything else here.** All the existing
verification compares addresses against *the ROM*. This compares the definition
against *RomRaider*. A definition can have perfect addresses and still be silently
ignored — which is exactly what happened earlier in this project with the
fabricated `Z Axis` element (11d): every address correct, every self-check
passing, tables invisible in the GUI.

### Result — all eleven firmwares

| | |
|---|---|
| Cal-ID match | every ROM resolves to its **own** `<rom>` block out of 11 |
| Tables built | 81 (384KB cals) / 86 (later cals) |
| Faulty tables | **0** |

This confirms the cal-ID auto-selection mechanism works, which the whole
multi-firmware design depends on.

### Two traps, both silent

1. **RomRaider cannot run truly headless.** `Settings.<init>` calls
   `getScreenSize()`, so `xvfb-run` is mandatory. Headless mode throws
   `HeadlessException` from deep inside static init.
2. **Without `~/.RomRaider/settings.xml`, `SettingsManager.load()` opens a modal
   dialog** — under xvfb the process then hangs **forever with no output, no
   error, nothing on stderr**. Genuinely hard to diagnose; copy a settings.xml
   from a working install.

Also needs a JDK **with** AWT (`openjdk-21-jdk`, not `-headless`) — the headless
JDK omits `libawt_xawt.so`.

### Usage

```bash
xvfb-run -a java -cp "out:i18n:lib/*" DefCheck definitions.xml rom.bin [--tables]
./runall.sh     # every ROM
```

`NO MATCH` in the output means that ROM would open in RomRaider with **no tables
at all** — the single most important thing to catch before publishing a
definition.

**Correction to earlier notes in this document:** the definition is no longer
"untested in RomRaider". It has been through the real parser on all eleven ROMs.
What remains untested is only GUI rendering/editing behaviour.

---


## 12c. Record-format curves EXPOSED — the stride objection was wrong

35 record-format ("hysteresis") curves are now editable, on top of the 8 shift
curves. Base ROM: **81 -> 116 tables**.

### The reasoning that blocked these was wrong

From 11p onward this document said the format could not be exposed because
RomRaider has no stride attribute. **The fields are interleaved at an 8-byte
stride, but the record block itself is contiguous.** A `type="3D"` table with
`sizex=4` (the four fields) and `sizey=n` (the records) maps onto the raw bytes
exactly. No stride support is needed. RomRaider's own parser accepts all of them.

Worth remembering as a category of error: a correct observation (fields are
strided) led to a wrong conclusion (therefore unexposable), and it stood
unchallenged for a long time because it sounded technical enough.

### Method

Enumerate every call site of the record-lookup routine, read the table pointer
from the argument, then **filter to curves whose breakpoint column is monotonic**.

That filter is load-bearing. It rejected 11 of 46 candidates — mostly the
gear-indexed pointer arrays, which walk as plausible-looking tables of 41-45 rows
and would have shipped addresses pointing at pointer bytes.

### What was found

| Group | Count |
|---|---|
| Signal response curves | 16 |
| Engine speed curves | 6 |
| Temperature curves | 3 |
| Solenoid output curves | 3 |
| Reference speed curves | 3 |
| **Sensor calibration** | **2** |
| CAN signal / uncategorised | 2 |

The two sensor-calibration tables are the most consequential: `0x00807E` and
`0x0081E8` are the **temperature sensor linearisation curves** — the calibration
defining what the ATF sensors actually read. Editing them moves every
temperature-dependent decision in the TCU.

### Porting: 5 of 10 firmwares, and why not more

Positional matching against the base's call-site order is only safe where the
counts match. Five firmwares match exactly (35/35) and are included. Five issue
34 or 36 call sites.

Tried aligning those by row-count signature (difflib on the sequence of row
counts). It reached only 28/35, and the signature has heavy repetition — `12`
appears nine times — so the alignment could pair the wrong curves undetectably.
**Rejected and not shipped.** Those five keep their fully verified 56-64 tables.

### Current state

| | |
|---|---|
| Firmwares | 11, all mapped |
| Tables | 116 base / 99 (5 firmwares) / 56-64 (5 firmwares) |
| Validator | 1295 checks, all pass |
| RomRaider parser | 11/11 match, **0 faulty** |
| Confirmed units | 5 |

---


## 12d. PRESSURE UNITS — negative result, with evidence. Do not re-attempt from the ROM alone.

Line pressure in kPa is **not stored in these ROMs**. Four independent tests, all
negative, now across all eleven firmwares rather than one:

| Test | Result |
|---|---|
| Manual kPa values (1370/490/1925/900/1235/1475/1530) as code immediates | **0 hits** in all 11 decompiles |
| Monotonic calibration runs spanning the 385-1925 kPa bands | only known speed tables (values >2000) |
| Record-curve value ranges scanned for a pressure-shaped span | one candidate, 512-2048 -- powers of two, a scaling table |
| `490` AND `1370` both present in the calibration region (0x8000-0x1D000) | **1 of 11 firmwares** |

Also tried the obvious rescalings (/2, x2, /4, /8, /10) as adjacent pairs: 0/11
for every meaningful one.

**The last test is the decisive one.** 490 and 1370 kPa are transmission *specs* --
the same physical transmission across every variant here. Had the TCU stored them,
they would appear in all eleven. Appearing in one is what chance produces in 384 KB.
Both values do occur *somewhere* in every image, but scattered outside the
calibration region, which is the signature of coincidence rather than storage.

### Most likely explanation

The TCU reports a raw duty or target value over SSM and **the Subaru Select Monitor
performs the kPa conversion itself**. That is normal for factory scan tools, and it
is consistent with the rest of what we know:

- There is no pressure *sensor* (11u) -- the manual has you fit a mechanical gauge.
- The DTC table at 0x4090 likewise has no reader in the ROM; the diagnostic
  presentation layer simply is not on the TCU side.

Code coverage was checked before concluding this: the decompiled output holds 1056
functions spanning 0x000168-0x05F4C4, and every gap over 2 KB is either the known
blank region (0x5AD4-0x20000) or bank padding. The conversion is not hiding in
unanalysed code.

### What would actually settle it

1. **A Select Monitor / SSM parameter definition for the TCU** giving the address
   and formula. FreeSSM ships no TCU-specific one, but its shared measuring-block
   list combined with the ROM's own SSM table supplies both - section 40.
2. **Empirical logging** -- read the raw variable over K-Line SSM while watching the
   Select Monitor's kPa readout, and derive the mapping from the pairs.

Both need hardware. **Neither is a static-analysis problem, and further ROM
searching will not resolve it.**

---


## 13a. CORRECTIONS from rimwall + the real 32176 datasheet — several earlier findings were WRONG

rimwall replied on the repo and raised four points; the CAN decoding thread and the
genuine Renesas manual settle several open questions and **overturn three findings.**

### 1. The "DTC table" at 0x4090 does not exist — REMOVED

rimwall: *"Something is not right with those DTC addresses - this part of the ROM is
just general initialisation of ports etc."* He is right.

`0x4090` is **M32R instruction stream** inside `FUN_00004000`:
```
00004080: a041 0074  a041 0078  a041 007c  6200 f000
00004090: a241 0700  6200 f000  a241 0704  6200 f000
```
`a041`/`a241` are opcodes; `0x0074, 0x0078, 0x007C, 0x0700, 0x0704 ...` are their
**displacement operands**, incrementing by 4 because they address consecutive
words. Independently corroborated by the datasheet: the **Port Data/Direction
register block is at `H'0080 0700`-`077F`** — exactly the operand values being
written. It is port initialisation.

Root cause: I scanned for uint16 in `0x0700`-`0x07FF`, found a cluster, and assumed
P07xx without checking whether the bytes were code. Missed tells: codes
incrementing by exactly 4 (no real SAE list does), and **zero data references to
0x4090**.

**This was a safety issue, not cosmetic.** Each generated switch's "off" state
zeroed bytes 2-3 of a "record" — instruction operands — so toggling one would have
corrupted boot code. All DTC tables removed from all 11 firmwares.

Where the real DTC data is: transmitted on **CAN 0x422 bytes 3-4** as
`[2-bit index][14-bit DTC number]`, cycling through up to 4 active codes. Find the
code that builds that message.

### 2. Ghidra M32R language — we were on the OLD upstream version

rimwall's fork is **4 commits ahead** of `ripnet/ghidra-m32r`. An earlier check
here concluded "unchanged from upstream" — that was wrong; the compare API returned
"Not Found" and I misread it as "no differences".

The key fix: **FPREL base corrected from `0x80C000` to `0x808000`.** Every
FP-relative access in our old decompiles resolved **0x4000 too high** and showed as
opaque `*(in_FP + -0x3a26)`.

Effect on the base ROM decompile:

| | old | with rimwall's fixes |
|---|---|---|
| opaque `in_FP` expressions | **742** | **0** |
| `CARRY4` clutter | **1014** | **0** |

Example: `(short)(*in_FP + -0x3a26) + 0x8000` becomes `DAT_008045DA + 0x8000`.

Install: `git clone https://github.com/rimwall/ghidra-m32r`, copy `m32r.sinc`, then
recompile the `.sla`. Only `m32r.sinc` differs (74 lines).

### 3. The "5-channel solenoid PWM bank" was wrong twice over

I reported a PWM output bank at `0x8047EA`-`0x8047F2`. Both parts were wrong:

- The **address** was inflated by the `0x4000` FPREL bug. It is `0x8007EA`-`0x8007F2`.
- The **peripheral** is not PWM. The datasheet register map shows
  `H'0080 07E0`-`07F2` is the **Interrupt Controller**. The boot code was writing
  interrupt control values.

### 4. Authoritative memory map (32176 Group User's Manual, Renesas Rev 1.01)

Manual saved as `m32r_32176_user_manual.pdf` (5 MB) with text at `m32r_manual.txt`
(42,545 lines). Source: CERN's component datasheet archive.

| Range | Contents |
|---|---|
| `H'0080 0000` | **SFR area** base |
| `H'0080 0080`-`0087` | A-D0 control registers |
| `H'0080 0090`-`00A6` | **A-D0 Data Registers 0-11** (12 channels, 10-bit) |
| `H'0080 0700`-`077F` | Port Data / Direction registers |
| `H'0080 07E0`-`07F2` | Interrupt Controller |
| `H'0080 4000`-`9FFF` | **Internal RAM** (24 KB) |

RAM ending at `0x809FFF` is consistent with every RAM variable found in this
project (highest seen ~`0x8096xx`).

**Not yet resolved:** no code reads `0x800090`-`0x8000A6` directly, so the ADC
results reach RAM by some other path (DMA, or computed pointers). Identifying which
ADC channel feeds each temperature sensor still needs that path traced.

### 5. RomRaider version requirement

rimwall on 0.8.2: *"couldn't load the Shift Curves - I get an error message 'There
was an error loading table'"*. Our 3D tables verify on **1.0.0** via the CLI
verifier. Definition now states 1.0.0+ is required.

### 6. Confirmations (not corrections)

The CAN thread independently confirms three of our derivations:

- **CAN 0x410 bytes 5:6 = Engine Speed (rpm)** — matches our trace exactly, and
  supports the `raw/8` axis scale.
- **ATF temperature = value − 40 °C**, with **two sensors** (pan + torque
  converter) — matches our two thermistor channels and the `−40` offset.
- **CAN 0x412 byte 0 = APA (Accelerator Pedal Angle) at ×100/255** — this is
  `DAT_008087D0`, the previously-unidentified operand in the Pressure Control
  X-formula. Also independently confirms the pedal-angle scale derived from the
  shift chart.

Also newly known: **CAN 0x511 is from VDC/ABS** (bytes 0-1 steering angle, byte 6
G-force); our `0x011836` curve is indexed by its byte 4, which the community
decoding still lists as unknown.

---

## 12. Next steps (in order)

### Open, ranked

1. **Record curves for the 5 unmapped firmwares** (`ABD1A03100`, `ABD1207000`,
   `ACD1207000`, `ACD1A06000`, `ADE0236000`). They issue 34 or 36 record-lookup
   call sites against the base's 35, so positional matching is unsafe. Row-count
   alignment was tried and reached only 28/35 with heavy repetition in the
   signature — **rejected, do not ship it**. Needs per-firmware call-site tracing.
   Would take them from 56-64 tables to ~99.

2. **DTC flags field** (`0x4090` records, `[flags:u16][code:u16][data:u32]`).
   Still undecoded, which is why every DTC "off" state carries an experimental
   warning. Caveat: the reader is not in our decompiled output — likely the same
   missing diagnostic layer as the pressure conversion — so this may not be
   statically solvable.

3. **GUI render check** — needs a human at RomRaider. The parser accepts all 116
   tables; nobody has looked at how the 3D shift curves *display and edit*.

4. **CAN IDs still unidentified**: `0x411`, `0x512`, `0x513`, `0x515`, `0x520`,
   `0x600`. `0x740`/`0x741` remain a probable diagnostic pair, unconfirmed.

### Closed as dead ends — do not re-attempt

- **Pressure units from the ROM** (12d). Four tests across 11 firmwares, all
  negative. Needs hardware, not analysis.
- **FreeSSM as a source of TCU unit conversions** (11m). ~~No TCU definitions
  exist in any branch.~~ **Reopened and largely answered - see section 40.** There
  is no TCU-specific definition file, which is what 11m checked, but the shared
  measuring-block list names parameters by SSM address, and the ROM maps SSM
  address to RAM address.
- **A pre-existing RomRaider TCU definition** — none exists; the forum thread says
  so explicitly. This project's is the first.
- **Byte-pattern porting of table addresses between firmwares** — resolves only
  4 of 9 families unambiguously. Use call-site enumeration.

---

## 13. Session summary (2026-07-26)

Started with one ROM and a 50-table definition. Ended with:

| | |
|---|---|
| Firmwares | **11**, all checksum-verified and mapped |
| Tables | 116 (base) / 99 (5 firmwares) / 56-64 (5 firmwares) |
| Confirmed unit scales | **5** — gear ratio /1024, engine speed /8, temperature -40 C, vehicle speed km/h, pedal angle /255 |
| Validation | 1295 address checks + RomRaider's own parser, 11/11, **0 faulty** |
| Published | `github.com/TomFLV/5eat-tcu-reverse-engineering`, 27 commits |

**Biggest wins**

- **Shift schedule fully decoded** in real units, cross-confirmed against rimwall's
  chart *and* his written description of the encoding.
- **The stride objection was wrong.** Believing the record format could not be
  exposed cost weeks of "blocked" status. The fields are strided; the record block
  is contiguous. 43 curves now editable.
- **RomRaider CLI verifier** — checks the definition against RomRaider itself, not
  just against the ROM. Two real bugs surfaced immediately.

**Bugs the verification caught (none findable by inspection)**

1. Derived firmwares inheriting base-ROM addresses — one was building 24 DTC
   tables for a firmware with 11.
2. The validator only ever checking one ROM.
3. `SpeedTrimA` at +142 where every other family in the same image is +144.
4. Pointer-array delta not equalling gear-table delta.
5. Checksum region differing between 512KB variants.
6. DTC table relocating in later calibrations.

**Standing lesson:** every one of these passed a self-consistent check before being
caught by an *independent* one. Address checks verify against the ROM; the CLI
verifier checks against RomRaider. Different questions.

---


---

## 14. REAL UNITS EVERYWHERE, and LINE PRESSURE SOLVED IN kPa (2026-07-29)

### 14a. rimwall's M32R language is correct for this family — verified, not assumed

Every decompilation in the repo up to now was built with the upstream Ghidra M32R
language, which resolves fp-relative operands against `0x80c000`. rimwall's fork
changes that base to `0x808000`. Rather than take it on trust, the base was
recovered from the firmware itself.

`FPREL` in `m32r.sinc` models `LD Rdest, @fp(disp16)` — addressing off R13 — and
the SLEIGH rule substitutes a hardcoded absolute for R13's runtime value. The
source comment says as much: "hack to show the relative offset to FP". So the
whole language assumes a single fixed R13 for every image. The instruction that
establishes it is `LD24 R13, #imm24`, encoded `ED xx xx xx` on a 4-byte boundary.

Scanning for it:

    every 5EAT image contains EXACTLY ONE  LD24 R13, #0x808000     (15 of 15)

Not one image disagrees. Upstream's `0x80c000` was simply wrong, and every
`@fp(...)` access in the old output pointed `0x4000` past the variable it touched.
All sixteen decompilations were rebuilt.

`A3DE207100` has no `LD24 R13` at all and its 24-bit immediates look nothing like
the rest of the family — it is not a 5EAT TCU image, and is excluded.

### 14b. Record arrays split per quantity — skipCells IS a stride

The four-column record tables were unreadable, and not for a cosmetic reason.
RomRaider scales a table as a whole. A record is `4 x uint16` holding two
different physical quantities interleaved, so a grid containing both a speed and
a pedal angle cannot carry a unit at all — every cell had to be shown as a raw
integer. The long column headers were clipped to "Spee..." as well, because
`DataCellView` fixes every cell at the 42x18 default in `Settings`.

`Table3D.populateTable` advances the element offset by `1 + skipCells` after the
LAST cell of each row. With `sizex=1` every cell is the last in its row, so the
stride applies to all of them: `skipCells=1` walks every second `uint16`. That is
exactly one quantity out of the interleaved array, in order, with nothing skipped
and nothing invented — so each table can carry its own real unit.

Confirmed by rendering rather than by reasoning: the pedal table reads 0.0, 0.0,
18.8, 25.1, 25.1, 37.6 ... against raw records [0,0,12,0], [12,48,17,64],
[17,64,22,96] — i.e. 48/255 = 18.8%, 64/255 = 25.1%.

### 14c. LINE PRESSURE IN kPa — §12d was right about where NOT to look

§12d closed pressure units as a negative result "from the ROM alone". That
qualifier turned out to be the whole answer. There is no conversion in the ROM
because the firmware already works in kPa.

The FSM line pressure test (5AT-35) says the TCU reports "P/L Solenoid Target
Pressure" to the Subaru Select Monitor **in kPa**, and specifies:

    D range, throttle full closed    490 kPa
    D range, throttle full open     1370 kPa
    R range, throttle full closed   1370 kPa

Searching for 1370 as a big-endian `uint16` finds it seven times at a 4-byte
stride, in every firmware, at an address that relocates between them. The layout
is an array of 4-byte records:

    [engine speed x 8, pressure in kPa]

terminated by breakpoint `0xFF00` = 65280 = 8160 RPM. The breakpoint column uses
the /8 engine-speed scaling already confirmed elsewhere, so BOTH columns carry a
confirmed unit. Consistent across all eleven firmwares: two curves each, 1370 kPa
and 953 kPa, seven records apiece.

NOT confirmed: which hydraulic circuit each curve governs. The value is flat
across engine speed within each curve and the consuming function has not been
traced, so they are named for what they demonstrably contain.

Note this also means the "Pressure Control B/C/E" families are NOT pressures in
kPa. Their values (flat 20, or 6/6/6/10/10 by gear) are corrections, and calling
them pressures was always a slight misnomer.

### 14d. Engine speed ceiling: 8191 RPM, and it cannot be raised

Engine speed is `uint16` scaled by 1/8, so 65535 raw is 8191 RPM. That is a limit
of the stored format, not of the editor, and rescaling to reach a higher number
would misstate what the TCU reads.

There is genuine headroom for a built engine — the highest breakpoint anywhere in
the eleven firmwares is 8160 RPM (65280 raw, in the SlipThreshold axis of
91D1206000), deliberately parked just under the ceiling — but a target above
8191 RPM is not representable.

This also re-confirms /8 against the alternatives: under /4 that same 65280 would
read 16320 RPM, which is nonsense for an engine.

### 14e. Verification extended, because it was checking the wrong bytes

`Verify3D` computed expected offsets as `base + (y*sx + x)*2` — contiguous
row-major. Once tables became strided that would have silently validated the
wrong addresses. It now recomputes the same `1 + skipCells` rule, and the XML
validator learned both record geometries (8-byte arrays ending in `0xFFFF`,
4-byte arrays ending in an `0xFF00` breakpoint).

    validator:  1560 checks across 11 firmwares, no errors
    Verify3D:   640 3D tables, 12844 cells, 0 mismatches

Also added `RenderTable`, which draws a table through RomRaider's own view
classes to a PNG. Reading values back through the API proves the numbers are
right; it does not prove the table is presented in a form anyone would recognise.
That gap had already hidden one real defect — the 3D tables were `userlevel=4`
and so filtered out of the tree by `Rom.java:169` while loading perfectly.

### 14f. Local LLM: no contribution

A sweep over the decompiled call sites using qwen2.5-coder:14b on a 12GB card
returned nothing usable — all 108 samples errored, and ollama 0.32.5 returns
zero-value stubs from both `/api/generate` and `/api/chat` on this machine while
the CLI works. The tool was not published. Every result in this section came from
byte analysis and the service manual.

### 14g. Shipped

RomRaider now lives in `romraider-5eat/` with its patches, launchers and a
`build-standalone.sh` that reproduces the package from upstream source, and the
58.6 MB standalone Windows package is published as release v1.0.0.

---

## 15. THE SHIFT SCHEDULE IS ONE SLICE OF 82 THRESHOLD CURVES (2026-07-30)

### 15a. The scan

`tools/scan_threshold_curves.py` looks for arrays with the full shape of a known
shift curve: 8-byte records of 4 x uint16 terminated by a leading `0xFFFF`, field 0
ascending from 0 and under 400 (vehicle speed km/h), field 1 ascending within 0..255
(accelerator angle), and â€” the strongest filter â€” segments that chain, each record's
field 2 equalling the next record's field 0.

On `91D1206000` that finds **82 curves. The definition carries 8.**

They fall in two regions:

    0x015CA8 .. 0x0176AC    shift-schedule-shaped, in groups of eight
    0x018060 .. 0x0192D2    a second block, paired, different pedal ladder

### 15b. How they are indexed â€” mode x gear, several arrays

The curves are not referenced directly in the decompilation; they are reached
through pointer arrays. `FUN_000443d8` does:

    iVar2 = iVar3 * 5 + uVar4;              // iVar3 from DAT_00804858, uVar4 = gear
    DAT_008049e0 = (&PTR_DAT_0001a308)[iVar2 * 2];
    DAT_008049e4 = (&PTR_DAT_0001a30c)[iVar2 * 2];

So an array at `0x01A308`, two pointers per entry, indexed by `mode * 5 + gear`.
25 entries is 200 bytes = `0xC8`, which is exactly the spacing observed between the
pointer runs found by searching for the curve addresses as 32-bit big-endian values.
There are therefore SEVERAL such arrays, each a full mode x gear set, plus a second
pair of arrays at `0x01AAD8`/`0x01AADC`.

A dummy pointer (`0x00019324`) fills entries that have no curve, and the code
special-cases a few (mode, gear) combinations with hardcoded addresses rather than
going through the array.

This also confirms the earlier reading of the array at `0x17714` indexed by
`gear * 2 + mode * 10` â€” same structure, different base. The eight curves currently
in the definition are one (mode, condition) slice.

### 15c. What the curves DO â€” shift decision, not lock-up

`FUN_00040174` consumes them:

    bVar1 = FUN_00045070(DAT_008049e0, 0, DAT_008047fe);   // lookup on vehicle speed
    if ((DAT_00804879 < bVar1) || (bVar1 == 0xff))         // compare against pedal
        *pbVar2 = *pbVar2 | 4;                             // set a flag bit
    else
        *pbVar2 = *pbVar2 & 0xfb;

Two curves produce two flag bits (`0x02` and `0x04`) in `DAT_008054b8`, and a third
bit (`0x01`) is then set only when neither of the first two is. `DAT_008048a5`
selects between three variants of which curve pair to use, so it is a small state
machine.

Two threshold curves per (mode, gear), compared against pedal at the current speed,
producing want-up / want-down flags, is the shift decision. **These are more shift
schedules, not the torque converter lock-up.**

### 15d. Lock-up: NOT FOUND YET. Do not assume the above is it.

Searching for lock-up produced nothing usable:

- The factory manual has one qualitative paragraph (5AT-33, "LOCK-UP FUNCTION")
  and no schedule, thresholds or duty figures.
- The `0x018060` paired block looked promising - pairs are what an apply/release
  schedule looks like, and the pair sits at index 4 of its array, which is 5th gear,
  matching lock-up being a top-gear function. But it is reached by the same
  `mode * 5 + gear` arrays and consumed by the same shift-decision code, so the
  pairing is up/down, not apply/release.

The next probe should start from the OUTPUT, not the tables: find the code that
drives the lock-up solenoid duty and work back to whatever curve feeds it. The
candidates already in the definition as "Solenoid Output Curve 1-3 of 3"
(`0x00EE30`, `0x00EE6A`, `0x00EEA4`) are worth checking first - they are in
speed/pedal space and their consumer has not been traced.

Nothing has been added to the definition for lock-up. A category named "Lock-Up"
holding curves that turn out to be shift thresholds would be worse than no category
at all.

### 15e. The real opportunity here

74 of the 82 curves are not in the definition. They are per-mode and per-condition
shift schedules - which is to say, this transmission has several shift maps and the
tool currently exposes one of them. Mapping the pointer arrays properly would give
a Shift Map per mode instead of a single map, and that is a bigger win for anyone
tuning than any remaining unit conversion.

Scan any image with:

    python tools/scan_threshold_curves.py rom/<image>.bin --unmapped-only


### 15f. Repo tidy - the exploratory scripts were removed

The one-off probes cited in earlier sections are no longer in `tools/`:
`scan_rom.py`, `find_tables.py`, `extract_tables.py`, `find_checksum.py`, twelve
single-question Ghidra dump scripts, and `romraider-cli/DefCheck.java`.

Each answered one question that is now written up here, and each was hardcoded to a
single ROM. `DefCheck` in particular had to go: it reported "0 faulty" without ever
calling `populateTables`, so its result meant nothing, and a tool that reports
success without checking anything is worse than no tool. `Verify3D` replaced it and
reads the actual bytes.

What remains is the reproducible pipeline - generator, validator, checksum tool, the
two scanners, the plotter, and the two Ghidra scripts the decompilation actually runs
(`SeedAuto.java`, `DecompileAll.java`) plus the driver that produced `decompiled/`.
That driver was missing from the repo before, which meant the decompilation was not
reproducible from a clean checkout.

Licensing was also wrong and is now fixed. The root LICENSE is MIT and said so of
everything, but `romraider-5eat/patches/` are diffs against RomRaider - a GPL-2.0
program - so the patches and any build made from them are GPL-2.0-or-later. That is
recorded in `romraider-5eat/LICENSE`.

---

## 16. THE DTC TABLE, FOUND VIA THE CAN DECODING (2026-07-30)

DTCs were previously written off as not located. They are located now, and the CAN
decoding contributed to the forum thread is what did it - not pattern matching,
which is what produced the wrong answer last time.

### 16a. The encoder gives the search a signature

The thread documents CAN `0x422` bytes 3-4 as a 16-bit word whose top two bits are a
rotating DTC index and whose low 14 bits are the DTC number. A 14-bit mask is a very
specific thing to grep for, and `FUN_00032cac` contains exactly it:

    DAT_008047b6 = (ushort)DAT_008049b5 * 0x4000
                 + ((&DAT_008047b8)[DAT_008049b5] & 0x3fff);

`* 0x4000` is the index shifted into the top two bits, `& 0x3fff` is the 14-bit code.
`DAT_008049b5` is the index and increments `& 3`, so it cycles 0-3, matching the
thread's note that successive messages cycle through up to four codes.

### 16b. The table

The four RAM slots are refilled whenever the index wraps to 0:

    if (DAT_008049b5 == 0) {
        DAT_008047b8 = 0x3fff; ... DAT_008047be = 0x3fff;   // 4 slots, empty
        for (uVar4 = 0; uVar4 < 0xc; uVar4++) {             // 12 status bytes
            bVar1 = (&PTR_DAT_0001cdc4)[uVar4][2];          // 8 fault flags each
            bVar2 = 1;
            for (uVar3 = 0; uVar3 < 8; uVar3++) {
                if ((bVar1 & bVar2) != 0 && uVar5 < 4) {
                    (&DAT_008047b8)[uVar5] = (&DAT_0001ce18)[uVar4 * 8 + uVar3];
                    uVar5++;
                }
                bVar2 <<= 1;
            }
        }
    }

`DAT_0001ce18` indexed by `group * 8 + bit` over 12 groups of 8 bits is a table of
**96 uint16 DTC codes**. That is the DTC table. `PTR_DAT_0001cdc4` is a separate
array of 12 pointers to fault-status structures whose byte at `[2]` holds the flags.

### 16c. The encoding: P-numbers in HEX

Codes are stored as the P-number in hexadecimal, not decimal:

    1797 = 0x705  -> P0705      (the one code the factory manual names)
    1824 = 0x720  -> P0720
    1841 = 0x731  -> P0731  ... 1844 = 0x734 -> P0734
    1857 = 0x741  -> P0741
    5894 = 0x1706 -> P1706
    6208 = 0x1840 -> P1840  ... 6212 = 0x1844 -> P1844

53 of the 96 slots hold a code; the other 43 are zero, meaning that fault bit has no
code assigned. Every one of the 53 decodes to a valid powertrain code - none decode
to something impossible, which is the property the validator now checks.

### 16d. Located per firmware, not assumed

The address is NOT constant across images - `0x01CE18` on the reference ROM is
garbage in the others. `tools/extract_dtc_table.py` locates it by signature: a
96-entry window where at least 30 non-empty entries decode to a plausible P-code and
NONE decode to something impossible. Result, consistent everywhere:

    ADE0236000 0x01DC14   91D0207500 0x01D854   91D1206000 0x01CE18
    91F0217100 0x01CEE8   91FE216300 0x01CE44   ABD1A03100 0x01DC34
    ACD1207000 0x01DE60   ACD1A06000 0x01DE70   91D1207900 0x01D4C8
    AAD1A07100 0x01D784   ABD1207000 0x01DCBC

All eleven: 53 codes, same set. The generator re-checks the first entry decodes to a
valid P-code before emitting, and aborts if not.

### 16e. Shipped as an editable 1D list, and why

First attempt was a 12 x 8 3D grid mirroring the firmware's indexing. Wrong shape -
a code list is a list, nobody reads it as a matrix. It also hit a RomRaider bug: a
**locked 3D table renders with null cells and throws** out of
`Table3DView.populateTableVisual`, because that method allocates its view array from
the table dimensions but fills it from the axis sizes while the lock is temporarily
cleared. Worth fixing in the patch set; a 1D table avoids it entirely.

Left EDITABLE rather than locked, because blanking an entry is a real use: set a code
to 0 and the slot becomes identical to the 43 the factory already leaves at zero, so
the fault bit still sets internally but no code is attached to it. That is useful
after a hardware change that leaves a sensor permanently faulted.

Two honest limits recorded in the table's own description:

- It suppresses the CODE, not the fault. Whatever limp-home or pressure behaviour the
  TCU applies when that bit sets still happens; you have only stopped it saying why.
- The zero-to-disable behaviour is INFERRED from the layout, not tested on a car.
  Zero is what the firmware's own unused slots contain, which is the best evidence
  available, but nobody has confirmed how a scan tool reports it.

### 16f. Validation checks content, not structure

The list is a plain contiguous array with no terminator, so there is nothing
structural to verify. The validator checks the CONTENT instead, which is stronger:
every non-empty entry must decode to a real powertrain P-code. Confirmed to bite -
moving the address 24 bytes produces "8 entries do not decode to a P-code, first
0x8000". This is precisely the check the old `0x4090` claim would have failed
instantly, and it is deliberately attached to the category rather than the table type
so changing the table's shape cannot silently drop it.

1439 checks across eleven firmwares, no errors.

---

## 17. THE FORUM THREAD, ARCHIVED AND READ (2026-07-30)

This project had one page of one thread on disk. The shift-table discussion turned
out to be in a different thread entirely, and page 4 of it answers a question §15
left open. `tools/fetch_forum_thread.py` now archives a whole topic to
`docs/forum_thread_<id>.txt`; topic 13725 is all 385 posts.

Two practical notes about the scraper. The board runs phpBB2, not phpBB3 - posts are
table rows anchored by `<a name="p12345">` with the text in `<div class="postbody">`
- and a phpBB3 parser looking for `id="p12345"` silently reports an empty thread.
And it refuses to overwrite an existing archive with a much smaller scrape, because
the copy of topic 20850 here is hand-curated (its CAN tables came from an attachment,
not the post body, which is only 536 characters) and scraping it destroyed that once.

### 17a. The 5 x 10 states - what all those curves ARE

§15 found 82 shift-shaped curves against the 8 in the definition and could only say
they were "per-mode and per-condition". Posts 54, 55 and 57 name them.

rimwall, post 54:

> Here is a teaser - the 5EAT base case shifting curves. There are 50 sets of these
> curves. 5 different unknown states x 10 different other unknown states.

rimwall, post 57, having worked one axis out:

> I've worked out the 5 states relate to fuelling (CL / OL / sensor error states).
> So the other 10 states must be the ones you have listed.

Sasha_A80's list, post 55, of what the other axis is likely to be:

> default / cold engine / warm engine / cold ATF / warm ATF / cold catalyst /
> preheat catalyst / quick shift (or selector RND43L plus winter mode) / hill assist
> ... There are 2-5 driver style adaptation levels for a part or for all variants
> above. And for "road curveness". Kickdown redlines may be defined separately.

That lines up with the decompilation. `FUN_000443d8` computes `iVar2 = iVar3 * 5 +
gear`, where `iVar3` is 0..4 selected by comparing `DAT_00804858` against six
constants - five states, which is rimwall's fuelling axis. The several pointer arrays
at `0x01A308 + n * 0xC8` are then the second axis. So the definition currently ships
one cell of a 5 x 10 grid.

NOT confirmed: which condition is which. Sasha's list is a candidate list, offered as
"there should be", and rimwall never pinned it down either. Naming a table "Cold ATF
Shift Map" on that basis would be a guess wearing a confident label.

### 17b. Pointer array addresses, cross-checked

rimwall posted the shift-pointer-array address for several ROMs. Checked against the
images rather than taken on trust:

    ACD1A06000   0x180E8   CONFIRMED - 12/12 in-ROM pointers, first target 0x1683C,
                           exactly as posted; 5 of the first 6 land on real curves
    91D1206000   0x17714   ours, from the decompilation - same structure, first
                           target 0x15CA8, which is the Shift 1-2 Upshift curve
    91FE216300   0x174B4   matches an address rimwall posted without naming the ROM
    91A0217400   0x170FC   DOES NOT match the image here. Either his dump differs
                           from ours or the address was approximate. Not adopted.

`0x17A94`, the other unattributed address, matched seven different images under the
same test, which means the test is too permissive there rather than that the address
is right. Recorded as unreliable, not as a finding.

The useful generalisation: on every image checked, the array sits between `0x17000`
and `0x18100` and is a run of twelve big-endian in-ROM pointers, most of which land
on a curve. That is a much cheaper way to locate it per firmware than tracing the
decompilation each time.

### 17c. Table structure, from rimwall (post 131)

> ECU - tables have a table header with number of items, data type, pointers to
> table data. This makes the table data 'clean' (not mixed with other data)
>
> TCU - no table header, only a pointer to the start of the data. Some tables have
> the number of elements at the start of the data. Other tables are terminated with
> 0xffff to signify end of data. Arrangement of data varies. 2D table data is
> generally intermixed (ie) x1, y1, x2, y2 and so on. 3D table data is generally
> split into the columns (ie) d11, d12, d13, d21, d22, d23, d31, d32, d33.

Independent agreement with what this project derived: the count-prefixed and
0xFFFF-terminated formats, and the interleaved 2D layout that the `skipCells` work
in §14b exists to read.

### 17d. FP = 0x808000, independently confirmed a second time

Post 22 quotes the instruction pair directly:

> seth fp, #0x81 ; add3 fp, fp, #-0x8000 -> The result is FP = #0x808000

§14a reached the same value by scanning every image for `LD24 R13, #imm24`. Two
independent derivations, and the upstream Ghidra module's `0x80c000` is wrong in
both of them.

### 17e. LOCK-UP: the best lead so far, and it is not a shift table

§16d had lock-up unfound. Post 125 explains why it does not look like the shift
curves, and quotes the factory description:

> the factory lock-up control is exceptionally slippy - seems to extend over a number
> of seconds - which per FSM is 'Smooth control - In lock-up clutch engagement,
> gradually changes pressure to provide smooth engagement.' I would say the gradual
> is about 5 or 10 times slower than it should be. Not sure how hard it is to locate
> those tables.

So lock-up engagement is a PRESSURE RAMP over time, not a speed/pedal threshold
polyline. That is why scanning for shift-curve-shaped arrays never found it, and it
redirects the search: look for a time-indexed pressure or duty ramp feeding the
lock-up solenoid, not a curve in (speed, pedal) space. rimwall had not located these
either as of that post, so there is nothing to copy.

The phrase "Smooth control" is the factory term and is worth searching a full service
manual for; the extract in this project does not contain that section.

### 17f. Other findings worth having

- Line pressure (post 227): rimwall located the Engine Torque to Line Pressure
  conversion, which "uses factors for each brake / clutch which account for the
  number of plates in each brake/clutch". That is a separate mechanism from the kPa
  target curves found in §14c and suggests more pressure tables exist.
- Shift durations (posts 227, 272) are located and adjustable in his work. Not
  mapped here.
- Denso TCUs are a different animal: 12 table headers at `0xe9080`, each 15 x 5, and
  a ROM integrity table at `0xffb80` of [start][end][balance] triples that must sum
  to `0x5aa5a55a`. None of that applies to the Hitachi M32R images here.
- Security access and the on-board kernel (post 61): CAN IDs 0x1f21 / 0x1f29, the
  0x27 seed-key exchange, and the encryption words. Relevant to FastECU, not to this
  definition.

---

## 18. THE LINE PRESSURE CHAIN - TWO MORE CONFIRMED SCALES (2026-07-30)

Post 184 of thread 13725 describes the whole line pressure calculation:

> CET is sent from the ECU via bytes 3 & 4 of CAN ID 0x412. The TCU calculates slip
> via the ratio between Turbine Speed and Engine Speed. A factor is looked up from a
> table based on the slip. For high slip (~0.5) the factor is ~1.4. For low slip, the
> factor is ~1.0. The CET is multiplied by this factor. Factored CET is then smoothed
> and further factored by a lookup based on ATF Temp. The twice factored and smoothed
> CET is then used to lookup a Line Pressure target.

That names two multiplier tables, and a multiplier is a strong fixed-point signature:
its baseline is exactly 1.0, so the raw data contains the divisor. Both were already
in the definition as `raw`.

### 18a. The slip factor - checks against numbers from outside this project

`Signal 82AC Curve 1 of 2`, now `Torque Converter Slip Pressure Factor`.

    breakpoints  0, 512, 614, 717, 819, 922      /1024 -> 0.0, 0.5, 0.6, 0.7, 0.8, 0.9
    values       1988, 1425, 1295, 1169, 1051, 1024, 1024
                                                 /1024 -> 1.941, 1.392, 1.265, 1.142,
                                                          1.026, 1.000, 1.000

Against rimwall's description:

    ratio 0.5 (high slip)  ->  1.392    he said "~1.4"
    ratio 0.9 (low slip)   ->  1.000    he said "~1.0"

Two independent numbers from an outside source landing on the same divisor is not a
coincidence, and the value column bottoming at exactly 1024 is the unity baseline a
multiplier must have. Breakpoint and value are both /1024.

### 18b. The ATF temperature factor - confirmed from the code, not the shape

`ATF Temp Curve (8428)`. `FUN_00045070(&DAT_00008428, 1, DAT_008047fb)` is the
lookup, and the result is used like this:

    iVar2 = (uVar7 & 0xffff) * (uVar4 & 0xffff);
    uVar4 = (uVar5 & 0xffff) * iVar2;
    DAT_008042fa = (undefined2)(uVar4 >> 0x10);

`uVar7` defaults to `0x100`. 256 is unity in /256 fixed point, and multiplying two
/256 values then shifting right 16 is arithmetically exact. So the divisor is /256,
established from the arithmetic rather than guessed from the range.

    breakpoints  0, 15, 25, 35     -40 -> about -40, -25, -15, -5 C
    values       435, 435, 282, 256   /256 -> 1.699, 1.699, 1.102, 1.000

More line pressure while the fluid is cold, unity once warm. Physically right, and
it bottoms at exactly 1.000.

`ATF Temp Curve A (Mode 1)` and `(Mode 2)` are the same fixed point at the hot end -
breakpoints about 95, 115, 135 C with factors 0.637..0.859 and 0.488..0.762, so they
de-rate something as the fluid heats. Same /256 family, but their consumer has NOT
been traced, so they carry the scale without a claim about what they govern.

`DAT_00008076`, the constant `uVar7` picks up when it is not unity, is 5120 = 20.000
in /256. A scalar worth exposing later.

### 18c. What this does and does not settle

It gives three more tables real units and renames one for what it actually does. It
does not mean the line pressure chain is mapped: the CET smoothing, the final
target lookup and the per-clutch plate-count factors rimwall mentions in post 227 are
all still unlocated.

Everything else that scanned as a plausible fixed-point multiplier was left raw. The
scan in `tools/classify_raw_tables.py` proposes candidates and deliberately adopts
nothing - a plausible scale that is wrong reads as confirmed, which is the mistake
this project already made once with pressure units.

### 18d. Pinout - not available here

Asked and answered honestly: there is no TCU harness pinout in what this project has.

- The service manual extract on disk is 147 KB of text from a 1.5 MB PDF and covers
  the 5AT section only. It has removal and installation procedures but no wiring
  diagrams or terminal tables.
- The thread does contain a pinout (post 368) but it is the wrong one twice over:
  it maps MCU pins to PCB programming pads (MD1, FWE, PD8, PB15, TxD1, RxD1) on a
  DENSO SH-based TCU, for boot-mode recovery of a bricked unit. Different controller
  family from the Hitachi M32R images here, and a board-level mapping rather than a
  vehicle harness connector.

A real harness pinout would come from the wiring diagram section of a full FSM, which
is not in the repository and is Subaru's document.

---

## 19. THE LINE PRESSURE TARGET MAPS - TORQUE IN, kPa OUT (2026-07-30)

Section 18 scaled the two multipliers in the line pressure chain. This is the lookup
they feed, which is the part a tuner actually wants.

### 19a. Found by following the value, not by scanning

The twice-factored torque is written to `DAT_008042fa`. It has exactly two consumers:

    DAT_00804a82 = FUN_00045070((&PTR_DAT_00012478)[uVar2 & 0xff], 0, DAT_008042fa);
    DAT_00804a82 = FUN_00045070((&PTR_PTR_00012314)[DAT_0080485f], 0, DAT_008042fa);

So `0x12478` and `0x12314` are arrays of pointers to target maps, chosen by
operating state, and `DAT_00804a82` is the resulting target. Nine distinct maps,
consistently, in all eleven firmwares.

### 19b. Both axes confirmed, from two different outside documents

INPUT, /10 = Nm. The community CAN decoding gives 0x412 bytes 3-4 as Engine Torque
Output. The breakpoints then read 0, 50, 100, 150, 200, 250, 300, 350, 400, 600,
800, 1000 Nm - round numbers over a sensible range.

OUTPUT, /10 = kPa. The factory manual's line pressure test (5AT-35) gives two
figures, and two different maps land on them exactly:

    Target 7   base            490 kPa    manual: 490 nominal, 385-555 band,
                                          D range, throttle full closed
    Target 9   at 400 Nm      1372 kPa    manual: 1370, D range, throttle full open

Not the same map, which is the point - they apply in different operating states, and
each reproduces the figure for the condition the manual measured. A single
coincidence would be unremarkable; two, on separate maps, from a document written
twenty years before this analysis, is not.

The nine maps at a glance (91D1206000):

    Target 1  base  750 kPa   at 400 Nm  1260
    Target 2  base  750           1780
    Target 3  base  860           1880
    Target 4  base  800           1300
    Target 5  base  800           1300
    Target 6  base  850           1300
    Target 7  base  490           1300
    Target 8  base  450           1300
    Target 9  base  524           1372

### 19c. What is still open

Which operating state selects which map is NOT established. The selector reads
`DAT_008047db` and `DAT_0080485a` for one array and `DAT_0080485f` for the other,
and those have not been traced to a named condition. The table descriptions say so
and advise changing the family as a set unless the active map has been logged.

The per-clutch plate-count factors rimwall mentions in post 227 are also still
unlocated. They are a separate mechanism from these targets.

### 19d. Why this one gets real units when most raw tables do not

The standing rule here is that a plausible scale is not adopted without evidence,
because a wrong unit reads as confirmed. This one clears that bar comfortably: the
input scale comes from the community CAN decoding, the output scale from the factory
manual, and the two were established independently of each other and of this project.
Contrast the other candidates thrown up by `tools/classify_raw_tables.py`, which look
like fixed-point multipliers and are still shipped raw because nothing outside the
guess supports them.

---

## 20. DOWNSHIFT PRESSURE AND RAMP TIMING - and why it is NOT lock-up (2026-07-30)

Hunting the lock-up control turned up a different thing, which is worth having on
its own but must not be mislabelled.

### 20a. A second target in the same RAM block

The line pressure target is `DAT_00804a82`. Looking for its neighbours found one
other lookup writing into that block:

    DAT_00804a94 = FUN_00045070((&PTR_PTR_00012034)[DAT_00804a8e], 0, DAT_008047fe);

Vehicle speed in, pressure out, wrapped in a timed ramp:

    if (timer < duration[idx])   out = floor;
    else                         out = min(target, start + step[idx]);

`DAT_00804a8c` is the timer, incremented every cycle and reset when the state is
entered. `step` and `duration` are a 4-byte struct per state at `0x1200C`, and the
target maps hang off a pointer array at `0x12034`.

That is exactly the shape the factory calls "smooth control - gradually changes
pressure to provide smooth engagement", which is why it looked like lock-up.

### 20b. The matrix says downshift, not converter clutch

The state index comes from a 5 x 5 byte matrix at `0x1BB6A`, read as `[a * 5 + b]`:

          b=0    1    2    3    4
    a=0   255  255  255  255  255
    a=1     0  255  255  255  255
    a=2     1    2  255  255  255
    a=3     3    4    5  255  255
    a=4     6    7    8    9  255

Lower triangular. An index exists only where `b < a`, and 255 marks "no entry".
With `a` the current gear and `b` the target gear, `b < a` is a downshift, and there
are exactly ten of them among five gears: 2-1, 3-1, 3-2, 4-1, 4-2, 4-3, 5-1, 5-2,
5-3, 5-4. Ten valid indices, ten target maps, ten ramp structs.

A gear-transition matrix is not a torque converter clutch. **This is downshift
pressure control. Lock-up is still not found.** It would have been easy to ship it
as a "Lock-Up" category on the strength of the ramp shape alone, and it would have
been wrong.

This is very likely the "shift durations" rimwall mentions in post 227 as something
he had located.

### 20c. Units

Pressure is /10 = kPa, the scale confirmed against the factory manual in section 19.
These maps top out at 13720, which is the 1372 kPa that manual gives for full
throttle in D - the same number, reached independently, in a different table family.

Duration is a loop counter. The controller's task period has NOT been established,
so it ships as a raw count. Converting it to milliseconds from a guessed task rate
would produce a number that looks authoritative and is not.

Stock values are interesting: only the 2-1 downshift has a hold period (25 counts)
and a small step (50); most entries have a step of 32767, which is effectively no
limit, so the pressure goes straight to target. So the factory only paces one
downshift and lets the rest apply immediately.

### 20d. Shipped as

`Transmission - Downshift Pressure`, in all eleven firmwares:

- ten `Downshift <n-m> Pressure` maps, vehicle speed against kPa
- `Downshift Ramp Step`, ten entries, kPa
- `Downshift Ramp Hold`, ten entries, raw loop counts

The ramp tables are a fixed array rather than a terminated record array, so the
validator got its own check for them: every entry readable, not all zero, and no
0xFFFF sentinel - any of which would mean the address is wrong. 3045 checks across
eleven firmwares, no errors.

---

## 21. ALL FIFTY SHIFT MODES DECODED - the 5 axis is GEAR LIMIT (2026-07-30)

Section 15 found 82 shift-shaped curves against the 8 in the definition. Section 17
learned from the thread that they are "50 sets, 5 states x 10 states". This resolves
the structure and ships the result.

### 21a. Fifty modes, ten groups of five

The curves hang off a pointer array indexed `gear * 2 + direction`, ten entries per
mode. Slots 1 and 8 are always placeholders - first gear has no downshift, fifth has
no upshift - which is what confirms the indexing rather than assuming it.

Walking past the first ten entries gives FIFTY modes, matching rimwall's "50 sets"
exactly. They are ten groups of five, and within every group the number of live
upshifts steps down as the mode rises, the highest one replaced by the placeholder
each time:

    limit 0   1-2, 2-3, 3-4, 4-5 live     D, all gears
    limit 1   4-5 disabled                hold 4th
    limit 2   3-4, 4-5 disabled           hold 3rd
    limit 3   only 1-2 live               hold 2nd
    limit 4   no upshifts at all          hold 1st

**The five axis is manual gear limiting.** That is read off the data, not assumed:
nothing else progressively disables upshifts from the top down, one per step, five
times over, in every one of the ten groups.

This DIFFERS from rimwall's reading, where the five were fuelling states (closed
loop, open loop, sensor error). No contradiction is implied - his index came from a
different array, the one at `0x01A308` computed as `iVar3 * 5 + gear` in
`FUN_000443d8`. Two different five-way selectors exist. The one that reaches these
curves is the gear limit.

### 21b. The ten groups are the conditions, and stay unnamed

Ten groups, each a complete eight-curve schedule. These are the operating
conditions. Sasha_A80's candidate list from the thread - cold and warm engine, cold
and warm ATF, catalyst preheat, quick shift, hill assist, driver style adaptation -
was offered as "there should be", and neither he nor rimwall pinned any of them to a
specific slot. They ship numbered.

Naming "Shift Map 6" as "Cold ATF" on the strength of a candidate list would be a
guess wearing a confident label, and would be the same error as the DTC table at
0x4090.

### 21c. Shipped

`tools/extract_shift_modes.py` locates the pointer array by shape - ten in-ROM
pointers where slots 1 and 8 are placeholders and the other eight are curves - which
is specific enough to find it without tracing the decompilation per firmware. It
independently landed on `0x180E8` for ACD1A06000, the address rimwall posted for that
exact ROM, and on `0x174B4` for 91FE216300, another address he posted without naming
the image.

Ten complete schedules per firmware (eight on the three 512 KB calibrations), each a
single sparse Shift Map with pedal across, shift event down, km/h in the cells - the
same form as before, ten times over. The gear-limited variants are not listed
separately because they reuse these curves with the upper upshifts disabled.

    91D1206000  10 maps      ACD1207000   8 maps
    91FE216300  10           ADE0236000   8
    91D0207500  10           ACD1A06000   8
    91F0217100  10
    ABD1A03100  10
    91D1207900  10
    AAD1A07100  10
    ABD1207000  10

Verified through RomRaider's own parser: 124 3D tables on the base ROM, 2994 cells,
zero mismatches. Validator at 3324 checks across eleven firmwares, no errors.

### 21d. Lock-up: a third lead eliminated

The output-first approach did not work either. The only hardware registers the
decompilation names in the SFR range are `0x8007EA` through `0x8007F2`, which is the
Interrupt Controller - the same block this project once misidentified as a solenoid
PWM bank. The M32R processor module does not name the timer registers that would
actually drive a solenoid, so there is nothing to search for by name.

Three leads eliminated so far: the paired curve block at `0x018060` (shift decision),
the timed pressure ramp at `0x12034` (downshift control), and the SFR search. What
remains is to name the MJT timer registers in the processor module and work forward
from the output, which is a bigger piece of work than any of the above.

---

## 22. THE SOLENOID OUTPUT PATH, END TO END (2026-07-30)

### 22a. Correcting section 21d - the output route was never blocked

Section 21d said the output-first approach was blocked because the only hardware
registers in the decompilation were `0x8007EA` to `0x8007F2`, the Interrupt
Controller. **That was wrong, and it was my own error, not a property of the ROM.**

The search used `DAT_008[0-3][0-9a-f]{3}` with no end anchor, which matched
truncated prefixes of ordinary RAM symbols like `DAT_00804855` and found nothing
useful. More importantly it was looking for the wrong thing entirely: the M32R
processor module defines 1749 named memory-mapped registers, so anything the
firmware touches appears by NAME, not as a `DAT_` symbol.

Searching for the register names instead shows the firmware drives **167 of them**.

### 22b. Seven PWM solenoid channels

The output stage is one function driving seven timer channels, each a
period/duty pair:

    TIO2CT  = duty - 1;
    TIO2RL1 = period - duty - 1;
    TIO2RL0 = duty - 1;

with two special cases per channel: duty 0 drives the port pin low and disables the
timer, and a specific full-scale value drives it high, so the solenoid can be held
fully off or fully on without PWM.

    channel   duty var     command var   driver
    TIO2      0x804EBE     0x805026      FUN_0002E4BC
    TIO4      0x804EBC     0x805024      FUN_0002DFAC
    TIO5      0x804EB2     0x80501C      FUN_0002CB70
    TIO6      0x804EB4     0x80501A      FUN_0002C3F8
    TIO7      0x804EB6     0x80501E      FUN_0002D07C
    TIO8      0x804EB8     0x805020      FUN_0002D58C
    TIO9      0x804EBA     0x805022      FUN_0002DA9C

Seven channels matches the 5EAT's solenoid count - line pressure, lock-up, transfer,
and the shift and timing solenoids.

### 22c. The full chain

    pressure command   0x804A62 .. 0x804A6E   seven uint16, one per solenoid
        |              computed per solenoid by seven parallel functions
        v
    duty command       0x80501A .. 0x805026
        |              clamped between 0x804EC2 and 0x804EC4
        v
    duty              0x804EB2 .. 0x804EBE
        |
        v
    TIOnRL0 / TIOnRL1  hardware PWM

Each pressure command is interpolated on ATF TEMPERATURE between two computed
pressures:

    if (temp between DAT_0001c3bd and DAT_0001c3be)
        cmd = (lo * (hi_bp - temp) + hi * (temp - lo_bp)) / (hi_bp - lo_bp) * 0x20

so `0x1C3BD` and `0x1C3BE` are the temperature breakpoints for that blend - a pair of
calibration constants worth exposing later, and a third place ATF temperature
influences pressure alongside the factor curve in section 18b.

### 22d. Lock-up: still not identified, and why

All seven driver functions are structurally identical, so nothing about the output
stage distinguishes lock-up from a clutch or brake solenoid. The obvious
discriminator - that lock-up only operates in fifth - does not appear either: none of
the seven functions references the gear variable `DAT_0080486e`. Whatever gates
lock-up by gear happens further upstream, in whatever computes the pressures at
`0x804298`, `0x80427C`, `0x80428A` and `0x80426E`.

So the honest position after four attempts is: the whole output path is now mapped
and any one of seven solenoids could be the converter clutch. Identifying which needs
either the upstream pressure computation traced, or a log from a car showing which
duty changes when lock-up engages. The second would settle it in minutes and needs no
further disassembly.

Leads eliminated so far: the paired curve block at `0x018060` (shift decision), the
timed pressure ramp at `0x12034` (downshift control), and the claim that the SFR
route was unavailable (my error).

---

## 23. LOCK-UP: NAMED, LOCATED IN THE DTC TABLE, NOT YET PINNED TO A SOLENOID SLOT

The 2006 Tribeca USDM service manual (jdmfsm.info) turned out to contain the
transmission diagnostics section this project never had. It answers most of what was
open about lock-up.

### 23a. The seven solenoids, named

The Select Monitor data list (5AT(diag)-15) enumerates every solenoid, and each has a
target pressure reported in kPa:

    H&LR/C   High & low reverse clutch
    D/C      Direct clutch
    F/B      Front brake
    I/C      Input clutch
    P/L      Line pressure
    L/U      LOCK-UP
    AWD      Transfer

Seven. The firmware drives exactly seven PWM channels (section 22), so the sets
correspond. The manual also confirms each is reported as a TARGET PRESSURE in kPa,
which is the same quantity the line-pressure work in section 19 established.

### 23b. Lock-up's DTC, and where it sits in our table

    P0743  TORQUE CONVERTER CLUTCH CIRCUIT ELECTRICAL
           "The output signal circuit of lock up solenoid is open or shorted."
           "No lock-up occurs. (After engine is warmed-up)"

P0743 is in the DTC table this project mapped in section 16, at index 12 - status
byte 1, bit 4. The other solenoid codes place similarly:

    1.0  P0753  shift A, front brake
    1.1  P0758  shift B, input clutch
    1.3  P0748  line pressure
    1.4  P0743  LOCK-UP
    5.1  P0768  solenoid D
    5.2  P0763  shift C, H&LR clutch
    7.2  P0773  shift E

### 23c. Useful specifics from the manual

- The lock-up circuit is on TCM connector B54, pin 23.
- The functional test reads "L/U Solenoid Target Pressure" and expects 500 kPa or
  more at 60 km/h with 10% or less throttle. That is a real reference value to
  compare a log against.
- Lock-up engagement is the "smooth control" pressure ramp quoted in section 17e.

### 23d. What is still NOT established, and a correction to an earlier assumption

Which of the seven command slots at `0x804A62`..`0x804A6E` is L/U.

Two attempts failed and both are worth recording. Assuming the SSM list order maps
onto the RAM order would put L/U at `0x804A6C`, but that is a guess: the line
pressure target at `0x804A82` flows to `0x804A84` and `0x804A92`, not into the
`0x804A6x` block, so there is no anchor confirming the ordering.

And the command variables are NOT in kPa. The per-driver constant `0x1C2B0` is 1258,
which is the same `0x4EA` full-scale value the TIO2 driver uses to switch the port to
a static high - so `0x804A62`..`0x804A6E` are DUTY, full scale 1258. The kPa figure
the Select Monitor reports is computed somewhere else. Any attempt to match those
slots against the manual's kPa figures directly would have produced a confident wrong
answer.

The remaining routes are unchanged in kind but much better targeted now: log the seven
duty addresses while lock-up engages and watch which moves, or trace the fault-latch
bit for group 1 bit 4 back to the driver that raises it.

### 23e. rimwall's FastECU fork - what is and is not in it

Cloned `github.com/rimwall/fastecu-oem` (113 MB) and searched it.

The patched Tribeca ROM is NOT in the repo. It was a forum attachment on post 266 of
thread 13725, which needs a board login. What the repo does have:

- `sub_tcu_hitachi_can` as a protocol family in `config/protocols.cfg`, so the tooling
  for our TCU is there
- flashing modules including `flash_ecu_subaru_hitachi_m32r_can` and
  `flash_ecu_subaru_uinisia_jecs_m32r`
- kernels for SH7055 and SH7058, CAN and serial
- `file_defs_romraider.cpp` - it reads RomRaider definition XML, so the definition
  this project produces should load in FastECU as well

`config/logger.cfg` is only a saved gauge selection, not parameter definitions, so it
does not provide RAM addresses.

FastECU and this project are complementary rather than competing. FastECU reads and
writes the TCU and logs it, which RomRaider cannot do for this ECU family at all.
This project produces the table definition and the editor. The definition is the part
that would be lost by switching tools, and it appears FastECU can consume it.

---

## 24. THE FASTECU DEVELOPMENT BRANCH, A SECOND CHECKSUM, AND rimwall's 123 POSTS

Three sources opened up at once: the development branch of rimwall's FastECU fork,
a corrected archive of forum thread 13725, and a set of stock Denso TCU images.

### 24a. The development branch is where the TCU work lives

An earlier pass cloned `github.com/rimwall/fastecu-oem` shallow, on the default
branch, and concluded the repository held no TCU parameter material. That was
wrong in an avoidable way: `master` has no TCU files at all. The repository has
five further branches, and `development` carries the entire TCU stack:

    modules/checksum_tcu_subaru_hitachi_m32r_can.cpp   <- our processor family
    modules/checksum_tcu_subaru_denso_sh7055.cpp
    modules/checksum_tcu_mitsu_mh8104_can.cpp
    modules/flash_tcu_subaru_hitachi_m32r_can.cpp
    modules/flash_tcu_subaru_hitachi_m32r_kline.cpp
    modules/flash_tcu_subaru_denso_sh705x_can.cpp
    modules/flash_tcu_cvt_subaru_hitachi_m32r_can.cpp
    kernels/ssmk_tcu_can_sh7055_35.bin, ssmk_tcu_can_sh7058.bin

rimwall says as much in post 72 - "First pass of the code is done on the repo
(development branch)" - and again in post 269, "Item 4 (protocols.cfg) should come
from the development branch (not master)". Clone with all branches, not `--depth 1`.

### 24b. A SECOND CHECKSUM, WHICH THIS PROJECT WAS NOT MAINTAINING

`checksum_tcu_subaru_hitachi_m32r_can.cpp` implements TWO checksums, not one:

  checksum 2  the additive one this project already had: every 32-bit big-endian
              word except 0x008000..0x008007, two's-complemented, stored in both
              0x008000 and 0x008004
  checksum 1  a BALANCE word at 0x008020, chosen so that every 32-bit big-endian
              word from 0x008020 to the end of the image sums to 0x5AA5A55A

The second was missing here entirely. That matters: an image that uses it and is
saved without it is an image the TCU's start-up integrity check should reject -
rimwall notes in post 61 that "there are various ROM integrity checks on start-up
so that will need to be satisfied by any modified ROM".

IT IS UNIVERSAL, AND THE FIRST ANSWER HERE WAS WRONG. The initial pass tested only
rimwall's exact form - does some region sum to 0x5AA5A55A - found it true on three
images, found no region reaching that constant on the other eight, and concluded the
other eight had no second checksum. That conclusion was reached from a statistical
scan while sixteen decompiled firmwares sat in `decompiled/` unread.

Reading them settles it. Every image contains the same loop:

    for (p = 0x8000; p < end; p++)
        if (p < 0x8000 || p > 0x801f)      // skip 0x8000..0x801F
            sum += *p;

The region is therefore 0x008020 to the end of the same extent the additive checksum
covers. What differs is the test applied to the result:

    32-bit variant   if (sum == 0x5aa5a55a)          ADE0236000, ACD1207000, ACD1A06000
    16-bit variant   if ((sum & 0xffff) == 0x5aa5)   the other eight

In the 16-bit variant the balance is the HALFWORD at 0x008022 and 0x008020 stays
zero, which is why those images look like they hold a small unrelated value there.
The evidence was already visible and was misread: the earlier scan printed sums of
0x0E535AA5, 0x6A7B5AA5, 0xDC2D5AA5 and so on for exactly those images - every one
ending in 5AA5 - and that was recorded as a boundary offset rather than as a 16-bit
checksum meeting its target.

The cost of the wrong answer would have been high. Leaving 0x008020 alone on the
16-bit images, which is what "no balance here" implies, means eight of the eleven
ROMs fail their own integrity check after any edit. The variant is decided
structurally, from the halfword at 0x008020 being zero or not, which stays true
after the ROM has been edited.

One more image-specific detail falls out of it: 91FE216300 is a 512 KB image with a
384 KB payload, and its balance region ends at 0x60000 like its additive checksum,
not at the end of the file. Summing to EOF gives 0x90C1DAA5 and looks like a
failure; summing to 0x60000 gives 0x90C25AA5 and passes.

Implemented in `tools/checksum.py` and in `ChecksumSUBARUTCU.java`. Verified two
ways. First, statically: every image reports both checksums valid as loaded, a byte
flip breaks one, and repair restores both. Second, and this is the test that
matters for flashing, end to end through the packaged application - each ROM loaded,
a table cell edited through the real editor write path, saved through
`Rom.saveFile()`, and the resulting file handed to an independent checker that
recomputes both checksums from the firmware's own rule. All eleven pass, reporting
2 of 2 valid both as loaded and after saving.

Two places FastECU's module would misfire on images in this repository, worth
recording because the code was otherwise a straight confirmation:

  - it implements only the 32-bit variant, and applies it unconditionally, so on
    the eight 16-bit images it writes a 32-bit balance over a field that is not one
  - it hard-codes the whole file as the region. 91FE216300 needs 0x60000.

### 24c. rimwall's posts - the archive was attributing them to nobody

The archive of thread 13725 recorded almost every author as `&nbsp;`. The parser was
matching the first `memberlist.php?mode=viewprofile` link in each post segment, which
on this phpBB2 board is the profile BUTTON in the previous post's footer, whose
visible text is a non-breaking space. The author is in `<b class="postauthor">`
directly after the post anchor. Fixed and re-archived: rimwall wrote 123 of the 385
posts, a third of the thread, and until now essentially none of them were searchable
by author.

### 24d. What his posts add

CONFIRMS what this project derived independently:

  - post 134: shift table pointers for ACD1A06000 at 0x180E8, first data at 0x1683C.
    Section 12 reached both from the ROM without reference to the post.
  - post 131: the Hitachi table format - no table header, only a pointer to the data;
    some tables count-prefixed and others 0xFFFF-terminated; 2D data interleaved as
    x1,y1,x2,y2; 3D data split into columns. This is exactly the geometry set the
    definition generator and validator were built around.
  - post 170: the Denso block integrity table at 0xFFB80 as [start][end][balance]
    summing to 0x5AA5A55A. Verified here against eight Denso images.
  - post 184: the line pressure chain - CET from CAN 0x412 bytes 3-4, factored by a
    slip lookup, smoothed, factored again by ATF temperature, then used to look up a
    line pressure target. This is the chain section 19 documents.

EXTENDS or corrects what was recorded here:

  - post 262 gives the slip factor range as 1.8 at maximum slip down to 1.0 at no
    slip. The table in this repository runs 2.000 down to 1.000, with 1.390 at a
    ratio of 0.5 - consistent with his "~1.4 at 0.5 slip" from post 184, and close
    to but not identical with the 1.8 figure, which he was quoting from a Denso
    Outback ROM rather than a Hitachi one.
  - post 57 reads the 5-way axis of the 50 shift schedules as fuelling state
    (CL/OL/sensor error). Section 14 here reads it as a gear limit, from the data.
    Note that post 57 is dated four days after he first found the curves and is
    phrased as a deduction; nothing later in the thread returns to it.
  - post 262 describes the upshift pressure model in full: the TCU maintains a
    linear relationship TCP = M x FET + O between target clutch pressure and
    factored engine torque, trials slightly larger and smaller M and O each cycle,
    keeps the best match, and stores the last eight pairs in RAM and EEPROM. The ROM
    holds DEFAULT M and O values used when new or after Clear Memory 2. Those
    defaults are ROM constants and are not yet exposed as tables here.
  - posts 241 and 345 describe shift duration as a step count: each brake and clutch
    moves through one of ~34 states, and each state has a target pressure and a
    NUMBER OF STEPS to reach it. Fewer steps means a faster change. These step tables
    are not yet located in the Hitachi images.
  - post 343: the SSM pressure adjustments live at different SSM offsets on Hitachi
    ROMs than on Denso ones, and he had not tracked the Hitachi ones down.

### 24e. Denso stock images

Seven stock Denso SH7058S TCU images were added to the working set - Legacy 3.272
and 3.583, a Legacy STI, an Exiga, an Impreza STI, a Forester STI and a Tribeca.
All seven verify against the Denso convention above: one block, 0x002000-0x0FFAF7,
sum plus balance equal to 0x5AA5A55A exactly.

They are a different family from the M32R images this project targets, so they do
not extend the definition. They do matter for two reasons: they confirm the Denso
checksum on seven more images, and they include STI and non-STI calibrations of the
same platform, which is the natural way to isolate the calibration region if the
Denso family is ever taken on.

The patched Tribeca ROM from post 266 is NOT a patch of any of them. It is a later
Denso build - its header block reads `Corp.DENSO2013` where all seven stock images
read `Corp.DENSO2000` - so diffing it against them does not isolate rimwall's 0xA8
command-handler patch.

### 24f. FreeSSM's 5EAT branch

The `e5at-permanent-adjustments` branch of the FreeSSM repository, which post 277
credits to Comer352L, adds the 5EAT adjustment definitions. For SysID A21022:

    0x1BE  Line Pressure Correction                169..211, default 189
    0x16E  1st to 2nd (Direct Clutch)               52..100, default 75
    0x1BC  2nd to 3rd (Forward Brake)              165..205, default 184
    0x16D  2nd to 3rd (High Low Reverse Clutch)     56..97,  default 75
    0x16C  3rd to 4th (Input Clutch)                56..109, default 81
    0x16F  4th to 5th (Front Brake)                168..221, default 195
    0x1BD  4WD Pressure Correction                 138..188, default 170
    0x1BF  Temperature Basis for Pressure Corrections, 20..90 degrees C

These are expressed in 'steps'; post 349 explains that a step is the logged byte in
the kPa tables, cross-referenced against temperature. They apply to Denso TCUs with
SysID A21022. Per post 343 the Hitachi images this project targets do not expose the
same adjustments at the same offsets, so these are not directly transferable - but
they name the eight corrections and give their bounds and defaults, which is the
clearest statement anywhere of what the TCU considers adjustable.

---

## 25. THE DENSO FAMILY, AND PROGRESS ON THE SOLENOID QUESTION

### 25a. B1D3F08000 / Z5D3F080 is not this family

Both filenames in jimihimi's collection are the same image. It opens `ff 00 03 00`,
which is close enough to the M32R branch pattern to look promising, and both
checksums fail.

It is not a 5EAT TCU. Every image in this family carries ASCII identification at
0x8008 - part number, version, case id, as in `MB558D20 / VF34B / Q6E`. This one has
a table of in-ROM pointers there instead, and no identifying strings anywhere in the
header region. Whatever it is, nothing here applies to it, and the failing checksums
are a symptom of that rather than of a bad dump. Excluded.

### 25b. Denso SH705x supported

Nine Denso images now have their own definition, generator and checksum plugin. The
detail that made it quick is that Denso reuse their engine ECU table format, which
RomRaider already parses - the M32R side needed patches for sparse tables and
striding axes before it could show anything at all.

Header, established from the shift tables and confirmed against every image:

    +0x00 uint16 rows         +0x0C uint32 -> data, uint16
    +0x02 uint16 cols         +0x10 uint32 flags
    +0x04 uint32 -> X axis    +0x14 float  scale
    +0x08 uint32 -> Y axis    +0x18 float  offset      (28-byte stride)

Axes are IEEE-754 floats lying immediately before the data, X then Y. Requiring
exactly that spacing is what makes the scan usable: without it a 1 MB image yields
thousands of candidates, and with it, a few hundred real ones.

Twelve consecutive 15x5 tables are the shift schedules, at 0xE9080 in most images
and 0xE90F8 in the 2013-build Tribecas. Both the address and the data agree with
what rimwall reported: an accelerator pedal axis of 0,5,10..100 percent, and values
rising to a little over 200 km/h. Rows reading 255 throughout are unused.

The remaining tables are shipped as unidentified at userlevel 4. Their structure is
certain and their meaning is not, and there are enough of them that guessing would
do real damage to how much of this definition can be trusted.

### 25c. Which solenoid is lock-up - narrowed, not yet answered

Section 22 established seven PWM channels and their duty slots. Reading how each is
written narrows the question considerably.

The seven duty slots are loaded from a contiguous array, which is the command block:

    0x80501A -> 0x804EB4        0x805020 -> 0x804EB8
    0x80501C -> 0x804EB2        0x805022 -> 0x804EBA
    0x80501E -> 0x804EB6        0x805024 -> 0x804EBC
                                0x805026 -> 0x804EBE

Four of them - 0x804EB8, EBA, EBC and EBE - are written by four blocks of code that
are IDENTICAL bar their operands:

    DAT_00804ebX = (short)(((int)DAT_00804eYY * (short)DAT_00804fZZ) / 0x100)
    ...
    uVar3 = DAT_008046fW + DAT_00804ecV + (int)DAT_00804ebX

Four channels driven the same way, each scaled by its own factor, are the four
clutch and brake pressure solenoids that move during a gear change.

0x804EB4 is not like them. It accumulates, saturates at 0x7FFFFFFF and -0x80000000,
and repeatedly calls the same helper on its own current value - a closed-loop
integrator, which is what a regulator looks like rather than a commanded pressure.
Line pressure is the obvious candidate for that, though it is not proven here.

That leaves 0x804EB2 and 0x804EB6 as the two remaining channels, and one of them is
lock-up while the other is the AWD transfer clutch. Both are handled by the same
simple code - clamp between 0x804EC2 and 0x804EC4, then program a timer:

    0x804EB2 -> TIO5CT / TIO5RL0 / TIO5RL1
    0x804EB6 -> TIO7CT / TIO7RL0 / TIO7RL1

Both also test against 0x4EA, which section 22 identified as full scale, and drive
the port to a static level at either end rather than continuing to modulate.

So the answer is now one of two channels rather than one of seven, and the remaining
step is to tell TIO5 from TIO7. Two routes: the fault path for the lock-up DTC
(P0743, group 1 bit 4) should reach exactly one of them, or a log of both duty
addresses while lock-up engages will show which moves. The service manual's
reference figure - L/U target pressure at or above 500 kPa at 60 km/h with 10
percent throttle or less - is what a log would be checked against.

Recording the negative too: reference counts alone say nothing useful here. 0x804EB4
has fourteen references and 0x804EB2 has none in the ACD1A06000 decompile, which
initially looked meaningful and is not - EB2 and EB6 are written through a different
routine that only appears in the base ROM's decompile.

---

## 26. THE FACTORY SHIFT DIAGRAM, AND WHERE THE "NUMBER OF STEPS" LEVER ALREADY IS

The service manual's "Shift change system diagram" (figure PCIA0013E) draws a gear
change as four traces: output shaft torque, gear ratio, and line pressure for the
ENGAGING clutch and the RELEASING clutch separately. It is not redistributed here;
what follows is what it establishes.

Three things in it are load-bearing.

**A shift moves two elements, not one.** There is a pressure trace for the clutch
coming in and another for the clutch going out, crossing over mid-shift. That is
what the four identical driver blocks in section 25c are for - during any one shift
some elements are filling while others are emptying, which is why four channels are
written by the same code with different operands rather than by four different
routines.

**Upshift and downshift are controlled on different inputs.** The manual is explicit:
on a shift-up, "change of line pressure is controlled depending on input torque"; on
a shift-down, "depending on input torque AND VEHICLE SPEED". The downshift path
having an extra input is a structural asymmetry, and matches this project finding
separate downshift pressure maps and ramp structures rather than a single shared set.

**There is closed-loop control during the change.** Annotated on the engaging
clutch's pressure trace: "Full phase real-time feedback control monitors movement of
gear ratio at gear change, and controls oil pressure at real-time to achieve the best
gear ratio." The controlled variable is GEAR RATIO, which is the quantity section 4
confirmed at raw/1024, and it explains rimwall's account (post 262) of the TCU
trialling values either side of its current ones and keeping whichever tracked the
clutch better. It is also consistent with 0x804EB4 being an accumulator that
saturates and feeds back on itself rather than a commanded value.

### 26a. The step count is already exposed, for downshifts

rimwall's description of the state machine (posts 241 and 345) is that each brake and
clutch moves through one of ~34 states; each state computes a target pressure and a
NUMBER OF STEPS to reach it, and "the simplest approach to getting faster changes
would be to reduce the number of steps".

That lever is already in the definition, under a name that does not announce itself.
`extract_downshift_pressure.py` locates a ten-entry structure - one per downshift
combination, four bytes each - immediately before the map pointer array, and ships it
as `Downshift Ramp Step` and `Downshift Ramp Hold`. In the base ROM it reads:

    (50, 25)  (32767, 0)  (35, 0)  (32767, 0)  (35, 0)
    (32767, 0)  (32767, 0)  (35, 0)  (32767, 0)  (32767, 0)

0x7FFF is the not-time-limited sentinel; the real values are small counts of 25, 35
and 50. Those are the step counts rimwall is describing, for the ten downshifts.

So the tuning lever exists and is shipped. What is NOT covered:

  - the same structure for UPSHIFTS, which has not been located
  - the wider state machine - ten downshift combinations is not ~34 states, so this
    is one slice of the mechanism rather than all of it
  - ~~which of the pair is the step count and which the hold~~ - RESOLVED in
    section 32; the shipped labels are correct.

---

## 27. VERIFYING THE DISASSEMBLER AGAINST THE MANUFACTURER'S MANUAL

Everything in this project is downstream of the disassembly, and the disassembler is
a third-party Ghidra processor module with local corrections. It had never been
checked against the instruction set it claims to implement.

Sources, neither redistributed here:

  - **M32R Family Software Manual** (Renesas MEJ19B0001, Rev 1.2) - the instruction
    set, with an [Encoding] bit diagram per instruction.
  - **32176 Group User's Manual** (Renesas REJ09B0067, Rev 1.01) - the hardware
    manual for the exact part in these TCUs, `M32176F4V`. Peripherals and registers,
    not the ISA.

`tools/verify_m32r_sleigh.py` compares the two mechanically. Both describe an
instruction as a sequence of 4-bit fields, so the literal nibbles must agree and
neither side may fix a nibble the other leaves as a field.

### 27a. Result: the module is correct, after two fixes

**54 instructions agree.** Four more are flagged by the checker and were confirmed
correct by hand - they use token forms the checker does not model (`op1_B`/`op3_B`
for ADDX, a whole-word `imm16=0x10D6` for RTE), or the manual row was mis-parsed
(UNLOCK is `0010 src1 0101 src2`, exactly what sleigh has).

Two real defects were found and fixed.

**MVTC was under-constrained.** The manual gives `0001 dest 1010 src`; the module had
`op1=1 & CRdest; Rsrc` with no `op3` constraint. Every sibling in that family pins it
- SRL 0, SRA 2, SLL 4, MUL 6, MV 8, MVFC 9 - so the omission was clearly an
oversight. The effect is that any halfword with `op1=1` and an `op3` belonging to no
documented instruction decodes as MVTC instead of failing. Across the sixteen images
that is 5,377 byte patterns against 773 legitimate MVTC halfwords.

**The accumulator moves were unimplemented**, left as bare stubs `#:MVFACHI` and so
on, although the `ACC` register was already declared. MVFACHI, MVFACLO, MVFACMI,
MVTACHI and MVTACLO are now implemented from the manual's semantics. The bit
numbering is a trap: M32R numbers bits MSB-first, so MVTACHI's documented
`accumulator[0:31] = Rsrc` writes the HIGH 32 bits, and MVFACMI's "bits 16 to 47" is
the middle word - which lands byte-aligned, so `ACC(4)`, `ACC(2)` and `ACC(0)` give
the high, middle and low words respectively.

RAC and RACH are still unimplemented. They need saturation semantics stated
carefully, and between them they account for two halfword matches in sixteen images
against roughly two hundred for the moves.

### 27b. The fixes changed nothing in our output, and that is the useful part

ACD1A06000 was re-decompiled with the corrected module. The result is **byte
identical** to what is already in `decompiled/` - same 1217 functions, same MD5.

That is the answer worth recording. The decompile is seeded at real entry points and
follows real control flow, so the regions where a loose MVTC could bite are data that
Ghidra never walks, and the accumulator encodings that appear in the images are byte
coincidences in data rather than instructions in reachable code.

So the disassembly this project's conclusions rest on is confirmed correct, by
comparison against Renesas' own encoding tables rather than by assumption. The module
is now also correct in two places where it was not, which matters for anyone
disassembling a different M32R image even though it did not matter here.

### 27c. The Denso side

The SH7058S core is **SH-2E**, not SH-2A - SH-2 plus a single-precision FPU, a
different lineage from the later SH-2A. Ghidra ships `SuperH:BE:32:SH-2` which is the
right base; SH-2A would be wrong.

No Denso image has been disassembled yet. The definition in
`5eat_tcu_denso_romraider_defs.xml` was built by reading the table headers directly,
which needs no disassembly - but naming the several hundred unidentified tables will.

---

## 28. FIXED-POINT STORAGE, PROVEN FROM THE BITS

Half the definition still shipped as `raw` - 85 tables against 80 with real units.
The usual route to a unit is the arithmetic in the decompiled code, but the
calibration tables are reached through computed pointers, so their addresses never
appear as symbols and there is no call site to read. That is why these were left.

A different question turns out to be answerable without the code at all: not what
the quantity IS, but how it is STORED.

### 28a. The test

If every stored value of a table, in every firmware, is an exact multiple of 2^k,
then k low bits are never used. That does not happen by accident in a hand-entered
calibration - it means the value was entered in whole units and stored with k
fractional bits.

`tools/detect_fixed_point.py` applies that, strictly: the table must vary (a constant
table proves nothing), and at least one value must have bit k set, or a larger k
would fit and the divisor reported is not the real one. Trouble-code switches are
excluded - they store a P-number, pass the test by accident, and mean nothing scaled.

### 28b. Result

Fourteen tables are provably fixed point:

    Gear 1..5 Reference Speed Baseline      /256      880 of 880 values, 16 firmwares
    Gear 1..5 Slip Detection Threshold      /256
    Reference Speed Curve 1 of 3            /256
    Signal 82CC Curve 1 of 2                /256
    Signal FE Response Curve                /8
    Engine Speed Curve 6 of 6               /8

All now ship scaled. `Gear 5 Reference Speed Baseline` reads
1, 11, 25, 39, 53, 66, 80, 93, 120, 156 where it previously read
256, 2816, 6400, 9984 and so on - the numbers the calibrator actually typed.

Thirteen are labelled "units of 1/256 (quantity not established)" or the /8
equivalent. That is deliberate and is the whole point: the storage format is proven
from the ROM, the physical quantity is not, and a table that shows the right number
with an honest label is useful where one showing 19456 is not.

`Engine Speed Curve 6 of 6` is the exception and does get a real unit. Its divisor is
8 and its range is 517..4096 over an engine-speed axis, which is exactly the RPM
encoding confirmed in section 4, so it is labelled RPM.

### 28c. A hypothesis that failed, recorded because it looked right

The Reference Speed Baseline family is per-gear, indexed by engine RPM, and once
scaled gives a plausible speed ladder - gear 1 reaching 79, gear 5 reaching 206. Road
speed in km/h was the obvious reading.

It is wrong. If the value were road speed then value/RPM would be fixed by the gear
ratio, and the five slopes would sit in the same proportion as 1/ratio: 1.00, 1.56,
2.41, 3.54, 4.25. Measured, they go the other way - 1.00, 0.84, 0.81, 0.57, 0.26.
The quantity falls as the gear rises, so it is not a road speed against engine speed.

The check took a few minutes and the answer would have looked entirely convincing
without it. Every value in the family is a whole number after scaling, the ladder is
monotonic, and the magnitudes are right for km/h. None of that is evidence.

So: format established, quantity still open. The name "Reference Speed Baseline" is
inherited from earlier work and should not be read as confirmed either.

---

## 29. THE SOLENOID DRIVE CHAIN, END TO END

Section 25c narrowed lock-up to two channels. Following both all the way up maps the
chain completely, and explains why the two cannot be told apart from the driver code.

### 29a. The chain

For the two candidates, with the TIO7 twin in brackets:

    command      0x804A64  [0x804A66]   blended target, ATF temperature dependent
      |
    demand       0x804F74  [0x804F78]   = feedback - command
      |
    pre-scale    0x80500E  [0x805010]
      |          scaled twice by 0x805038 and 0x805037, /0x80 each
    output       0x80501C  [0x80501E]
      |
    duty         0x804EB2  [0x804EB6]   clamped between 0x804EC2 and 0x804EC4
      |
    timer        TIO5CT/RL0/RL1  [TIO7CT/RL0/RL1]
      |
    pin          TO5 = port P115 = package pin 102  [TO7 = P117 = pin 104]

The pin mapping comes from the 32176 Group User's Manual, which is the hardware
manual for the exact part in these TCUs.

### 29b. Why the code cannot settle it

The two functions - `FUN_0002cb70` for TIO5 and `FUN_0002d07c` for TIO7 - are exact
mirrors. Every symbol in one has a twin in the other at +2 bytes: 0x804A64/0x804A66,
0x804C22/0x804C24, 0x804F74/0x804F78, 0x80500E/0x805010, 0x80501C/0x80501E. They
share 965 of their symbols and differ only in which slot they address.

That is the same relationship the four shift-element channels have with each other.
These are instances of one parameterised driver, so no amount of reading the driver
will say which physical solenoid is on the other end of the wire. The distinction
lives further upstream, in whatever writes the per-channel targets 0x80429A and
0x80429C, or in the board wiring from MCU pin to connector - and pin 102 or pin 104
to connector B54 pin 23 is not something either manual states.

One asymmetry is worth noting for later: in its fallback branch TIO7 uses an extra
calibration constant, 0x1C2AE, that TIO5 has no equivalent for, selected when the
state byte 0x8048D2 equals 2. TIO5's fallback instead sets a mode variable to 1 or 2
and passes it to its terminating call. So they are not quite identical, and that
constant is the thread to pull next.

### 29c. What the ATF blend breakpoints actually do

An open item from earlier - the meaning of 0x1C3BD and 0x1C3BE - falls out of this.
Both drivers compute their command by interpolating between two target values:

    if (0x1C3BD < atf && atf < 0x1C3BE)
        target = (cold * (0x1C3BE - atf) + warm * (atf - 0x1C3BD))
                 / (0x1C3BE - 0x1C3BD)

with `atf` read from 0x8047FB. So the pair is the ATF TEMPERATURE WINDOW over which
solenoid target pressure crosses from a cold calibration to a warm one. Below the
first breakpoint the cold value applies, above the second the warm one.

In the base ROM they read 55 and 175, which on the confirmed -40 encoding is
**15 C to 135 C** - a sensible window for exactly that job.

A caution against reading the table above too quickly: those two addresses are BASE
ROM addresses. Sampling them in the other fifteen firmwares gives incoherent pairs
like 255/255, 0/0 and 207/0, which is not evidence of odd calibration - it is the
constant having relocated, the same way every other family does. Per-firmware
addresses are needed before this can be exposed as a table, and the relocation has
not been derived yet.

---

## 30. NAMING THE DENSO TABLES: WHAT WORKED, AND WHERE IT STOPPED

Section 29 left the Denso tables indexed but unnamed. Disassembling the image was
supposed to close that. It closed part of it.

### 30a. The index is solid

The pointer runs are real and reproducible - 140 to 186 indexed tables per image
against 250 to 346 header candidates, in two generations. That filter now decides
what the definition ships, and it is the most useful thing to come out of this.

### 30b. Tracing a run back to its reader mostly fails

The plan was to name a group by naming the function that reads its index. It does not
work, for a reason worth recording rather than rediscovering:

  - only 2 of 32 runs have a direct code reference
  - the run START addresses appear NOWHERE in the image as 32-bit words
  - searching backwards for a real array base that something points at found 1 of 32

So the arrays are not reached by loading a literal address. SH-2 code reaches them by
some computed route - a base register plus an index, or a table of tables - and
recovering that needs the arithmetic read per site rather than a reference lookup.
Anyone repeating this should skip the xref approach and start from the two functions
below.

### 30c. What the two readable functions show

`FUN_00084dc8` and `FUN_00084f7c` are the exceptions, and they are dispatchers:

    if (state_byte < threshold && flag == 1)  arrays = A
    else if (state_byte < threshold)          arrays = B
    else if (flag == 1)                       arrays = C
    ...
    value  = lookup2d(arrays, axis1, axis2)
    result = blend(other1, other2, value)

Which is the same shape as the unanswered question on the M32R side - several
complete table sets, selected by operating condition, then interpolated. The
condition inputs here are a byte at PTR_DAT_00084f34 compared against DAT_00084f38,
and a flag at DAT_00084f3c tested against 1.

That is a concrete lead: identify those two RAM locations and the selection rule
falls out, for a family where the tables are already located and indexed. It is a
better starting point than the 86-family classification problem, because it needs two
answers rather than eighty-six.

---

## 31. FULL DISASSEMBLY OF A DENSO IMAGE, AND WHY THE TABLES STILL RESIST NAMING

Section 30 blamed the failed table-to-reader trace on partial coverage. That was a
reasonable guess and it was wrong. Fixing the coverage did not fix the trace.

### 31a. Coverage is now complete, and 100% is the wrong target

Auto-analysis reaches 28.3% of the image. Sweeping every 2-byte-aligned address
outside the known calibration blocks raises that to 50.8% instructions plus 9.6%
known table data.

The remaining 38% is not missing code. Classifying the image by content:

    code-like        46.6%   477 KB
    other data       33.3%   341 KB    constants, float arrays, non-header tables
    blank flash      12.6%   129 KB    unprogrammed 0xFF
    known tables      6.5%    66 KB
    ASCII             0.8%     7 KB

50.8% disassembled against 46.6% code-like means essentially all the code is now
instructions. Pushing past that would mean decoding blank flash and constant pools,
which manufactures exactly the false cross-references that wasted time earlier: an
unrestricted sweep produced 77 referrers to the shift-schedule array, every one of
them the sweep reading its own mis-decoded pointers. tools/denso_data_ranges.py
computes the blocks to leave alone, from the table headers themselves.

### 31b. The arrays are still unreferenced, and now that means something

With the code fully disassembled the calibration pointer arrays STILL have zero
references from outside themselves. That is no longer a gap in the analysis; it is a
fact about the firmware. The addresses are computed, not loaded.

### 31c. GBR is not the answer, but it is worth knowing

SH-2 has a global base register, and this firmware leans on it: about 2650 mov.b and
1150 mov.w accesses are GBR-relative, set from 248 ldc sites. Ghidra cannot resolve
@(disp,GBR) without knowing GBR, so none of those produce cross-references - which
looked like the explanation.

It is not. Resolving what those sites load gives values like 0xFFFF31A8, 0xFFFF37AC
and 0xFFFF3FF8: all on-chip RAM, consistent with the initial stack pointer at
0xFFFFBFA0. GBR is used for fast access to RAM STATE VARIABLES, not for reaching
calibration tables in ROM.

Recording the method as well as the answer, because the first attempt got it wrong in
a way that looked convincing: walking back from "ldc rN,gbr" to the instruction that
set rN and taking its first scalar operand returns 4, 8, 0x0C and so on. Those are
the displacements of mov.l @(disp,PC),rN, not the constants it loads. The value has
to be read through the instructions reference, from the literal pool.

---

## 31. FULL DISASSEMBLY OF A DENSO IMAGE, AND WHY THE TABLES STILL RESIST NAMING

Section 30 blamed the failed table-to-reader trace on partial coverage. That was a
reasonable guess and it was wrong. Fixing the coverage did not fix the trace.

### 31a. Coverage is now complete, and 100% is the wrong target

Auto-analysis reaches 28.3% of the image. Sweeping every 2-byte-aligned address
outside the known calibration blocks raises that to 50.8% instructions plus 9.6%
known table data.

The remaining 38% is not missing code. Classifying the image by content:

    code-like        46.6%   477 KB
    other data       33.3%   341 KB    constants, float arrays, non-header tables
    blank flash      12.6%   129 KB    unprogrammed 0xFF
    known tables      6.5%    66 KB
    ASCII             0.8%     7 KB

50.8% disassembled against 46.6% code-like means essentially all the code is now
instructions. Pushing past that would mean decoding blank flash and constant pools,
which manufactures exactly the false cross-references that wasted time earlier: an
unrestricted sweep produced 77 referrers to the shift-schedule array, every one of
them the sweep reading its own mis-decoded pointers. `tools/denso_data_ranges.py`
computes the blocks to leave alone, from the table headers themselves.

### 31b. The arrays are still unreferenced, and now that means something

With the code fully disassembled the calibration pointer arrays STILL have zero
references from outside themselves. That is no longer a gap in the analysis; it is a
fact about the firmware. The addresses are computed, not loaded.

### 31c. GBR is not the answer, but it is worth knowing

SH-2 has a global base register, and this firmware leans on it: about 2650 `mov.b`
and 1150 `mov.w` accesses are GBR-relative, set from 248 `ldc` sites. Ghidra cannot
resolve `@(disp,GBR)` without knowing GBR, so none of those produce cross-references -
which looked like the explanation.

It is not. Resolving what those sites load gives values like 0xFFFF31A8, 0xFFFF37AC
and 0xFFFF3FF8: all on-chip RAM, consistent with the initial stack pointer at
0xFFFFBFA0. GBR is used for fast access to RAM STATE VARIABLES, not for reaching
calibration tables in ROM.

Recording the method as well as the answer, because the first attempt got it wrong in
a way that looked convincing. Walking back from `ldc rN,gbr` to the instruction that
set rN and taking its first scalar operand returns 4, 8, 0x0C and so on. Those are the
displacements of `mov.l @(disp,PC),rN`, not the constants it loads. The value has to
be read through the instruction's reference, from the literal pool.

### 31d. Where this leaves the Denso side

What holds: the pointer index, 140 to 186 real tables per image, the twelve shift
schedules, the checksum, and now a fully disassembled image.

What does not: naming the remaining tables by static analysis. The route from code to
table is computed at runtime, and neither cross-references nor GBR resolution recovers
it. Emulating the relevant routines would, and that is a different and much larger
undertaking than anything attempted here.

---

## 32. THE DOWNSHIFT RAMP PAIR, SETTLED

Section 26a left a doubt worth closing. `Downshift Ramp Step` and `Downshift Ramp
Hold` were labelled from the code but never confirmed, and rimwall's account of the
control scheme would make the first a step COUNT rather than a pressure. If those two
were the wrong way round, anyone tuning them would be editing the wrong field.

They are correct. The control loop in the base ROM reads:

    DAT_00804a8c = DAT_00804a8c + 1;                         // ticks every cycle
    if (DAT_00804a8c < *(ushort *)(&PTR_DAT_0001200e + i))   // 0x1200E
        pressure = min(DAT_00804a92, DAT_00804a94);          //   hold, pressure unchanged
    else
        pressure = DAT_008046e6                              // 0x1200C
                 + *(ushort *)(&DAT_0001200c + i * 4);       //   add the step

The halfword at 0x1200E is compared against a counter that increments once per cycle,
so it is a DURATION in ticks. The halfword at 0x1200C is ADDED to a pressure, so it is
a pressure STEP. The two sit 4 bytes apart per downshift, matching the ten-entry
structure the extractor locates.

So the shipped labels stand, and the doubt is closed rather than left hanging.

It also says what rimwall's lever actually is here. Shortening a shift means reducing
the HOLD at 0x1200E, so the ramp starts sooner, or raising the STEP at 0x1200C so the
target pressure is reached in fewer cycles. Both are already editable.

---

## 33. HOW A SHIFT SCHEDULE IS CHOSEN

The oldest open question in this project - which operating condition selects which of
the ten shift schedules - is answered. It was never going to come from pattern
scanning; it is four lines of arithmetic in the base ROM.

Searched first, which is worth recording: GitHub has essentially nothing on this ECU.
A repository search for "5EAT" returns this project and two empty repositories, and
"subaru transmission TCU" returns this project alone. `miikasyvanen/FastECU-m32r-flasher`
is a recovery flasher with no table definitions. There is no prior work to borrow.

### 33a. The selection

    DAT_00804B94 = DAT_0080485A * 2 + sVar1 * 10;
    schedule     = (&PTR_DAT_00017714)[DAT_00804B94];
    partner      = (&PTR_DAT_00017718)[DAT_00804B94];

Two pointer arrays, four bytes apart, indexed by one computed value. The `* 10` is
the ten-schedule structure this project inferred from the data years of session notes
ago, appearing directly in the code.

`sVar1` picks the group of ten and comes from `FUN_00043428`:

    if (DAT_00804858 == 0x80 || 0x84 || 0x8C)  sVar1 = 0
    else if (DAT_00804858 == 0x85)             sVar1 = 1
    else if (DAT_00804858 == 0x81)             sVar1 = 2
    else if (DAT_00804858 == 0x82)             sVar1 = 3
    else if (DAT_00804858 == 0x83)             sVar1 = 4

`DAT_00804858` holds 0x80 to 0x85 and 0x8C. A small contiguous range of high-bit-set
byte codes selecting one of five groups is a selector or range position, and it
confirms from the code what section 17a inferred from the data: the five-axis is a
GEAR LIMIT, not the fuelling state rimwall read it as. It initialises to 0x84, which
maps to group 0 - the same group as 0x80 and 0x8C.

`DAT_0080485A` picks within the group and holds 0 to 4, tested that way in about 189
places across the firmware. That is the operating condition itself.

### 33b. What is still not established, and a table this project does not ship

Which physical condition each value of `DAT_0080485A` corresponds to. Sasha_A80's
list from the forum - cold engine, warm engine, cold ATF, warm ATF, catalyst preheat,
quick shift, hill assist, driver style - remains the candidate set, and nothing here
picks between them. A log of that one byte against driving state would settle it in a
single drive.

More useful in the short term: `DAT_00804858` is not read from a sensor. It comes
from `FUN_000433D8`, which reads a byte from a TABLE at 0x10108:

    cVar1 = *(char *)(DAT_0080486E * 4 + 0x10108 + ((DAT_008052B3 ^ 0xFF) & 7) - 3);
    if (cVar1 != 0 && cVar1 != -1) return cVar1;

So the mapping from whatever `DAT_0080486E` is to a selector position is
CALIBRATION DATA, at 0x10108 in the base ROM, and this project does not currently
ship it. That is a tunable that decides which schedule group applies, and it is a
better target than the remaining unidentified curves.

---

## 34. THE FIRST REAL VEHICLE DATA

Everything before this section is static analysis. A RomRaider log from a running
5EAT, 568 samples over 110 seconds, is the first time any of it has been checked
against a car.

Logged: accelerator angle, engine speed, SI-Drive mode, two turbine speeds, ATF
temperature, gear position, front and rear wheel speed, turbine revolution speed, and
the pressure of all seven solenoids by name - AWD, D/C, F/B, Fwd/B target, H&LR/C,
I/C, L/U and P/L. A full drive: 0 to 173 km/h, 599 to 6944 rpm, all five gears, ATF
87 to 92 C.

### 34a. Lock-up engages in FOURTH as well as fifth

The working assumption in this project was that lock-up is fifth-gear only. It is not.

    gear   samples   L/U engaged   max L/U   speed range
      1      225           0          0      0-73 km/h
      2       10           0          0     77-103 km/h
      3       91           0          0      0-146 km/h
      4      110          25        130 kPa 98-173 km/h
      5      132         121        260 kPa 21-104 km/h

Never below fourth, which is the part that was right. But fourth gets partial
engagement at roughly half the pressure fifth reaches, on 23% of its samples against
92% in fifth. Engine-to-turbine slip across all engaged samples runs -79 to +383 rpm,
so the converter really is locking rather than the channel merely being commanded.

The assumption never reached the definition or the documentation, so nothing shipped
needs correcting. It would have, eventually.

### 34b. The seven solenoids are confirmed, by name and by range

Section 22 identified seven PWM channels from the firmware and section 23a matched
them to the Select Monitor's names. The log confirms both, and gives working ranges:

    P/L    350 - 2520 kPa      line pressure
    H&LR/C  20 - 1760 kPa
    I/C      0 - 1400 kPa
    D/C      0 - 1390 kPa
    Fwd/B    0 - 1390 kPa      target
    F/B      0 -  900 kPa
    AWD      0 -  410 kPa      transfer clutch
    L/U      0 -  260 kPa      lock-up

### 34c. What the log does NOT settle, and one thing it complicates

It does not identify which firmware channel is lock-up. The log reports Select Monitor
parameters by name, not RAM addresses, so it cannot distinguish 0x804EB2 on TIO5 from
0x804EB6 on TIO7. Resolving that needs the duty addresses themselves logged, which
this capture does not include.

It also complicates one earlier reading, and the honest thing is to record that rather
than let it pass. The P/L parameter reaches 2520 kPa, well above the 1370 kPa this
project confirmed as the full-throttle line pressure from the service manual and found
in a table in all sixteen images. Both cannot be the same quantity. The likeliest
reading is that the Select Monitor's "P/L Solenoid Valve Pressure" is the solenoid's
own commanded pressure while the tables hold a line pressure TARGET, but that is a
hypothesis and is not established here. The kPa finding itself stands - it was
verified against the manual and against the firmware's own arithmetic - but the
relationship between the logged parameter and the table is not what was assumed.

Two shorter notes. SI-Drive mode reads 1 for the whole capture, so it tells us nothing
about whether it selects a shift schedule. ATF sat at 87 to 92 C throughout, inside the
15 to 135 C blend window from section 29c, so the solenoid targets were mid-blend the
entire time.

---

## 35. WHAT THE LOG CAN AND CANNOT VALIDATE

Section 34 took the easy results from the vehicle log. This section is the attempt to
use it to validate the shift maps, which did not work, and the reasons are worth more
than the attempt was.

### 35a. Gear Position in the log LAGS the real shift

The ratio of turbine speed to road speed is a direct measure of which gear is engaged.
Across the first upshift it reads:

    time    logged gear   km/h   turbine/km-h
    42.6s        1         60        106
    42.8s        1         63        105
    43.0s        1         67         92
    43.2s        1         69         78
    43.4s        1         73         68
    43.6s        2         77         68

Measured steady-state ratios are 101 for first and 64 for second. So the transmission
was already at second-gear ratio by 43.4s while the logged `Gear Position` still said
first, and the change physically began around 43.0s. The logged gear trails the real
event by roughly 0.4 to 0.6 seconds.

Anyone reading a shift speed straight out of one of these logs will read it late - by
about 10 km/h under hard acceleration. That is not a sampling artefact; the interval
is 194ms and only buys 1 to 5 km/h.

### 35b. So the shift maps are NOT validated by this log

Taking the logged gear at face value gives 1-2 at 77 km/h, 2-3 at 106 and 3-4 at 148,
against 43, 87 and 144 from the base ROM's tables at full pedal. The 3-4 figure looks
like a 3% match and it is not evidence: the same table set is 79% out on 1-2, and the
lag above explains part but not all of the gap.

The larger problem is that the logged car's firmware is unknown. It need not be one of
the sixteen here, and shift speeds depend on final drive and tyre size as much as on
the table. Comparing a log from one car against another car's calibration cannot
validate anything, and reporting the 3-4 number as agreement would have been a
coincidence dressed as a result.

To actually validate the shift maps: log a car whose ROM has been read, so the
calibration is known, and derive the shift instant from the turbine/road-speed ratio
rather than the reported gear.

### 35c. What the log does establish

**Measured gear ratios.** Turbine speed against road speed, steady state:

    gear 1   101 turbine-rpm per km/h
    gear 2    64
    gear 3    43
    gear 4    30
    gear 5    26

Normalised against fifth those are 3.94, 2.48, 1.69, 1.16, 1.00, against published
ratios of 4.25, 2.72, 1.76, 1.20, 1.00. Fourth and fifth agree within 3%; the lower
gears read low because their samples are nearly all taken during hard acceleration
where the converter and the shift itself are still settling, and there are only 10 to
21 of them.

**Lock-up thresholds.** Fourth engages from 98 km/h at 2611 rpm, fifth from 44 km/h at
1126 rpm. Fifth reaches 260 kPa, fourth only 130.

**AWD behaviour.** Front-to-rear wheel speed difference stays between -2 and +4 km/h,
mean 0.15, so the transfer clutch is holding the axles close to locked throughout.

---

## 36. THE LOGGED CAR IDENTIFIED, AND WHY FULL-THROTTLE SHIFTS IGNORE THE SPEED TABLE

The logs came from unit A3DE207100. That single fact overturns section 35 and produces
the most useful result the logs have given.

### 36a. It is a DENSO image, and one already shipped

A3DE207100 is 1 MB, opens `00 00 0b f8` - the SH-2 reset vector - and has no ASCII
calibration id at 0x8008. It is not an M32R image at all, which is why the M32R
checksum reports it as broken and why the M32R decompile script has always skipped
`A3DE*`.

Its Denso calibration id at 0x2000 is **WQDE2WB1**, and it is byte-for-byte identical
to `rom-denso/Impreza_STI_3.583_JDM2011.bin`. So this project already ships a
definition for the exact firmware these logs came from.

Section 35 compared the log against the base M32R ROM's tables. That was the wrong
family entirely. The conclusion there - that the comparison proved nothing - stands,
but the reason was worse than stated.

### 36b. At full pedal the shift is RPM-limited, not speed-limited

Every one of WQDE2WB1's twelve shift tables reads 224 or 205 km/h in its full-pedal
column. This car does not reach those speeds, so at wide-open throttle the speed table
never fires. Its top entry is effectively "do not upshift on road speed".

What actually triggers the shift is engine speed. Taking the shift instant from the
turbine-to-road-speed ratio and converting through the measured gear ratios:

    shift    road speed    turbine rpm at the shift
    1->2       73 km/h            7300
    2->3      103 km/h            6592
    3->4      146 km/h            6278

against a logged maximum of 6944 rpm. Those are redline shifts.

This explains why no comparison of full-throttle shift points against the speed tables
could ever have worked, in either family. The tables govern part-throttle shifts; at
full pedal a different limit takes over.

### 36c. The one part-throttle shift is consistent, not confirmed

The 4-5 upshift at 99 km/h and 2970 rpm is a genuine speed-driven change. Searching all
twelve tables for entries within 8 km/h of 99 returns 47 of them, spread across nine
tables at pedal positions from 25% to 60%.

Consistent with the tables, and no more than that. The log has an accelerator angle
column but it is empty, so there is no way to say which entry applied. A log with
pedal recorded would turn this into a real check, and it is now a small ask: the
firmware is known, the tables are decoded, and only one channel is missing.

### 36d. Correction to section 35

Section 35 said the reported gear lags the real shift by 0.4 to 0.6 seconds and that
reading a shift speed straight from the log puts it about 10 km/h late. The lag is
real, but the effect was overstated. Recomputing the shift instants from the ratio
moves them by only 2 to 4 km/h - 77 to 73, 106 to 103, 148 to 146. The correct
statement is that the reported gear lags, and it is worth deriving the instant from
the ratio, but the error it introduces is small.

---

## 37. THE SHIFT TABLES READ PROPERLY, AGAINST THE CAR THAT RAN THEM

### 37a. First, a correction: the pedal WAS logged

Sections 34 and 36 state that the accelerator angle column is empty. It is not. All
568 rows carry a value; the column uses a **comma decimal separator** (`0,00`), and the
parser silently dropped every one of them. The same fault would have hidden any other
fractional column.

Anyone writing a tool against these files should convert the comma before parsing.
`float("0,00")` does not raise a useful error, it simply fails, and a column of real
data reads as absent.

### 37b. The table structure, resolved

Each 15x5 table has one unused row and four live ones. Reading a pair:

    table 0, pedal:   0   5  10  15  20  25  30  35  40  50  60  70  80  90 100
      y=1            19  19  19  19  22  29  40  80  85 100 120 142 181 224 224
      y=2            29  29  29  29  29  35  51  80  85 100 120 142 181 224 224
      y=3            44  44  44  44  49  54  64  80  85 100 120 142 181 224 224
      y=4            54  54  54  54  59  66  76  80  85 100 120 142 181 224 224

The four live rows are the FOUR UPSHIFTS. At idle they read 19, 29, 44 and 54 km/h,
rising in order, which is what 1-2, 2-3, 3-4 and 4-5 must do. Even-numbered tables
converge on 224 and odd ones on 205, so the twelve are six upshift/downshift pairs -
six schedules, not twelve.

### 37c. Above about 35% pedal the speed table stops deciding

Every curve flattens into the same tail - 80, 85, 100, 120, 142, 181, 224 - regardless
of which shift it governs. At full pedal all four upshifts would need 224 km/h, which
this car never reaches. The entry means "do not upshift on road speed".

The observed full-throttle shifts confirm it. Converting through the measured gear
ratios they occur at 7300, 6592 and 6278 turbine rpm against a logged maximum of 6944.
They are redline shifts, governed by an engine speed limit that is not in these tables.

This is worth stating plainly for anyone tuning: **raising or lowering the high-pedal
end of a shift curve will not move a full-throttle shift point.** Only the part-throttle
region of the curve does anything.

### 37d. And below that, the table is necessary but not sufficient

The log contains one genuine part-throttle upshift. The car cruised at 99 km/h in
fourth at 18% pedal for four seconds, then went to fifth as the pedal eased to 17%.

At 17% pedal the 4-5 threshold reads 56 km/h in table 0, and across all twelve tables
the highest is 74 km/h in table 4. The car sat 25 to 45 km/h above every threshold it
has, in the right gear, at a steady speed, and did not shift for four seconds.

So something inhibits the upshift beyond the speed comparison. A timer, a temperature
condition, or hold-gear logic following the hard acceleration run that preceded this
stretch - the car had just come down from 173 km/h. The shift schedule tables give a
threshold; they do not by themselves decide when the shift happens.

That is the most useful thing the log has said about the tables, and it could not have
been found without a car.

---

## 38. WHICH ELEMENT IS APPLIED IN WHICH GEAR

The log records the pressure of every solenoid alongside the gear, which gives the
clutch and brake application directly - useful because it says which pressure table
affects which gear, and that is not obvious from the tables themselves.

Median pressure in kPa, by gear:

    solenoid      gear 1   gear 2   gear 3   gear 4   gear 5
    H and LR/C        60      610     1420     1420     1420
    D/C                0     1390        0     1390        0
    F/B              890      890      890        0      890
    I/C                0        0        0     1400     1400
    Fwd/B target    1390      330        0        0        0
    L/U                0        0        0        0       40
    AWD              140      240        0       40       30
    P/L              600     2400      350      440      410

Reading off the elements above 100 kPa:

    gear 1    Fwd/B + F/B
    gear 3    H&LR/C + F/B
    gear 4    H&LR/C + D/C + I/C
    gear 5    H&LR/C + F/B + I/C

Two or three elements per gear, changing between gears, which is what a five-speed
planetary box must do.

**Gear 2 is not usable and its column should be ignored.** It has 10 samples against
91 to 225 for the others, and all of them fall inside a hard acceleration run, so its
medians describe a shift in progress rather than a gear being held. Its P/L median of
2400 kPa is the same artefact - that is a shift pressure spike, not second-gear line
pressure. Any figure in that column needs a log with a sustained second-gear cruise
before it means anything.

The other four columns each rest on at least 91 samples, nearly all with the pedal
steady, so they describe held gears.

Two observations worth carrying forward. H&LR/C reads 1420 kPa in third, fourth and
fifth and only 60 in first, so it is the element that distinguishes the low gear from
the rest. And L/U appears only in fifth here at a median of 40 kPa, consistent with
section 34 finding it engaged in fourth as well but far less often - a median across
all fourth-gear samples washes it out.

---

## 39. GEAR RATIOS LOCATED IN BOTH FAMILIES, AND A VARIANT WE DO NOT HAVE

The 2006 Tribeca service manual quotes gear ratios of **3.841, 2.352, 1.529, 1.000
and 0.839**. This project has always used **3.540, 2.264, 1.471, 1.000, 0.834**,
confirmed to within 0.0007 in section 4. Both are correct; they are different 5EAT
variants, and noticing that turned out to be worth more than the discrepancy itself.

### 39a. The table is at a fixed address in every image

Searching for a run of five values matching either set finds one in all 25 firmwares:

    M32R    0x0844C in fifteen images, 0x0844A in the base ROM, as uint16 / 1024
    Denso   0xB9234 to 0xCE658 depending on the image, as IEEE-754 float

Each family stores them in its own convention - the same split seen everywhere else
between the two. This is an independent confirmation of the `/1024` scaling: the
ratios were originally derived from published figures, and here they are as a clean
five-value run at a consistent address, in every image, arrived at from the other
direction.

### 39b. All 25 images use the Legacy set, including both Tribecas

Every M32R image and every Denso image carries 3.540 through 0.834 - including
`Tribeca_3.583_EDM_2009` and `8EFB206000` from the 2014 USDM Tribeca.

So the 3.841 set the 2006 manual documents appears in nothing this project holds.
Either the early Tribeca used a transmission variant later ones did not, or its
calibration is one nobody here has dumped.

### 39c. Why that matters for the bench unit

A 2006 Tribeca TCM is now on the bench. If its ROM carries the 3.841 ratio set it is a
variant this project has never seen, and reading it would be the most valuable single
contribution available - a new calibration family rather than another member of one
already covered.

The check is cheap and needs no bench rig at all: dump the ROM and look for five
consecutive values that decode to 3.841, 2.352, 1.529, 1.000, 0.839. `uint16 / 1024`
if it is M32R, IEEE-754 float if Denso. Their addresses above say where to start
looking.

It also means the ratios in a definition are not a constant of the 5EAT. Anyone
comparing a log against tables - as section 36 did - needs the ratios for the car that
produced the log, not for the family in general.

---

## 40. THE SELECT MONITOR TABLE NAMES THE RAM, AND FreeSSM WAS NOT A DEAD END

Section 11m closed FreeSSM as a dead end. That conclusion was too broad, and the
correction is rimwall's - forum topic 13725, post 391. Section 11m looked for
per-model TCU definitions in `SSM1defs_*.xml` and the transmission dialog, found
only generic wiring, and stopped. It never opened the file that matters:
FreeSSM's
`SSMFlagbyteDefinitions_en.cpp` is the ordered list of every parameter the Select
Monitor can report, with units and conversions, and the TCU ROM holds the other
half of the same mapping. Joining them names RAM addresses, which is the thing
that was missing.

### 40a. The table, and where it is

Every M32R image carries a run of 512 big-endian pointers into on-chip RAM,
indexed by SSM address, with a single dummy address filling every slot the unit
does not support:

    ACD1A06000    0x1D600      76 supported of 512
    ACD1207000    0x1D5F0      76
    the other 14  0x1C5D4 to 0x1D44C   74 each

rimwall gave `0x1d600` in `ACD1A06000` and it is exactly right. Reading entry `n`
gives the RAM address the Select Monitor reads when asked for SSM parameter `n`.
Cross-referencing against FreeSSM names **36 or 37 parameters per image**.

The check that this is real rather than a coincidence of ranges: SSM addresses
`0x0E` and `0x0F` are Engine Speed's two halves in FreeSSM, and in the ROM they
map to `0x00805139` and `0x0080513A` - adjacent, in order, as a 16-bit value must
be.

### 40b. The addresses are a staging buffer, and that is the useful part

The named addresses are contiguous, which is the signature of a copy made for the
Select Monitor rather than of the variables the control logic uses. That could
have been a disappointment. It is the opposite: the routine that fills the buffer
names its own sources, so one hop back gives the working variable *and* its
scaling.

    DAT_00805139 = (undefined1)(((uint)DAT_008042bc << 2) >> 8);   Engine Speed
    iVar2 = (int)DAT_008046c6 / 100;
    DAT_00805173 = (undefined1)iVar2;                              L/U pressure

`tools/map_ssm_parameters.py` does the join and follows that hop, resolving the
temporaries Ghidra introduces for the range checks. It reports **27 working
variables per image**, consistent across all sixteen. Among them, for
`ACD1A06000`:

| parameter | working variable | scaling |
|---|---|---|
| Engine Speed | `0x8042BC` | `<< 2` |
| Turbine Revolution Speed | `0x8042CC` | `>> 5` |
| AT Turbine Speed 1 / 2 | `0x8042C8` / `0x8042CA` | |
| Gear Position | `0x804846` | |
| Accelerator Pedal Travel | `0x804923` | |
| Front / Rear Wheel Speed | `0x8051D6` / `0x8051D8` | `>> 8` |
| ATF Temperature 1 / 2 | `0x8047CC` / `0x8047DA` | |
| Battery Voltage | `0x804BAA` | |
| Solenoid pressures, H&LR/C to AWD | `0x8046CA`-`0x8046D4` | `/ 100` |
| **L/U solenoid pressure** | **`0x8046C6`** | `/ 100` |
| Solenoid currents, P/L to AWD | `0x80473C`-`0x80474A` | `* 255 / 400` |

The ten that do not resolve are the switch bitfields, assembled a bit at a time
rather than copied.

Note that the solenoid pressure block runs `0x8046CA` to `0x8046D4` in SSM order
H&LR/C, D/C, F/B, I/C, P/L, AWD - and **L/U sits apart at `0x8046C6`**, outside
that run. The lock-up channel is handled separately from the other six in the
M32R firmware, which is consistent with it being the one channel whose hardware
routing section 29 could not settle.

### 40c. This does not settle TIO5 against TIO7

Tempting, but no - though the first version of this section got the reason wrong
and said section 29 concerned the Denso firmware. It does not. `0x804EB2` and
`0x804EB6` sit in `0x0080xxxx`, which is M32R RAM, they appear only in
`decompiled/91D1206000_5EAT.c`, and section 29a takes its pin numbers from the
32176 Group User's Manual. **Section 29 is M32R throughout**, the same family as
this section, so the two are directly comparable.

They still do not settle it, for a substantive reason rather than a taxonomic
one. Running the mapping against `91D1206000` - the image section 29 analysed -
gives L/U solenoid current from `0x804758` and L/U pressure from `0x8046E2`. But
the pressure is computed as

    DAT_008046e2 = (short)((DAT_008045d6 * 100) / 0x100);

from `0x8045D6`, a commanded value, and neither address reaches `0x804EB2` or
`0x804EB6` within the two hops traced. What the Select Monitor reports for lock-up
is derived from the **demand** side, not read back from whichever timer output
actually drives the solenoid - so it cannot distinguish the two candidates. The
bench measurement in [docs/BENCH-RIG.md](docs/BENCH-RIG.md) remains what settles
it.

### 40d. Denso stores this differently, and it is not yet found

No Denso image has a comparable run. Their on-chip RAM lives at `0xFFFF8000` and
up, and a scan of that range finds 1745 distinct addresses across 5228
occurrences, scattered as SH-2 literal pools rather than gathered into a table.
The logs in `logs/` prove a Denso TCU answers the Select Monitor, so the mapping
exists in some form - most likely as displacements from GBR rather than absolute
addresses, which would fit the ~3800 GBR-relative accesses section 27 counted.
Worth another look; the M32R result is what is established.

### 40e. rimwall's drive mode enumerations

Recorded from post 391 as his work, not verified here. Section 33 found the
schedule index is `condition x 2 + group x 10` without establishing what each
condition value means; this is a direct answer to that, and checking it against
the selector table is the obvious next step.

Denso SH7058S: 0 unused, 1 I-Mode, 2 Normal (Sport), 3 Sport#, 4-7 unknown, with
5 to 7 possibly hard acceleration or temperature conditions.

Hitachi M32R: 0 Normal (Sport), 1 Sport#, 2 unused, 3 unknown, 4 Manual Mode,
5-7 unknown, 8 ATF Temp Low, 9 unknown, 10 unused, 11 I Mode, 12 Slope,
13 Kickdown / hard acceleration.

He has also offered his working decompiler listings - roughly 1000 of 1300 M32R
functions and 2800 of 4200 Denso functions given meaningful names, with comments
and named RAM values - and a spreadsheet of reference material. That would be the
single largest input this project could receive.

---

## 41. THE SSM PATH CROSS-CHECKS THE UNIT SCALINGS, AND CONTRADICTS ONE OF THEM

Section 40 named RAM addresses. That does not by itself add anything to the
definition, which describes ROM tables - different address space, different
purpose. What it does give is the first **independent check** on the unit scalings
the definition depends on, because the routine that fills the Select Monitor
buffer applies a known conversion to a variable FreeSSM independently names.

Read together: `ROM conversion` then `FreeSSM conversion` must produce the real
physical quantity. Two agree with this project. One does not.

### 41a. Confirmed

| quantity | ROM applies | FreeSSM applies | implies |
|---|---|---|---|
| Turbine speed | `>> 5` | `x * 32` | working variable is **rpm directly** |
| Gear position | none | `x + 1` | working variable is **zero-based** |
| Accelerator pedal | none | `x / 255 * 100` | working variable is **0-255 for 0-100%** |
| Solenoid pressure | `/ 100` | `x * 10` | working variable is **kPa x 10** |
| Solenoid current | `* 255 / 400` | `x / 255` | working variable is **mA-ish, full scale 400** |

The turbine speed result is the useful one: the two conversions cancel exactly, so
`0x8042CC` holds rpm with no scaling at all. That is consistent with section 11s
and arrived at independently.

The pressure result is worth carrying into section 34, which recorded that the
Select Monitor reported P/L up to 2520 kPa where the line-pressure tables hold
1370. The working variable being `kPa x 10` is a lead on that, not yet a
resolution.

### 41b. Contradicted: ATF temperature, by 15 degrees

Section 11t established **`°C = raw - 40`** and the definition applies `x-40` to
thirteen tables, including every ATF temperature axis and the cold-lockout
constants.

The SSM path disagrees. For `ACD1A06000`:

    DAT_008047cc = FUN_00046cd4(&DAT_00008080, 0, adc);      linearisation lookup
    SSM value    = DAT_008047cc - 5
    FreeSSM      = value - 50                                 SSM 0x56

so the firmware's own published temperature is **`raw - 55`**, not `raw - 40`.

These are the same variable, not two encodings of one quantity. `FUN_00046cd4`
looks up the table at ROM `0x8080`, which is exactly what the definition calls
`Temp Sensor 1 Linearisation - °C`, and its result is what `0x8047CC` holds.

**Neither figure is measured.** Section 11t inferred `-40` from plausibility: the
tables map `0..255` onto `0..255`, and `-40` makes that `-40 °C` to `+215 °C`,
the standard automotive unsigned encoding. That is a good argument, not a
measurement. FreeSSM's `-50` is equally unverified for this unit - its list is
shared across every Subaru controller, it carries three different ATF temperature
encodings for different SSM addresses, and nothing says the TCU follows the same
one as the ECU.

What is new is that there is now evidence on both sides where before there was
plausibility on one. Under `-55` the constants section 11t decoded as
`-10, -5, 15, 38, 55, 65, 71, 75, 95, 125, 135, 139, 145 °C` become
`-25, -20, 0, 23, 40, 50, 56, 60, 80, 110, 120, 124, 130 °C`, and the ATF blend
window of section 32 moves from 15-135 °C to 0-120 °C. Both sets are physically
plausible for a transmission.

**The definition has not been changed.** Rescaling thirteen tables on an inference
would replace one unverified number with another. If `-40` is wrong then every ATF
axis in the definition is out by 15 °C, which matters to anyone tuning temperature
compensation, so this is recorded as a live uncertainty rather than a settled
detail.

### 41c. Evidence, from the family that stores temperature in real units

The service manual does not settle it. Its P0712 and P0713 procedures test for an
open or shorted circuit, not for a threshold in degrees, and the only temperatures
quoted anywhere in the transmission section are 20, 25 and 80 °C - the last as a
warm-up instruction, with the sensor reading 500-1,200 ohms at that point. That
pins the sensor, not the encoding.

The Denso family does better, because it stores axes as IEEE floats in real units
and so carries no offset at all. Scanning `Impreza_STI_3.583_JDM2011` for monotonic
float runs in a temperature range finds one axis repeated at `0xA0344`, `0xA038C`
and `0xA0490`:

    20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130 °C

That is the range Subaru calibrates this gearbox over. Against it, the M32R blend
window of section 32 - which RomRaider reads out of `ACD1A06000` as `15.0, 135.0`
under the current scaling, from raw 55 and 175 - brackets the calibrated range
symmetrically, five degrees clear at each end. Under `-55` the same window reads
`0, 120`, putting its warm limit *inside* the calibrated range and cutting off the
top ten degrees of it. A blend window that stops short of the data it blends is
the less likely design.

**The evidence therefore favours `-40`, and the definition stays as it is.** This
is a consistency argument across two firmware families rather than a measurement,
so 41b's uncertainty is reduced rather than closed.

### 41d. What would close it

Feed the ATF sensor input a known resistance on the bench unit, read the raw
linearisation output over the Select Monitor, and compare. One measurement at one
known temperature decides it outright.

If `-55` did turn out to be right, the fix is mechanical: thirteen tables in the
M32R definition change `x-40` to `x-55` and `x+40` to `x+55`. Nothing else in the
project depends on the offset.

---

## 42. THE DENSO SELECT MONITOR TABLE, FOUND BY READING THE HANDLER

Section 40d recorded that no Denso image had a parameter table like the M32R one,
and guessed it was probably stored as GBR displacements. That guess was wrong, and
the table was found the way section 40 should have been approached from the start:
by reading the code rather than scanning for a shape.

### 42a. The handler has the same structure in both families

The M32R request handler splits on the requested address:

    if ((uVar7 < 0x200) && ((DAT_00805001 & 2) == 0)) { table lookup }
    else                                              { direct read }

Searching the Denso listing for the same two conditions finds one match, at line
4090 of `Impreza_STI_3.583_JDM2011.c`:

    if (((*(byte *)(iVar1 + 5) & 2) == 0) && (uVar2 < 0x200)) {
        *(undefined4 *)DAT_00009bb2 =
            *(undefined4 *)(PTR_DAT_00009be0 + (addr & 0xffff) * 4);
    }

`PTR_DAT_00009be0` is the table base. Reading the pointer stored at ROM `0x9BE0`
gives `0x00086870`, and that is the table.

### 42b. Why the scan missed it

Two assumptions in section 40's detector, both wrong for this family:

**Entries point into ROM as well as RAM.** The dummy address that fills every
unsupported slot is `0x000D1109`, a ROM address, and the five identifier bytes are
read straight out of ROM too. The detector only accepted RAM pointers, so the run
broke immediately.

**Denso RAM starts far lower than assumed.** The detector used `0xFFFF8000` as the
floor. Real entries reach down to `0xFFFF2800`, so even after admitting ROM
addresses the run broke at the first low one - 41 entries in, out of 512.

Both are now handled, and requiring the run to be exactly 512 entries long, which
both families are, is what keeps the wider address ranges from matching unrelated
pointer blocks.

### 42c. What it gives

All 25 firmwares now yield a table:

    M32R    16 images, 74 to 76 supported parameters, 36 or 37 named
    Denso    9 images, 86 to 95 supported parameters, 39 or 40 named

The Denso units report *more* than the M32R ones, which is the opposite of what
the older, smaller M32R calibrations would suggest.

### 42d. It is confirmed against a real car

Table entries 1 to 5 answer with the five identifier bytes. On the Denso side they
point straight at ROM, and for `Impreza_STI_3.583_JDM2011` they point at `0xD110E`,
where the bytes are:

    A3DE207100

which is exactly the unit identifier recorded in `logs/README.md` for the car
cortin logged - a car whose ROM is byte-identical to that image. The table was
located from the disassembly with no reference to the logs, and it independently
reproduces a fact established months earlier from a completely different source.

That also fixes how the identifier is found. Section 40 took it from a fixed
`0x802A`, which is right for the M32R but wrong for Denso, where the address moves
between images. Reading it from the table works for both.

### 42e. The logger definition now covers both families

`definitions/5eat_tcu_logger.xml` carries all 25 unit identifiers. The two lock-up
candidates stay restricted to the M32R units, since `0x804EB2` and `0x804EB6` are
M32R addresses and pointing a Denso unit at them would read an unrelated part of
its address space and report a number that looks perfectly reasonable.

Tracing Denso parameters back to their working variables is not done. The reason
given here first - that SH-2 reaches the RAM GBR-relative, so no symbol exists to
match - **was wrong**, and section 45 corrects it. The naming, which is what the
logger definition needs, is complete for both families; only the second hop to the
working variable is M32R-only.

---

## 43. WITHDRAWN - see section 51

This section concluded that rimwall's drive mode enumeration did not map onto the
schedule selector. It does. The comparison was made against two variables when
there are three, and the drive mode is the one this project had not found.
Superseded entirely by section 51, which verifies his mapping and formula against
the code.

## 44. THE 32176 HARDWARE MANUAL, AND WHAT IT CONFIRMS

The manual for the exact part in the M32R TCUs turns out to be public. It reads as
missing because Renesas files it as a *Hardware Manual*, not a User's Manual, so
the obvious URL 404s:

    32176 Group Hardware Manual   REJ09B0067-0110, Rev.1.10, Jun.2006, 744 pp
    Errata                        TN-32R-A080A/E, Sep.2010
    M32R Family Software Manual   MEJ19B0001-0102Z, Rev.1.2 (the instruction set)

All are downloadable without an account from renesas.com. Copies are kept outside
this repository - they are Renesas documents, not ours to redistribute.

### 44a. The lock-up pin assignment is confirmed

Section 29 traced the two torque converter candidates to package pins and could not
verify the mapping. The manual states it directly, in the pin assignment table:

    102 P115/TO5
    104 P117/TO7

which is exactly what section 29 recorded. The bench measurement in
[docs/BENCH-RIG.md](docs/BENCH-RIG.md) can be taken at those pins with confidence
that they are the right ones - the remaining question is only which of the two the
lock-up solenoid hangs off.

The package is **144-pin LQFP** (PLQP0144KA-A), which is worth stating because a
100-pin assumption would make both numbers meaningless.

Timer registers sit at `H'0080 0300` upward, and the manual places `TIO7CT` at
`H'0080 0370` and TIO5's reload registers around `H'0080 0356`. None of these
addresses appear in the decompiled listings, so the firmware reaches the timer
block through a base register rather than absolutely - which is why section 29 had
to identify the channel from the driver structure rather than from a register write.

### 44b. The RAM map, and an errata that matters

Section 3.4.2 gives the M32176F4 map as flash `H'0000 0000`-`H'0007 FFFF`, SFR
`H'0080 0000`-`H'0080 3FFF`, and **24 KB of internal RAM at `H'0080 4000`-`H'0080
9FFF`**.

Figure 3.2.1 misprints the RAM top as `H'008F 9FFF`, in three places in the text.
The errata corrects it to `H'0080 9FFF`. Anyone reading the manual alone would take
the wrong number.

This is checkable against the ROMs, and it checks out exactly. The sixteen M32R
parameter tables of section 40 point at **1,190 addresses, every one of them inside
`0x804000`-`0x809FFF`, none outside**. Two independent things confirm each other:
the errata is right, and the table extraction is picking up real RAM addresses
rather than coincidences.

`tools/map_ssm_parameters.py` now uses the documented window instead of the whole
`0x0080xxxx` page it assumed, which also excludes SFR space from consideration.
Detection is unchanged on all 25 firmwares.

### 44c. The processor module in use is the stale one

This project's disassembly used [ripnet/ghidra-m32r](https://github.com/ripnet/ghidra-m32r),
last touched March 2022, with five open issues and two unmerged pull requests. Two
better forks exist:

  * [StackwalkerInc/ghidra-m32r](https://github.com/StackwalkerInc/ghidra-m32r) -
    active, and it already carries rimwall's ADDX and TSTb31 work, audited. Worth
    noting that it **corrected** rimwall's `TSTb31`, which modified `Rdest` when it
    should not have. It also replaces rimwall's hardcoded frame-pointer base with a
    language variant.
  * [tiredboffin/ghidra-m32r](https://github.com/tiredboffin/ghidra-m32r) - the most
    recently updated, with Ghidra 11.x support and fixes to `LDH`, `SUBX` and `ADDX`.
    It is camera firmware work, not automotive, so its ABI assumptions do not carry
    over even though the instruction fixes do.

The frame-pointer question is now decidable from the manual rather than by taste.
ripnet's module assumes `0x80C000`; rimwall changed it to `0x808000`. RAM ends at
`0x809FFF`, so **`0x80C000` is not in RAM at all** and cannot be a frame pointer.
rimwall's value is inside RAM and is the plausible one.

What that means for the findings here: results resting on absolute addresses - the
tables, the checksums, the parameter maps, everything in sections 1 to 43 - are
unaffected, because those come from data references rather than from frame
resolution. Stack-local variables in the decompiled output may be mislabelled.
Re-running the disassembly against StackwalkerInc's module is worth doing before
the next round of function-level analysis, and is a prerequisite for making good
use of rimwall's annotated listings if he shares them.

### 44d. Also established

`m32r-elf-objdump` and the GDB simulator at `sim/m32r` both still exist in binutils
and GDB. Neither is used here yet, and both are worth keeping in reach as an
independent check: every M32R Ghidra fork has been chasing the same handful of
instruction bugs (`ADDX`, `SUBX`, `LDH`), and a second disassembler settles that
class of question immediately.

`jimihimi/TCURoms` on GitHub holds further stock TCU images across EDM, JDM and USDM
markets. Worth checking against the 25 already here for variants this project does
not have - particularly the early Tribeca calibration section 39 is missing.

---

## 45. HOW THE DENSO CODE ACTUALLY REACHES RAM, AND WHY 42e WAS WRONG

Section 42e said Denso working variables could not be traced without resolving GBR
at every access site. That is wrong. GBR is not involved at all, and the mistake
was assuming a mechanism instead of reading one function.

### 45a. Sign-extended 16-bit literals, not GBR

SH-2 has no instruction that loads a 32-bit constant. The compiler puts constants
in a literal pool beside the code and loads them PC-relative, and for RAM addresses
it uses the 16-bit form, which **sign-extends**:

    mov.w  @(disp,pc), Rn

On-chip RAM starts at `0xFFFF0000`, so an address like `0xFFFF81C0` is stored as
the two bytes `81 C0` and sign extension supplies the rest. Nothing anywhere in the
image holds the full 32-bit address, which is exactly why scanning for `0xFFFFxxxx`
found almost nothing and why section 40d concluded, wrongly, that there was no
table.

Ghidra labels the *literal*, not the address it denotes, so the decompiled body
reads

    pbVar4 = (byte *)(int)DAT_000099e0;

where `DAT_000099e0` is the ROM address of the literal. Reading two bytes there
gives `0x81C0`; sign-extended, `0xFFFF81C0`. Every one of the six literals in the
Select Monitor handler resolves to a valid RAM address this way.

### 45b. What that recovers

`tools/resolve_denso_ram.py` does the resolution: for every `DAT_` symbol in a
listing, read two bytes at that ROM address, sign-extend, and keep the result if it
lands in RAM. On `Impreza_STI_3.583_JDM2011` that turns **401 of 12,397 symbols
into concrete RAM addresses**, mechanically, with no judgement involved.

### 45c. Why the names still do not attach, and it is not the same problem

Joining those 401 against the 93 addresses the Select Monitor table names produces
**zero matches**, and the reason is structural rather than a failure of the method.
The two sets occupy different parts of RAM:

    code touches          0xFFFF8100, 0xFFFFF700, 0xFFFF8000, 0xFFFFFF00 ...
    SSM table points at   0xFFFFAA00, 0xFFFFA900 ...

This is the same shape as the M32R: the Select Monitor names a **staging buffer**,
and the control logic works on variables elsewhere. On the M32R the bridge is the
routine that fills the buffer, which names its sources as absolute symbols, so one
hop back gets the working variable.

The Denso bridge exists too. The buffer addresses appear as 16-bit literals at
`0x7FCAE`, `0x7FCC2`, `0x80032` and `0x80742`, in a region that is decompiled and
carries 274 nearby symbols. But Ghidra did not create symbols at those four
locations, so they are invisible to a listing-based tracer. Recovering them means
working from the disassembly rather than the decompiled C, or forcing literal-pool
symbols in that range.

That is a bounded, identified piece of work with known coordinates - not the
open-ended GBR problem 42e described.

### 45d. And how rimwall named 2,800 functions

Worth stating plainly, because it is the honest answer to why his listings are
worth more than any tool here.

He did not run a script. The method he described in post 391 - map Select Monitor
parameters to RAM addresses, then trace those back through the logic - is a
*bootstrapping* process. Naming one function makes its callers partly readable;
naming those makes their callers readable; a value identified in one place
constrains everything that touches it. It compounds, and it is human judgement at
every step.

Roughly 2,800 of 4,200 Denso functions and 1,000 of 1,300 M32R functions is years
of that. No amount of tooling substitutes for it, which is why the offer in post
391 is worth more to this project than anything else currently on the table. What
tooling can do is exactly what section 45b does: hand the human the mechanical
part, resolved and correct, so the judgement goes further.

---

## 46. THIS PROJECT HAD NO DISASSEMBLY

Everything in sections 26 to 45 that describes Denso *code* was read out of Ghidra's
decompiler output. There was never a disassembly listing in this repository -
`decompiled-denso/` holds pseudocode C and nothing else - and several conclusions
were drawn about the instruction stream from an artifact that does not contain one.

That is the root cause of the GBR error in section 42e, and of section 40d's
conclusion that the Denso images had no parameter table.

### 46a. What the decompiler removes

By design, and correctly for its purpose:

  * **Literal pools disappear.** The constants a PC-relative load reads are folded
    into expressions or dropped.
  * **Unreferenced constants get no symbol**, so they cannot be found by searching
    the C at all.
  * **PC-relative loads become bare symbol names.** `DAT_000099e0` gives no hint
    that the interesting value is the *contents* of ROM 0x99E0 rather than the
    address itself.

Concretely: the Select Monitor staging buffer addresses sit in literal pools at
`0x7FCAE`, `0x7FCC2`, `0x80032` and `0x80742`. Ghidra created no symbols there, so
nothing in the decompiled C mentions them, and searching that C concluded they were
unreachable. They are perfectly visible in a disassembly listing.

### 46b. The listing

`tools/ghidra/DensoDisasmAll.java` exports every code unit in address order with
raw bytes, mnemonic, and - the part that matters - the **resolved target of every
PC-relative load**:

    00000200  93 80    mov.w @(0x304,pc),r3   ; [00000304] = 0xD052 -> RAM 0xFFFFD052

On one image that is **228,509 instructions, 523,444 data items, and 28,182
resolved RAM literals**, covering **2,848 distinct RAM addresses**.

For comparison, the same question asked of the decompiled C recovered 401 addresses
(section 45b). Not because that method was wrong, but because it was asking an
artifact that had already discarded the answer.

### 46c. What this makes possible

A RAM cross-reference for the Denso family: for any address, every instruction that
touches it. That is the thing section 45c said was needed to bridge the staging
buffer to the working variables, and it is the foundation naming has to be built
on. It does not by itself name anything.

Also worth noting from the listing: there are **no 4-byte RAM literals anywhere**.
All on-chip RAM sits in `0xFFFFxxxx`, so the compiler always uses the 16-bit form
and lets `mov.w` sign-extend. That is a property of the family, and it is why a
scan for full 32-bit RAM addresses finds nothing.

Listings run about 38 MB per image, so `disasm-denso/` is regenerated rather than
committed. The exporter is what is worth keeping.

### 46d. The lesson, which is not a new one here

Section 15 of this file already records that reading the source beats guessing at
structure, and the memory of the checksum episode says the same thing: two
confidently wrong answers came from statistical scanning, and the firmware settled
both in minutes.

The same mistake recurred in a different costume. Decompiler output *is* source of
a kind, so it felt like reading the code. It is not the code, and for questions
about addressing modes, literal pools and how a constant reaches a register, it is
the wrong document. Ask the disassembly.

---

## 47. DENSO WORKING VARIABLES, NAMED

Section 42 named Select Monitor buffer slots on the Denso family. Section 46 got a
real disassembly. Together those are enough to do for Denso what section 40 did for
the M32R: put real-world meaning on the variables the transmission logic uses.

The Select Monitor does not read control variables directly. A routine copies each
into a contiguous staging buffer before the reply goes out, and on this family that
copy is a run of very small functions, all the same shape:

    mov.l  @(0x7fcf0,pc),r6    ; = 0xFFFF3B17     the working variable
    mov.b  @r6,r2                                 read it
    mov.l  @(0x7fcf4,pc),r6    ; = 0xFFFFA9F7     the buffer slot
    rts
    mov.b  r2,@r6                                 write it

`tools/denso_trace_ssm.py` walks back from each buffer write to the nearest RAM
literal that is not itself a buffer address. On `Impreza_STI_3.583_JDM2011` - the
image the vehicle logs in `logs/` came from, unit `A3DE207100` - that names
**13 working variables**:

| parameter | working variable | scaling in the copy |
|---|---|---|
| Accelerator Pedal Travel | `0xFFFF301C` | none |
| Gear Position | `0xFFFFA015` | none |
| Front Wheel Speed | `0xFFFF3B16` | none |
| Rear Wheel Speed | `0xFFFF3B17` | none |
| ATF Temperature | `0xFFFF3B6C` | range-checked |
| Battery Voltage | `0xFFFF8A38` | `shar` twice, so a division by 4 |
| Lateral G Sensor Voltage | `0xFFFF8A3C` | `shar` twice, so a division by 4 |
| six switch bytes | `0xFFFF3AA4`-`0xFFFF3AAC`, `0xFFFF91F5`-`0xFFFF91F6` | bit tests |

Front and rear wheel speed landing on adjacent bytes is a good sign, and
`0xFFFF3B17` was read out of the listing by hand before the tool existed - that is
what the tool was checked against.

### 47a. What is not traced, and why

Twenty-seven slots resist it: the seven solenoid currents, the eight pressures, and
the rest of the bitfields. Those are not simple copies. The values are assembled
from several sources or computed in place, so walking back to "the" source finds
nothing single. They need reading rather than a heuristic, and the disassembly is
now there to read.

### 47b. Why this matters more than the count suggests

Two of these are anchors rather than curiosities.

`0xFFFF301C` is pedal position, and section 36 established from the logs that
**full-throttle shifts do not use the speed tables at all** - every curve flattens
into a tail at a speed the car never reaches, so the shift fires on engine speed
instead. Any table read by a function that also touches `0xFFFF301C` is
pedal-indexed, which is exactly the axis those unnamed tables need identifying.

`0xFFFFA6D8`, from the cross-reference rather than the trace, is **SI-Drive Mode**,
touched four times. Section 43 recorded that rimwall's drive mode enumeration does
not fit the M32R schedule selector; this is the Denso side of that question and a
place to start looking.

This is the first real-world meaning attached to any Denso RAM address in this
project, and it is the anchor set the 950 unnamed tables in the Denso definition
have to be named from.

---

## 48. WHAT THE FIRMWARE ACTUALLY READS, AND A PROBLEM WITH THE DENSO DEFINITION

With a real disassembly, every address the code uses can be recovered rather than
inferred. SH-2 cannot build a 32-bit constant in an instruction, so every RAM
variable, table base and jump target is fetched from a literal pool. Reading those
pools is a complete account of what the firmware touches.

`tools/denso_literals.py` resolves them from the ROM image rather than relying on
Ghidra having typed the pool entry - the listing already carries the absolute pool
address in the operand, so all of them resolve, not the 63% Ghidra annotates.

On `Impreza_STI_3.583_JDM2011`, **37,106 literal loads**:

    ram    21,895     table   7,711     code   6,308     const  1,192

The 7,711 table loads reach **5,156 distinct calibration addresses**. That set is
ground truth for what this firmware reads.

### 48a. A false alarm, and how it happened

The first version of this section claimed the definition did not match: 11 of 985
tables referenced by code, nine in ten with nothing pointing at them, and a
conclusion that the definition was mostly artefacts. **That was wrong**, and it is
worth recording how, because the mistake was in the measurement rather than the
firmware.

Two errors compounded. The definition was sliced out of the XML by character
offset, which spanned several ROM sections at once and mixed tables belonging to
different images. And the comparison was made against the definition's
`storageaddress`, which is where the *data* lives - but the code references the
**header**, not the data.

Parsing the XML properly and comparing against headers:

    tables in the WQDE2WB1 section                    591
    matching an indexed header, or its axes or data   588   (99%)
    indexed headers referenced by a literal load      196 of 196   (100%)

196 headers, each contributing a data block and two axes, is 588 entries exactly.
The definition for this image is sound, every table in it is reachable, and the
pointer index the generator filters on is doing its job.

The pointer arrays themselves are *not* referenced by literal loads - 0 of 32 -
which is the opposite of what was assumed. The code holds header addresses
directly; the arrays are how this project found them, not how the firmware reaches
them.

### 48b. The real state of the Denso definition

The problem is naming, not validity. Of the tables across the Denso definition,
almost all carry shape-derived placeholders like `Table 0C4FE0 (10x11)`. They are
real tables at correct addresses with correct dimensions and scaling. Nobody knows
what they do.

That is a different problem from the one 48a first reported, and a much better one
to have.

### 48c. The useful inversion

The map runs both ways. For any calibration address, every site that reads it; for
any code site, every table it touches. Combined with the working variables of
section 47 - pedal at `0xFFFF30FB`, gear at `0xFFFFA015` - a table read by a
function that also reads pedal is pedal-indexed, and that is how a real table gets
a name rather than a shape.

That is the path to naming the Denso family, and it now has the data under it.

---

## 49. RUNNING THE CODE

Every technique in this file up to here reads the firmware. This one executes it.

Ghidra ships a p-code emulator that works against whatever language a program was
loaded with, which means it runs on the SH-2E definition of section 46 rather than
on an approximation of the core. There is no need for external tooling: it was
already installed.

### 49a. It works

`tools/ghidra/DensoEmuTable.java` sets the argument registers, points the program
counter at a function, and single-steps until it returns. Running `0x0002C3DA`
with `r4 = 0x40` executes **155 instructions**, including a call into `0x255A` and
back, and returns cleanly.

Which tables a run touches is read off the executed path. The emulator does not
expose a memory-read hook, but on this core every calibration access goes through a
PC-relative literal (section 46), so intersecting the path with the literal map of
section 48 is equivalent and needs no instrumentation. For that run:

    155 instructions, 11 table loads, 4 distinct tables
       0x0C17BE  x4      0x0C17C2  x1
       0x0C17C6  x1      0x0C17E4  x5

So `0x0002C3DA` reads a cluster of four related tables at `0x0C17BE`-`0x0C17E4`.
That is established by running the routine, not by inferring it from proximity.

### 49b. Sweeping an input

`tools/denso_emulate.py --sweep r4=0,192,64` runs the function once per value and
reports which tables each run reaches. If an input selects between tables, or moves
which rows are read, that is what an axis looks like from the outside.

On this function the answer was negative and worth recording: all four tables are
reached on every value of `r4`, so `r4` is not what selects between them. A negative
result from an experiment is worth more than a plausible guess, and this is the
first experiment this project has been able to run at all.

### 49c. Why this matters more than the tooling before it

Naming a table by static analysis means arguing from shape, from what it sits next
to, and from what a nearby function seems to do. Every one of those arguments has
been wrong at least once in this file - sections 42e, 45, 48a.

Emulation replaces the argument with an observation. Set pedal to 40%, run the
shift decision, see which table is read and what comes out; set it to 80% and do it
again. That is the same method the vehicle logs provide, except it costs seconds
instead of a drive, and it works on all nine Denso images rather than the one car
that was available.

It does not name anything by itself. What it does is make a claim testable, which
is what this project has been short of.

### 49d. Also available, not used

GDB carries CGEN instruction-set simulators for both families - `sim/m32r` and
`sim/sh` - which would run the code outside Ghidra entirely. They need GDB built
from source, and the Ghidra emulator is already here and already speaks SH-2E, so
they are noted rather than pursued. QEMU has no SH-2 target; its SuperH support is
SH-4 only and is not applicable.

---

## 50. THE SELECT MONITOR ADDRESSES ARE OUTPUTS, NOT INPUTS

Section 47 called the addresses behind the Select Monitor "working variables". That
is the wrong word for most of them, and the emulator is what showed it.

Setting `0xFFFF30FB` - the address the table names Accelerator Pedal Travel - to
every value from 0 to 255 and running the functions that touch it produced an
identical instruction path and an identical result every time. The write was
verified as landing before that was believed: the emulator reads back `AA` after
being told to write `AA`.

The reason is visible once reads and writes are separated:

    written at   0x12CC2, 0x131BC, 0x13E82, 0x13F30, 0x14724, 0x14BE8
    read at      0x79F3A, 0x7A1E4, 0x7A254, 0x7A316, 0x2CF9E, 0x2D32E

Everything in the first group is control code. Everything in the second is the
Select Monitor reporting region identified in section 47. So `0xFFFF30FB` is
**computed by the transmission logic and consumed by the diagnostic reply** - a
published output. Writing to it changes nothing because nothing upstream reads it.

That is why the sweeps in section 49 were flat. Not a broken harness: the wrong end
of the pipe.

### 50a. The first Denso table identified by reading the code

Following one of the writers, at `0x14724`:

    00014716  cmp/hi r5,r2                          compare against a limit
    00014718  bf 0x0001471e
    0001471A  bra 0x00014720
    0001471C  _mov #-0x1,r2                         saturate to 0xFF
    0001471E  mov.w @r7,r2   ; [000CE312] = 0x1C    otherwise take this
    00014720  mov r2,r5
    00014722  mov.l @(0x1493c,pc),r2   ; = 0xFFFF30FB
    00014724  mov.b r5,@r2                          store the pedal byte

So **`0x0CE312` is a constant in the accelerator pedal path** - a limit or default,
holding `0x1C`, applied where the computed value is not saturated. It is the same
table that `tools/denso_find_users.py` found being read alongside pedal in two
independent functions, `0x143A2` and `0x7A214`, which is corroboration from a
different direction.

This is the first Denso calibration address in this project given a purpose by
reading what the code does with it, rather than by its shape or its neighbours.

### 50b. What actually finds the control inputs

The method that works is the inverse of what was tried first:

1. Take an address the Select Monitor names. It is probably an output.
2. Split its sites into reads and writes. Writers are the control logic.
3. Follow a writer back. What feeds it is the real variable, and the constants and
   tables consumed on the way are calibration.

`tools/denso_find_users.py` does step 2 and reports, per function, whether an
address is loaded, compared, and branched on. For `0xFFFF30FB`: twelve functions
load it, none compares or branches on it - which is exactly the signature of a value
being produced rather than consumed, and would have saved the sweeps had it been run
first.

---

## 51. THE COMPLETE SHIFT TABLE INDEX, AND 194 TABLES THIS PROJECT WAS MISSING

rimwall gave the whole of it in forum topic 13725 post 393, and every part of it
checks out against `ACD1A06000`. Section 43 is withdrawn.

### 51a. Section 43 was wrong

Section 43 recorded that his drive mode enumeration did not fit the schedule
selector, because the selector's variables hold 0 to 4 and seven high-bit codes,
and his list runs 0 to 13. That was comparing his drive modes against the wrong two
variables. There are **three** inputs, not two, and the drive mode is a third
variable this project had never found.

### 51b. The function, verified

`FUN_0004bcd8` at `0x4bcd8` maps all three and computes the index:

    DAT_00804b10 = sVar1 * 0x32 + sVar2 * 10 + (ushort)DAT_00804832 * 2;
    DAT_0080498c = (&PTR_DAT_000180e8)[DAT_00804b10];
    DAT_00804990 = (&PTR_DAT_000180ec)[DAT_00804b10];

`0x32` is 50, so the index is

    drive mode offset x 50  +  shift lever offset x 10  +  gear x 2

which is rimwall's formula exactly. Section 33 had found the second and third terms
and missed the first, which is why it could describe the selection without ever
identifying what selected between schedules.

The three variables:

    DAT_00804814   drive mode        internal value, mapped below
    DAT_00804817   shift lever mode  0x80-0x85 and 0x8C, mapped below
    DAT_00804832   gear              0 to 4

Drive mode mapping, read out of the function and matching his post value for value:

    0x0 -> 0  Normal (Sport)      0x6 -> 5  unknown
    0x1 -> 1  Sport#              0x8 -> 7  ATF Temp Low
    0x3 -> 3  unknown             0x9 -> 8  unknown
    0x4 -> 4 or 8  Manual Mode    0xB -> 9  I Mode
    0x5 -> 1  unknown             0xC -> 2  Slope
                                  0xD -> 6  Kickdown / hard acceleration

`0x2`, `0x7` and `0xA` are unused. Manual Mode picks 4 or 8 depending on bit 7 of
`0x8055FC`, which is the only conditional in the whole mapping.

Shift lever mapping:

    0x84, 0x80, 0x8C -> 0   P, N, D, or Manual 5
    0x85 -> 1   Manual 4        0x82 -> 3   Manual 2
    0x81 -> 2   Manual 3        0x83 -> 4   Manual 1

### 51c. 194 tables are missing from the definition

Walking the two pointer arrays over the full index range gives **202 distinct shift
table addresses**. The definition for this image contains **eight**, named
`Shift Map 1 of 8` through `8 of 8`.

    pointer slots            1000
    distinct table addresses  202
    already in the definition   8
    missing                   194

The eight are not wrong - `0x01683C` is the first entry of the array and is
correctly `Shift Map 1 of 8` - they are simply the small fraction that earlier
pattern scanning happened to find. Everything reached through a drive mode other
than the default was invisible.

Many index slots share data, which is why 1,000 slots resolve to 202 tables. That
sharing is what rimwall's naming convention captures: a table used for D and for
Manual 5 through 2 is named once with all of them.

### 51d. Naming

His convention:

    Table_[Drive Mode]_[Shift Lever Modes]_[Gear]_[Up or Down]

so the first, for Normal drive mode with the lever in D, first gear, upshift, is
`Table_Normal_D5432_1st_Up` - the `D5432` recording that the same data serves D and
Manual 5, 4, 3 and 2.

This is the single largest addition available to the M32R definition, and it comes
from someone else's work. It is his mapping, his formula and his naming; what is
verified here is that all three are correct against this image.

---

## 52. THE PUBLISHED METHOD FOR DEFINING A SUBARU 32-BIT ROM

rimwall pointed at forum topic 8449 in post 394. It is dschultz's step-by-step
process for defining a new 32-bit Subaru ROM from a known one, written in 2012 and
still the reference. It is archived as `docs/forum_thread_8449.txt`.

Most of it is about engine ECUs, but three claims are testable against the TCU
images here and all three hold.

### 52a. What it confirms

**The RAM segment.** Step 1 says to create one "starting at 0xFFFF0000 length
0x0000C000". That is what `DensoAddRam.java` does, added a day earlier here after
the emulator showed there was no RAM in the program at all (section 49). Arrived at
from opposite directions.

**Where the table structures live.** Step 4 says "the map data is stored in the ROM
above the 0xC0000 area" and that the structures carry the data type, a multiplier
and an additive. For `Impreza_STI_3.583_JDM2011`:

    table headers   0xE5208 to 0xEC868      196 of 196 above 0xC0000
    map data        0xA16A8 to 0xD2358

Every header is above the line. The 28-byte structure of section 30 - rows, columns,
axis pointers, data pointer, flags, float scale and offset - is the same object
step 4 describes.

**The unsupported-parameter convention.** Step 2 notes that the Select Monitor
table names every parameter whether or not the unit supports it, and that
unsupported ones reach "a subroutine that returns 0xFF". This project found the
same structure with a different implementation: the Denso TCU points unsupported
slots at a fixed data byte rather than at a routine, which is why the filler in
section 42 is an address in ROM.

### 52b. What it does not solve, and that is the interesting part

Post 16, from dschultz himself: *"Unfortunately, this process does not work well on
Hitachi ROMs."* Post 17, SergArb, having tried: *"Only 'Statistical' maps and no X&Y
axis."*

That is the whole method failing on the M32R, and it fails for a reason already
recorded here: Hitachi tables carry **no header**. There is no structure holding a
type, a multiplier or axis pointers, only a pointer to data. Everything step 4
depends on is absent.

So the community position, unchanged since 2019, is that Denso and Hitachi ECUs are
definable by this process and Hitachi ones are not. The thread ends with people
being told the work takes months and that the only people who can do it charge for
it.

That is worth stating plainly because it sets what this project's M32R side is
against: 296 named tables in the Hitachi definition, arrived at without headers,
plus the shift table index of section 51. The Denso side is the easier half by the
community's own account, and it is the half still mostly unnamed here.

### 52c. Not adopted

The process depends on IDA Pro and a set of tools distributed as forum attachments -
`XmlToIdc`, `MakeCELPointers.idc`, `MakeTablePointers.idc`, `WalkTheRom.idc`,
`MakeXmlDef.exe`, `RR2EcuFlash.exe`. This project uses Ghidra and its own
generators, which reach the same objects by different means: `generate_denso_def.py`
already walks the table structures step 4 describes, and the pointer index it
filters on is a stronger test than the structural match that step relies on.

The DTC location trick in step 3 - search for the byte sequence `03 35 01` and read
the switch table above it - **does not transfer**. Tried on both families: the
sequence appears nowhere in `Impreza_STI_3.583_JDM2011` and nowhere in
`ACD1A06000`. The reason is in the number itself. `0335` is P0335, crankshaft
position sensor, an *engine* code; a transmission controller has no reason to carry
it. The anchor is engine-ECU specific and the equivalent for a TCU would be one of
the P07xx codes, which is a different search that has not been worked out.

Section 24's disputed DTC addresses therefore remain open.

---

## 53. THE DENSO SHIFT SCHEDULE SELECTOR, FOUND BY RUNNING THE CODE

The M32R schedule selection was read out of the disassembly (section 51). The Denso
equivalent was found the other way - by emulating the function and changing things
until the answer changed.

### 53a. Why single inputs looked inert

Setting pedal, gear, or the most-read address one at a time produced an identical
8,739-instruction path every time, which section 50 read as the addresses being
outputs. That was true of pedal, but it was not the whole story.

With RAM zeroed, **every comparison takes its default branch**, so the function
walks one path regardless. Setting all eight addresses the function reads, all at
once, moved it immediately:

    all reads 0x00   8,739 steps   selects 0xB6CD4
    all reads 0x01   8,515 steps   selects 0xB6CF2
    all reads 0x40   7,820 steps   selects 0xB6D2E
    all reads 0x80   8,539 steps   selects 0xB6CB6

Bisecting one address at a time against that baseline isolated it: **`0xFFFF9F55`
alone reproduces the full effect.** The other seven change the instruction count -
they are read - but not which table is chosen.

The lesson is worth keeping. A flat sweep does not prove an input is ignored; it
can equally mean the state around it is not plausible enough for the branch to
matter. One variable at a time is the wrong experiment on a controller.

### 53b. What it selects

    0xFFFF9F55 = 0   ->  0xB6CD4
                 1   ->  0xB6CF2      +0x1E
                 2   ->  0xB6D10      +0x1E
                 3   ->  0xB6D2E      +0x1E
                 4+  ->  0xB6D2E      clamped

Four schedules, a 30-byte stride, saturating at 3. Each table is fifteen uint16
values, which is the fifteen-point pedal axis section 36 measured from the vehicle
logs.

Reading them as road speed in km/h:

    0:  25  25  25  25  29  40  92 105 ...
    1:  35  35  35  35  35  51  92 105 ...
    2:  44  47  49  52  54  64  92 105 ...
    3:  56  57  58  60  70  90 105 114 ...

**Monotonically later shift points from 0 to 3.** Schedule 0 upshifts at 25 km/h
where schedule 3 holds to 56, and the ordering is preserved across the whole curve.
That is economy through to aggressive, and it is the physical check that the
selector was correctly identified: nothing about the emulation forced the numbers
to come out ordered.

The range and the clamp match rimwall's Denso drive mode list from post 391 -
0 unused, 1 I-Mode, 2 Normal, 3 Sport# - though which internal value maps to which
name is not established here, only that there are four and they run economy to
aggressive.

### 53c. It is not the Select Monitor's SI-Drive

`0xFFFFA6D8`, which the Select Monitor table names **SI-Drive Mode**, changes
nothing: every value from 0 to 4 selects `0xB6CD4`. So it is another published
copy, exactly as section 50 describes, and `0xFFFF9F55` is the working value the
control logic acts on. Twenty code sites read `0xFFFF9F55` and it appears in no
Select Monitor table at all.

Anyone logging SI-Drive is watching what the TCU reports, not what it decides on.

### 53d. The method

This is the first result in this project established by experiment rather than by
reading. The procedure generalises:

1. `denso_inputs.py` - emulate the function and record which RAM it reads on the
   path actually taken.
2. Set all of those at once. If nothing moves, the function is genuinely
   input-independent; if something moves, there is leverage.
3. Bisect one address at a time against that baseline to find which one carries it.
4. Sweep the winner and read the mapping off the output.

Four steps, minutes of machine time, and no argument about what a table's shape
might mean.

---

## 54. PROBING TWELVE FUNCTIONS BY EXPERIMENT

`tools/denso_probe.py` automates the procedure of section 53: emulate, record what
the taken path reads, set all of it at once, and if the answer moves, bisect to the
address that carries it and sweep that. Run against the twelve functions that
consume the most calibration tables.

**All twelve respond to their inputs.** None is the inert kind that flat single-
variable sweeps made several functions look like earlier.

### 54a. Control inputs found

Five addresses that decide something, none of which appears in any Select Monitor
table:

    0xFFFF357C, 0xFFFF357A    0x00058B24    nine distinct results
    0xFFFF33AC, 0xFFFF32D0    0x00036E8E    nine distinct results
    0xFFFF35E1                0x00057EC8    three
    0xFFFF8E62, 0xFFFF8E64    0x00035D14    two
    0xFFFF9152                0x000526C6    two

`0xFFFF8E60`, `0xFFFF8E62` and `0xFFFF8E64` are the three busiest addresses in the
whole cross-reference - 452, 342 and 418 code sites - and they now have a role
rather than just a reference count.

### 54b. Two of them are arithmetic, with exact constants

`0x00058B24` returns `input x 0x4C000`, exactly linear across the sweep. Read as
16.16 fixed point that is **a multiply by 4.75**.

`0x00036E8E` steps by `0x32E60000` per unit of input, which as a fraction of 2^32
is **0.198822**. The low half advances separately, so this is a wider-than-32-bit
accumulation rather than a single product.

Neither is a table lookup. They are scaling routines, and knowing that is worth as
much as finding a table: it says the constants they carry are conversion factors,
not calibration to be tuned.

### 54c. One is a selector, and one number in it is not what it looks like

`0x00057EC8` returns different things by input:

    0, 2, 3, 8  ->  0xFFFF3618      a RAM address
    1           ->  0xFFFFDB00      a RAM address
    4, 5, 6, 7  ->  0x00B20000      not an address

`0x00B20000` is past the end of a 1 MB image, so it is a computed value rather than
a pointer, and this was nearly written up as a calibration table selector on the
strength of the number looking plausible. Checking whether the address exists is
the whole of the difference. What the function does for inputs 4 to 7 is not
established.

### 54d. What the method is and is not good for

It finds inputs and shows what they select, quickly and without argument. It does
not name anything: knowing that `0xFFFF357C` scales a value by 4.75 does not say
what the value is.

Naming still needs either the Select Monitor mapping, which covers the published
copies rather than these, or somebody who has read the code. That remains rimwall's
listings, and nothing here changes that.

---

## 55. A SIMULATED DRIVE, LOGGED IN FULL

Probing one function at a time with a fresh emulator costs about twenty seconds of
JVM and project load per data point, so any real drive was impossible that way. It
also discarded the state between runs, which is the wrong shape for the problem: a
transmission controller is a state machine and what it does now depends on where it
has been.

`DensoDriveLog.java` keeps one emulator alive for a whole drive. Each tick writes
that instant's inputs, runs the control function, and records every RAM byte that
changed. **Memory carries forward between ticks** - integrators wind up, timers
advance, and a shift decision sees the gear the previous tick left behind.

### 55a. It runs, and it is fast

568 ticks, **4,855,577 instructions, under a minute**. The whole 64 KB of RAM is
compared each tick and 64 addresses moved across the drive.

The profile is not invented. `denso_make_profile.py` builds it from the vehicle
logs in `logs/` - 568 rows from a car running this exact firmware, unit
`A3DE207100`, idle to 173 km/h through all five gears - so the simulated drive
follows something that actually happened. Tick 0 comes out as idle: engine 736 rpm,
first gear, ATF 88 °C, which is what the log says.

At this rate a 30-minute drive at 1 Hz is about three minutes of machine time.

### 55b. What the firmware computed

Of the 64 addresses that moved, 58 were never written by the profile - the firmware
produced them. Correlating each against the inputs that drove the drive:

    0xFFFFBE8D   r=0.878  tracks 0xFFFF32D0
    0xFFFFBE8C   r=0.815  tracks 0xFFFF8A8A
    0xFFFF8A70   r=0.883  tracks 0xFFFF33AC
    0xFFFF8A85   r=0.883  tracks 0xFFFF33AC
    0xFFFF8A81   r=0.883  tracks 0xFFFF33AC
    0xFFFF8A75   r=0.883  tracks 0xFFFF33AC
    0xFFFF8A71   r=0.855  tracks 0xFFFF33AC
    0xFFFFBEC3   r=0.645  tracks 0xFFFF33AC

So `0xFFFFBE8C` and `0xFFFFBE8D` are each derived from a different one of the two
wheel-speed inputs, and a block at `0xFFFF8A70`-`0xFFFF8A85` is derived from a
single input together.

**That dependency structure is established.** It comes from watching the firmware
run, not from reading anything.

### 55c. What is not established, and the difference matters

The *names* are not. `denso_make_profile.py` maps log columns onto input addresses,
and that mapping is an assumption - it was chosen because those addresses are the
ones probing showed the control code reads, not because anything proved
`0xFFFF33AC` holds ATF temperature.

So the honest statement is "`0xFFFFBEC3` tracks whatever `0xFFFF33AC` is", not
"`0xFFFFBEC3` is temperature-derived". If the input mapping is wrong every name
inherited from it is wrong, while the dependency graph stays correct either way.

Two things would fix that. Feeding one input at a time through its full range and
watching which computed address responds gives the graph without needing names at
all. And the Select Monitor copies, which *are* named, can be compared against
these computed values tick by tick - if a computed address matches a published
parameter across a whole drive, that is the name, established rather than assumed.

### 55d. Why this is the right instrument

Every naming argument in this file that rested on a table's shape or its neighbours
has been wrong at least once - sections 42e, 45, 48a, 50, and the `0xB20000` that
was nearly written up as a table pointer in 54c. A drive log is a different kind of
evidence: it says what the firmware did, over time, from a starting state that
actually occurred.

---

## 56. THE CAN INPUT PATH, AND WHY THE SIMULATED DRIVE WAS INCOMPLETE

Section 55 fed the firmware sensor-like values and logged what moved. The results
were real but the drive was not: **a 5EAT TCU gets most of what it needs over CAN,
not from its own sensors**, and every CAN input was being fed as zero.

That is why the working buffer in section 55 held values matching no table in the
ROM. The firmware was computing from an engine that, as far as it could tell, was
reporting nothing.

### 56a. What the TCU is told

From rimwall's decode in forum topic 20850, archived as
`docs/forum_thread_20850.txt`. CAN 0x410 from the ECU, eight bytes:

    0  x2.0     Nm    Engine torque output
    1  x1.6     Nm    Max engine torque
    2  x1.6     Nm    Max torque allowed by ABS/VDC
    3  x1.6     Nm    Torque loss
    4  x100/255  %    Accelerator pedal angle
    5,6           rpm Engine speed, low then high byte
    7  bits          torque permission, AC, power steering, ECT low, idle switch

and 0x411 carries throttle position, the gear the ECU infers from its own speed
ratio, and cruise speed.

Torque is the important one. Section 19 traced line pressure from CAN 0x412 through
a slip factor and an ATF temperature factor to the pressure target, so with torque
at zero the whole pressure chain is running against an idling engine no matter what
road speed is fed in.

### 56b. Where it lands

The SH7058 has two HCAN channels and the TCU uses both. From the hardware manual,
table 16.6, the mailbox registers begin at `H'D020`, and the firmware's own literal
pool confirms the layout - 60 distinct addresses in that range:

    0xFFFFD000 - 0xFFFFD05A    HCAN0 control
    0xFFFFD100 - 0xFFFFD128    HCAN0 mailbox data
    0xFFFFD800 - 0xFFFFD928    HCAN1, the second channel

So the frames are memory mapped, and an emulated drive can deliver them by writing
those addresses - the same mechanism the hardware uses.

### 56c. A setup error this exposed

`DensoAddRam.java` created RAM over `0xFFFF0000`-`0xFFFFFFFF`, the whole 64 KB.
Thread 8449 specifies `0xFFFF0000` length `0xC000`, which ends at `0xFFFFBFFF`;
everything above that is peripheral registers, not RAM.

The oversized block is harmless for reading - unmapped peripheral reads return zero
either way - and it is what makes writing the mailboxes possible at all. But it
means the region is being treated as plain memory when parts of it are registers
with side effects on read, and nothing in the emulation models that. Worth knowing
before trusting a result that depends on peripheral behaviour rather than on
values.

### 56d. What this changes about section 55

The dependency graph stands: those addresses really do respond to those inputs.
What it cannot claim is that the drive was representative. A run with torque,
engine speed and pedal arriving over CAN is a different experiment, and the values
the firmware computes in it should be expected to differ.

The profile builder has been extended and the harness now runs a task list;
56e records what that did and did not achieve.

### 56e. Injecting the frames, and what it did not do

`denso_make_profile.py` now writes both frames every tick, built from the log:
0x410 into mailbox 0 at `0xFFFFD100` and 0x411 into mailbox 1 at `0xFFFFD108`, with
engine speed packed low byte then high as the ECU sends it. At tick 200 the frame
carries `0x04F9`, 1273 rpm, which is what the log says.

`DensoDriveLog.java` now takes a task list rather than one function - entries
separated by `+` are run in order every tick, sharing memory - because a controller
services CAN, decodes it, and only then decides, and no single function does all
three.

Both are in place and neither changed the outcome. The drive with frames moved 68
addresses against 64 without, and adding the CAN accessor at `0x19D2` to the
sequence added 7,951 instructions and moved the same 68.

The reason is that `0x19D2` is a **mailbox accessor**, not a periodic task: it takes
a mailbox number in a register, bounds-checks it against 32, and computes an
address. Called with the registers zeroed it fetches mailbox 0 and does nothing with
it. The function that decodes 0x410 into working variables - the one that would turn
byte 5 and 6 into an engine speed the shift logic reads - has not been identified.

So the CAN path is located and the machinery to feed it exists, but the link from
mailbox to working variable is still missing. Finding it means looking for a routine
that calls an accessor like `0x19D2` and then stores below `0xFFFFC000`, which the
literal map and the disassembly now make searchable.

One limit worth stating: the logs are TCU-side. They carry engine speed and pedal
but **no ECU torque column**, so byte 0 of 0x410 is fed as zero even now. Since
section 19 puts torque at the head of the line pressure chain, a drive built from
these logs cannot exercise that path however well the frames are delivered. That
needs an ECU-side log from the same car, or a torque estimate derived from the
engine speed and pedal that are present.

## 57. THE ECU ON THE OTHER END

Section 56 ended on a missing input: the logs are TCU-side and carry no torque
column, so CAN 0x410 byte 0 was fed as zero, and section 19 puts torque at the head
of the line pressure chain. The suggested remedies were an ECU-side log from the
same car or an estimate derived from pedal and engine speed.

Neither was necessary. The ECU does not measure torque either - it **looks it up**,
from accelerator pedal angle and engine speed, in a calibration table. The logs
carry both of those columns. So the torque figure was never missing; it was one
table lookup away, and the table is in a ROM that can be read.

### 57a. Which ECU

The TCU image this project works against is `Impreza_STI_3.583_JDM2011`, unit
A3DE207100, calibration WQDE2WB1 - a JDM STI A-Line, which is the 5EAT car. The
ECU on the other end of its CAN bus is **AZ1G502L**: 2009 JDM Impreza STI,
automatic, SH7058, 1 MB. The same processor as the Denso TCU, so the SH-2E
language of section 44, the disassembly scripts and the emulation harness all
apply unchanged.

Verified on load rather than assumed: the string `AZ1G502L` sits at 0x2004 exactly
where the RomRaider definition says its internal identifier lives, the reset vector
is 0x00000C0C and the initial stack pointer 0xFFFFBFA0 - the same RAM ceiling as
the TCU.

Neither the ROM nor the RomRaider definition file is ours, so neither is committed.
`tools/ecu/README.md` records where both come from and how to fetch them.

### 57b. Reading the calibration

Two things about these definitions have to be read rather than assumed, and both
cost time before they were noticed.

**The definition is split in half.** A base entry carries every table's shape -
type, axes, scaling, units - and each calibration overrides only the addresses,
because the same table lives somewhere different in every ROM. Read one half alone
and you get either what a table means or where it is, never both. This is what made
`AZ1G502L` look at first as though it defined no torque table at all: the search
was for the plain name while this calibration uses the A/B naming. It overrides 297
tables, six of them requested-torque maps.

**The axis endianness in the definitions is wrong for these ROMs.** They tag the
float axes little-endian while the ROM stores them big-endian like everything else
on an SH7058. This is the dangerous kind of wrong: the table data comes out
perfect and only the axes turn to denormals around 1e-41, so the result still
prints and still looks like a table. Settled by reading the bytes - `44 48 00 00`
is 800.0 big-endian, and read the other way round it is 0x00004844. The reader
checks whether the values are ones a real axis could hold and flips if not.

### 57c. What the map says

`Requested Torque A (Accelerator Pedal) SI-DRIVE Intelligent` at 0xDDD54: a 15x16
grid of big-endian uint16 scaled by 0.0078125, on axes of pedal angle 0-100 % and
engine speed 800-6800 rpm in 400 rpm steps. The X axis, Y axis and data are
contiguous - 0xDDCD8 + 60 = 0xDDD14 + 64 = 0xDDD54 - which is an independent check
that the addresses are right.

The three SI-DRIVE modes behave as the marketing says, which is the strongest
evidence the reading is correct:

    rpm      Intelligent    Sport    Sport Sharp     at full pedal, Nm
    800            261.2    261.2          261.2
    2000           350.0    350.0          350.0
    3200           344.0    350.0          350.0
    4800           280.0    350.0          350.0
    6000           240.0    350.0          350.0
    6800           212.0    330.0          330.0

Intelligent tapers away above 2800 rpm; Sport and Sport Sharp hold a flat 350 Nm
from 2000 to 6000. At part throttle the three separate as well - 30 % pedal and
3000 rpm gives 155.0, 190.0 and 222.5 Nm.

350 Nm divided by rimwall's 2.0 Nm per count for CAN 0x410 byte 0 is 175, inside a
byte with room to spare. The calibration and the frame decode agree.

### 57d. Applied to the drive

Across the 568-row log, torque peaks at 350 Nm with 184 rows under load. At the
wide-open-throttle row - 100 % pedal, 5598 rpm - the frame reads

    byte 0  0x7E  126  x2.0  =  252 Nm      byte 4  0xFE  pedal 99.6 %
    byte 1  0x9D  157  x1.6  =  251.2 Nm    byte 5,6  0xDE 0x15  =  5598 rpm

Bytes 0 and 1 are the same torque on different scales, so they have to be converted
rather than copied. An earlier version of the profile builder copied one into the
other, which understates maximum torque by a fifth and does it silently.

## 58. THE CAN RECEIVE MAP

Section 56 located the HCAN mailboxes and section 56d recorded that writing them
changed nothing. Two reasons, both now settled by reading the code rather than
guessing at it.

### 58a. The mailbox layout was wrong

The generic mailbox accessor at `0x0000A8E6` lays the hardware out plainly. It takes
a mailbox number, compares it against 0x20 to choose between the two channels,
shifts left by five to get an offset of 32 bytes per mailbox, and adds it to a base:

    0000A90C  shll2 r6        \
    0000A90E  shll2 r6         >  offset = mailbox * 32
    0000A910  shll r6         /
    0000A912  mov.w ...,r2    ;  0xD108 -> RAM 0xFFFFD108
    0000A916  add r6,r5       ;  data   = 0xFFFFD108 + N*32
    0000A918  add -0x8,r2     ;  header = 0xFFFFD100 + N*32

So `0xFFFFD100` is mailbox 0's **header**, not its data, and mailbox 1's data is at
`0xFFFFD128` rather than `0xFFFFD108`. The profile builder had been writing frame
0x410 into mailbox 0's header and frame 0x411 into mailbox 0's data.

### 58b. Nothing reads a mailbox anyway

The more important reason is that no consumer reads a mailbox at all. A receive task
copies each frame into a fixed RAM buffer and every consumer reads the buffer.

The configuration that drives the copy is a table of 36 sixteen-byte entries at
**0x08600E**, found by its shape rather than its address so it can be located in the
other firmwares too: a valid 11-bit identifier, the constant length word 0x0800, and
0xFFFF as the high half of a destination.

    CAN id   channel  mailbox   destination
    0x420    0        1         0xFFFF30BC
    0x421    0        2         0xFFFF30C4
    0x422    0        3         0xFFFF30CC
    0x410    1        4         0xFFFF300C
    0x411    1        5         0xFFFF3014
    0x412    1        6         0xFFFF301C
    0x511    1        7         0xFFFF3024
    ...
    0x7DF    1        13        0xFFFF4011
    0x7E1    1        14        0xFFFF4011
    0x7E9    0        15        0xFFFF4019

The destinations are eight bytes apart, one CAN payload each. The table holds two
vehicle configurations - a second set covering 0x231, 0x232, 0x235, 0x331, 0x333,
0x334, 0x351, 0x3B1, 0x451, 0x491, 0x520 and 0x521 follows the first.

Two independent checks that this is read correctly. 0x7DF, 0x7E1 and 0x7E9 are the
standard OBD-II identifiers - functional request, TCU physical request, TCU response
- and they are the only entries that land outside the powertrain buffer region and
the only ones with different flags. And the decode routine of section 59 loads
0xFFFF300C as a literal, which is where this table says frame 0x410 is put.

`tools/denso_can_map.py` recovers the table and can emit the profile writes that
deliver a decoded frame where the firmware will look for it.

## 59. THE FRAME ARRIVES, AND STILL NOTHING MOVES

With torque computed from the ECU calibration and the receive map of section 58 in
hand, the drive was run four times against a zero-torque control identical in every
other respect. The result each time: **no propagation whatsoever**.

    delivery                          instructions   moved   control   downstream
    HCAN mailbox                       4,855,577      70       68          0
    receive buffer 0xFFFF300C          4,855,577      70       68          0
    buffer + receive task              5,188,425      70       68          0
    decoded variables written direct   4,855,577      74       71          0

The instruction counts are identical to the digit between the torque run and its
control in every case, which is the strongest possible statement that no branch
anywhere depends on torque. Every address that differed was one this project had
written itself.

### 59a. The receive gate, fully traced

The receive task at `0x00012BA4` asks a gate at `0x0000A2E2` whether a frame
arrived, and skips the decode when the answer is no. The gate reads a
receive-pending register and masks the bit for the mailbox. Two helpers do the
work, and reading them settled a question that guessing had got wrong:

    0x0000AC96   base 0xFFFFD040, adjusted by mailbox number:
                   below 16   add 2        32 to 47   add 0x802
                   16 to 31   unchanged    48 and up  add 0x800
    0x0000AD00   mask = table[mailbox & 15] at 0x0000ADA4, a plain 1<<n

So **the mailbox numbering is global** - 0 to 31 is channel 0, 32 to 63 is channel
1 - and byte 4 of a receive table entry is not a channel index. Frames 0x410 and
0x411 are mailboxes 4 and 5, both below 16, so the register is `0xFFFFD042` and the
bits are `0x0030`.

This corrects a derivation made here earlier. Channel 1 registers do sit 0x800
above channel 0, and the firmware does reference `0xFFFFD840`, so `0xFFFFD040 +
0x800` looked well founded. It was still wrong, because the mailbox in question is
not on channel 1 at all. An offset that is real does not make the address it
produces right.

### 59b. Three writers, no reader

The reason nothing moves is not the delivery. It is that **`0xFFFF30F0` is written
three times in this image and read nowhere that can be found**:

    0x00012BD2   the decode - unpacks the frame into it
    0x00013E00   a failsafe - writes zero to it and its neighbours
    0x000143A2   limp-home - writes 0xAF, which at 2.0 Nm per count is 350 Nm,
                 with pedal from a ROM constant and engine speed from 0xFFFF3AFC

The last is worth noting on its own: when the ECU goes quiet the TCU does not
assume no torque, it assumes **maximum** torque. That is the conservative choice
for line pressure - hold the clutches hard rather than slip them - and it is a
useful piece of behaviour to have found.

This is the pattern of section 50 again. The decoded values are published copies,
and whatever the control path actually reads is reached another way.

### 59c. A trap in cross-referencing, and a wrong turn recorded

The obvious next step was to look for reads of the structure by displacement off a
base, since `0xFFFF30EC` carries 57 references against six for `0xFFFF30F0`. A
script that found base loads and then displacement reads off the same register
reported two torque reads.

Both were false. The register is reassigned in between - at `0x00012BBA` r4 holds
`0xFFFF30EC` but is reloaded with the receive buffer `0xFFFF300C` before the reads,
and at `0x00012F58` r5 holds `0xFFFF30EC` only long enough to set one flag bit
before being reloaded with `0xFFFF3044`. **A cross-reference tool that does not
track register reassignment produces confident nonsense**, and it produced it here
before the listing was read.

`0xFFFF30EC` is not a structure base at all. It is a flag byte, manipulated almost
entirely by bit operations.

### 59d. Where this leaves it

Settled and verifiable: the ECU is identified and its torque calibration read; the
receive map is recovered; the frame decode is confirmed byte for byte against
rimwall's; the gate chain is traced to the register and bit.

Not settled: what reads engine torque. It is not the shift decision function, which
does not branch on it at any value. The candidates left are access through a
pointer held in RAM rather than a literal, which none of the static methods used
here would catch, and code reached only from interrupt or task-scheduler context
that the harness has never entered.

## 60. TWO RAM REGIONS, AND THE LINK BETWEEN THEM IS NOT STATIC

Sections 56 to 59 record five attempts to make a CAN input reach the control code,
each one fixing a real defect found by reading the firmware, and each one moving
nothing. A register-aware cross-reference of the whole image explains why, and the
explanation is structural rather than a sixth thing to fix.

`tools/denso_xref.py` walks the listing tracking what each register holds, and
attributes an access only when the base register provably holds that address at
that instruction. It drops state at every branch target and on any instruction
whose effect it does not model, so it under-reports rather than inventing links -
which matters, because the naive version reported two reads of engine torque that
were both false. Across 297,557 instructions it resolves 2,902 addresses read and
2,936 written, dropping 33,165 accesses whose base it could not follow.

### 60a. What the two regions look like

    address        reads  writes   what it is
    0xFFFF300C..     1       0     CAN 0x410 buffer, read once by its own decode
    0xFFFF301C..     1       0     CAN 0x412 buffer, likewise
    0xFFFF30F0       0       3     engine torque, decoded - never read
    0xFFFF30F1       4       6     pedal from 0x410
    0xFFFF30F2       3       6     engine speed from 0x410
    0xFFFF30FB       7       6     pedal from 0x412 - Accelerator Pedal Travel

    0xFFFF9F55      36       0     shift schedule selector
    0xFFFF8A88       8       0     engine speed, control input
    0xFFFF357C       3       2     pedal, control input - both writes are init
    0xFFFF33AC       8       8     ATF temperature

The first group is written by the CAN decode routines and read, where it is read at
all, by a dispatch table of small stubs that each publish one value to a staging
word at `0xFFFF3B4E`. That is a reporting path, not a control path.

The second group is what the shift logic actually reads - these are the addresses
probing found in sections 53 and 54. Several of them have **many readers and no
writer this analysis can find**. `0xFFFF9F55` is read 36 times and never written.
`0xFFFF8A88` is read 8 times and never written. `0xFFFF357C` is written twice and
both writes are in an initialisation routine that fills a long list of variables
with the same value.

### 60b. What that means

Values do not travel from the CAN region to the control region by code that names
either address. Something copies them, driven by pointers held in RAM or in a
table, and no amount of static register tracking will see it - the addresses never
appear as literals at the point of the copy.

This accounts for every failure in sections 56 to 59 at once, including the ones
that looked like separate problems. The mailbox layout really was wrong, the
receive buffer really is the right destination, the gate really does need its
pending bit, and the decode really does write those four variables. All true, and
none of it sufficient, because the last hop was never in the code being run.

### 60c. Engine torque, settled

One question this does close. `0xFFFF30F0` is written three times - by the decode,
by a failsafe that zeroes it, and by a limp-home routine that writes 350 Nm - and
read nowhere in the image. Its neighbours are read using the same addressing that
the tool handles perfectly well, so this is not a gap in the method.

**Engine torque as sent on CAN 0x410 byte 0 is a published copy in this firmware,
not a control input.** Section 19's line pressure chain hangs off 0x412, and 0x412
byte 0 decodes to `0xFFFF30FB`, which the Select Monitor table names Accelerator
Pedal Travel. The pedal figure the TCU works from arrives over CAN from the ECU
rather than from a sensor of its own.

### 60d. The next move

Finding the copy engine is a job for the emulator rather than the listing. The
question - what writes `0xFFFF8A88` - is answerable by running code and watching
the address, which is how the schedule selector was found in section 53 after
static analysis had failed at it too.

## 61. THE LINK, FOUND AND WALKED END TO END

Section 60 concluded that values reach the control region by a route no static
register tracking would see, and suggested the emulator as the way to find it. It
turned out to be cheaper than that. If a copy is driven by pointers, the addresses
have to exist somewhere as data - so searching the ROM for the control addresses as
32-bit big-endian values was the first thing to try.

At `0x0002D1A8` they appear in pairs:

    FFFF3AAF  FFFF8E46
    FFFF30FB  FFFF8E47      <- pedal, decoded from CAN 0x412 byte 0
    FFFF30F1  FFFF8E48      <- pedal, decoded from CAN 0x410 byte 4
    FFFF3B5E  FFFF8E4A

Thirty-six pairs, sources scattered across RAM and destinations running almost
contiguously from `0xFFFF8E44` to `0xFFFF8E8C`.

This is not a table walked by a loop, which is what the pairing suggests at first
glance. It is the **literal pool of the function at `0x0002CF80`**, and that
function is an unrolled gather - load from a source, store to its slot, one pair at
a time:

    0002CF9C  mov.l ...,r6     ; 0xFFFF30FB
    0002CF9E  mov.b @r6,r2
    0002CFA0  mov.l ...,r6     ; 0xFFFF8E47
    0002CFA2  mov.b r2,@r6

The same function turned up in section 60 as one of the two that read
`0xFFFF30FB`, and was set aside as part of a reporting path. It was the link.

### 61a. Walked

With `0x0002CF80` in the task list ahead of the shift function, and CAN 0x412
carrying the pedal column from the vehicle log, one address moves that this project
did not write: **`0xFFFF8E47`**. Against a control identical in every respect except
the pedal byte, it tracks the source on **568 of 568 ticks**, exactly, with no lag -
254 at the wide-open-throttle row, which is 99.6 %.

So the whole path now runs under the firmware's own code:

    CAN 0x412 frame
      -> receive buffer 0xFFFF301C        (receive table, 0x08600E)
      -> decode at 0x00012CBE
      -> 0xFFFF30FB, Accelerator Pedal Travel
      -> gather at 0x0002CF80
      -> 0xFFFF8E47, in the control block

Every hop was read out of the firmware rather than assumed, and each one was found
by a failure that ruled out the alternative.

### 61b. What it does not yet do

The instruction count is still identical between the two runs, so nothing branches
differently: the shift decision function does not act on `0xFFFF8E47` at the values
this drive reaches. One value crossing is the mechanism proven, not the behaviour
explained.

### 61c. The real input surface

The cross-reference gives a better answer to what the harness should be feeding.
119 RAM addresses are read four or more times and never written by any code it can
follow, accounting for 1,293 read sites. Grouped into runs:

    0xFFFF9077 - 0xFFFF90B3    36 addresses    476 reads
    0xFFFF9053 - 0xFFFF905A     4 addresses    140 reads
    0xFFFF3AA8 - 0xFFFF3AAC     3 addresses    120 reads
    0xFFFF99CF - 0xFFFF99D4     5 addresses     54 reads
    0xFFFFAA3A - 0xFFFFAA41     8 addresses     48 reads

The first is the hottest block in the firmware and nothing writes it. Whatever
populates it - the A/D converter, an interrupt, a copy through a pointer - is not
in the code the harness runs, so the harness has to supply it. That is a far better
input set than the twelve addresses probing had assembled, and
`denso_campaign.py --from-xref` now derives it from the image instead of from
guesswork.

## 62. THE CAMPAIGN SAYS ONE INPUT MATTERS, AND WHY THAT IS THE WRONG READING

Section 61c derived the firmware's real input surface from the cross-reference:
119 RAM addresses read four or more times with no writer any static analysis can
find. An isolation campaign over the top 40 of them - each swept across its full
range with the rest held mid-scale, 256 ticks per run - gives an unusually clean
result.

**Thirty-nine of the forty do nothing at all.** Identical instruction counts,
2,117,888 every time, and `changed=1`, which means the only address that moved in
the whole of RAM was the one being swept. That includes every byte of
`0xFFFF9077`-`0xFFFF90B3`, the block carrying 476 read sites.

One responded. `0xFFFF9F55`, the shift schedule selector of section 53: 48
addresses moved and the instruction count changed to 2,171,319.

### 62a. What that actually means

Not that the other 39 are inert. The campaign runs a single entry point,
`0x00023E72`, picked early in this work because it was the shift decision function
and never revisited. Those 476 reads are real; they are in code that has never been
executed here.

This project has been probing one function and calling it the firmware. Every
result in sections 53 to 61 is conditioned on that entry point, and the honest
reading of them is narrower than it looked: they describe what one function does,
not what the controller does.

`0xFFFF9F55` responds because the shift function reads it 36 times. Everything else
belongs to code the harness never enters.

### 62b. A table of tasks

If the goal is to run the controller rather than one function, the thing to find is
whatever calls the rest. A scan for runs of consecutive ROM values that point at
instruction boundaries turns up several tables. Most have sequential targets a few
dozen bytes apart, which is the shape of a switch statement's jump table.

One does not. At **0x00D98C** there are 69 pointers, all but one distinct, aimed
all over the image - 0x014FC0, 0x090AAC, 0x019A94, 0x077A14, 0x02CEA6 and so on.
Forty-four of the 69 begin with a register-save prologue. Scattered targets and no
repeats is the shape of a dispatch or task list rather than a jump table, and one
of its entries sits just before the gather of section 61.

### 62c. A harness that survives a bad guess

Running a table of candidate tasks is only worth doing if a wrong entry does not
destroy the run. Until now one did: an address that is not an instruction boundary
throws out of the emulator step and the drive ends having written nothing, which is
what happened when a function start was guessed wrongly in section 59.
`DensoDriveLog.java` now catches per-task failures, counts them, and reports which
entries failed, so a list of 69 guesses yields results from the ones that work.

## 63. THE CALL GRAPH, AND A CORRECTION TO 62b

### 63a. 0x00D98C is not a task table

Section 62b proposed the 69 pointers at `0x00D98C` as a dispatch or task list, on
the strength of their being scattered and non-repeating. Reading the code around
them says otherwise. What precedes the region is a run of small stubs that each
increment a fault counter and jump away:

    0000D946  mov.l ...,r6     ; 0xFFFF3704
    0000D948  mov.b @r6,r2
    0000D94A  add 0x1,r2
    0000D94C  mov.b r2,@r6
    0000D94E  mov.l ...,r2
    0000D950  jmp @r2

The pointers are those stubs' literal pool. One of the 69, `0x000A2E18`, is not an
instruction boundary at all - it failed to decode when the list was run, which is
the sort of thing a table of real task entries does not contain.

That is the second time a table has been proposed from shape alone and been wrong,
after the pair-shaped literal pools of section 61. Shape is a way to find
candidates, not a way to confirm them.

It is not entirely empty of meaning. **25 of the 69 are call-graph roots**, against
402 roots among 5,051 functions overall - 36 % where chance would give 8 %. A
literal pool serving dispatch stubs would naturally hold the addresses they jump
to, so the region does carry task entries without being a task table.

### 63b. What the call graph says

`tools/denso_callgraph.py` resolves 297,557 instructions into 5,051 functions, of
which 1,225 are called by name. A function start is a register-save prologue or the
target of a call - the second matters because a leaf using only scratch registers
saves nothing and would otherwise be invisible.

The gather of section 61 has exactly one caller:

    0002CD9E  bsr 0x0002cf80

and `0x0002CD9C`, the function containing that call, **is itself a root** - nothing
in the image calls it by name. It can only be reached through a pointer.

That shape holds generally. The largest root calls 43 functions and reaches 44 in
total; the next calls 36 and reaches 37. There is no deep hierarchy and no main
that reaches everything. **The firmware is dispatched from a table**: each task is
invoked through a pointer, so tasks appear in the call graph as roots with nothing
linking them, and the call graph is a forest of shallow trees rather than one tree.

The practical consequence is that the scheduler does not have to be found. The task
set is approximately the **402 roots that call at least one function**, and those
can be run directly.

### 63c. A harness that hid its own results

The 69-entry list did run. It looked like a crash because the wrapper piped the
run through `grep ... | head -5`, and a task list of guesses produces a stream of
decode errors that consumed the quota before the RESULT line was reached. The
output said nothing at all, which reads exactly like a failed run.

Truncating diagnostic output to keep it tidy is how a result gets thrown away
without anyone noticing. The wrapper now keeps the full log, reports RESULT and the
failed entries, and counts decode errors separately.

## 64. RUNNING THE CONTROLLER RATHER THAN ONE FUNCTION

Section 63 concluded that the task set is approximately the 402 call-graph roots
that call at least one function, and that the scheduler need not be found to run
them. Running all 402 as a task list, one pass per tick, against sixty ticks of the
vehicle log spanning the wide-open-throttle row:

    entry list        instructions    addresses moved    fatal failures
    one function         4,855,577              76               -
    402 roots           30,390,470           2,249               0

**Thirty times the work and thirty times the coverage.** Where the shift function
alone touched 76 addresses, the task list touches 2,249. This is the first run in
this project that exercises the controller rather than a piece of it.

The zero fatal failures matter as much as the count. The list contains guesses -
44 of the 69 pointers examined in section 63 were not even function starts - and
312 instruction-decode errors were raised and stepped over during the run. Before
section 62c a single one of those ended the drive with nothing written.

### 64a. And the input still does not propagate

Against a control identical except for the pedal byte, **one address differs, and
it is one the harness wrote**. Worse, `0xFFFF30FB` does not appear in the changed
set at all - it was injected with values from 0x18 to 0xFE across the sixty ticks,
so something is overwriting it before the snapshot.

That is not a small detail. It means the broad run is not merely failing to
propagate the input; it is destroying it.

### 64b. Coverage and tracing want opposite things

The two runs that have worked in this project want incompatible task lists.

Section 61 traced a CAN value into the control block by running three functions:
deliver, gather, consume. It propagated exactly, 568 ticks of 568. It exercised
almost nothing else.

This run exercises 2,249 addresses and traces nothing, because a task list large
enough to be the controller also contains the routines whose job is to overwrite
inputs - the failsafe that zeroes the CAN variables, the limp-home that substitutes
350 Nm, the initialisers. Injecting a value and then running the code that exists
to replace it measures nothing.

There is also evidence that some tasks are being run wrongly rather than merely
unhelpfully: the log carries reads of addresses like `ram:f18e0560`, far outside
any mapped region, which is what happens when a function expecting arguments is
entered with the registers zeroed. A root is a function nothing calls by name; that
does not make it a task that takes no parameters.

So the harness needs both modes and should not pretend one is the other. Broad task
lists for coverage - what the firmware touches, which parameters exist. Curated
pipelines for causation - what a given input actually drives.

## 65. TWELVE EMULATORS, AND FINDING THE CULPRIT BY EXPERIMENT

### 65a. The machine was doing an sixteenth of what it could

A drive pinned one core at 102 % while fifteen sat idle. The suggestion was CUDA,
and it is worth recording why that is the wrong tool rather than just declining it.
The p-code emulator interprets one instruction at a time, with a data dependency
between every step and a branch in most of them. CUDA wants thousands of threads
running identical arithmetic over independent data; this is the opposite shape, and
there is no CUDA backend for p-code, so it would mean reimplementing SH-2E
emulation to run a workload that could not use the hardware anyway.

The parallelism that does exist is across whole drives. Each drive is independent,
so twelve of them can run at once. Measured: twelve JVMs at about 100 % each
against one before. The only obstacle is that Ghidra locks a project while it is
open, so each worker gets a 39 MB copy, made once and reused.

`tools/denso_parallel.py`. It turns a question that would have taken two hours of
sequential runs into ten minutes.

### 65b. Bisecting the task list

Section 64a left a specific question: with 402 tasks running, `0xFFFF30FB` does not
appear in the changed set at all, so something overwrites the injected pedal.
Excluding every function the cross-reference says writes that address changed
nothing, which means the writer list is incomplete - unsurprising when 33,165
accesses have a base the tracker cannot follow.

That is a question for experiment, and twelve cores make it cheap. Twelve prefixes
of the task list, run at once, over a twenty-tick window where the pedal moves:

    tasks run    pedal survives    0xFFFF8E47 filled    addresses moved
       33            yes                 yes                   27
       67            yes                 yes                2,009
      100            yes                 yes                2,005
      134            no                  yes                1,833
      167            no                  no                 1,881
      401            no                  no                 2,232

Two distinct culprits, cleanly separated. Something in tasks 100 to 134 overwrites
the pedal at `0xFFFF30FB`. Something further on, between 134 and 167, stops
`0xFFFF8E47` being written at all - which is a different failure, since the gather
that fills it runs first in the list.

The first 33 tasks move only 27 addresses between them; almost all the coverage
arrives in the next 34. Whatever the scheduler's real order is, the task list is
not uniformly interesting.

### 65c. Both culprits, named

Two more parallel rounds narrowed 401 tasks to two functions:

    0x000124F0   overwrites the injected pedal at 0xFFFF30FB
    0x0002CE7A   stops 0xFFFF8E47 changing at all

The second was predicted before it was measured, which is worth recording because
so little else in this work has been. `0x0002CE7A` sits beside the gather caller
`0x0002CD9C` and its first act is `bsr 0x0002d2cc` - the function that section 60
found reading more of the control block than any other, and the consumer of the
second gather pool at `0x02D4F4`. Both gathers write `0xFFFF8E47`. Running the
second one after the first replaces the pedal-derived value with whatever its own
source holds, and if that source is constant across the drive the address stops
changing and drops out of the log entirely.

### 65d. The call graph was missing every indirect call

`0x000124F0` calls `0x00013C5E`, which is the one root already identified as
reaching code that clobbers injected inputs and already excluded from the task
list. Excluding it achieved nothing because a different root calls it - and the
call graph did not show that, which is why the exclusion looked sound.

The cause is the same SH-2 property that has shaped most of this work. A 32-bit
constant cannot be built inline, so an indirect call is a pc-relative load into a
register followed by `jsr` through it:

    000124F2  mov.l @(0x1269c,pc),r3     ; pool holds 0x00013C5E
    000124F4  jsr @r3

Matching the address printed in the operand catches `bsr` and misses every one of
these, and misses them silently: the callee simply appears to be a function that
nothing calls. `tools/denso_callgraph.py` now joins the load to its pool entry -
the listing marks those as `.pointer` lines - and resolves the target. Called
functions go from 1,225 to 2,162, and `0x00013C5E` is now correctly attributed.

Two lessons, both already paid for elsewhere in this file. An analysis that cannot
see a construct does not report uncertainty about it; it reports a confident wrong
answer. And "nothing calls this function" is a statement about the tool before it
is a statement about the firmware.

## 66. THE CONTROLLER RUNS AND THE INPUT PROPAGATES

Dropping the two functions section 65c named - `0x000124F0`, which overwrites the
injected pedal, and `0x0002CE7A`, which runs the competing gather - and running the
remaining 399 tasks over sixty ticks of the vehicle log:

    pedal run          2,437 addresses moved
    zero-pedal control 2,359
    difference           108, of which 105 the firmware computed

**One hundred and five addresses respond to the accelerator pedal.** Not one
address in a three-function pipeline, and not nothing in a task list large enough
to be the controller, but the dependency graph of one input across the running
firmware.

Where they are:

    0xFFFF33xx    41     the largest cluster by far
    0xFFFF8Dxx    24
    0xFFFF32xx    16
    0xFFFF8Exx     9     includes the control block
    0xFFFF34xx     7
    0xFFFF3Bxx     4
    0xFFFF36xx     3
    0xFFFF84xx     1

Six of them are in the control block the gather fills - `0xFFFF8E47`, `8E4B`,
`8E4C`, `8E4D`, `8E60` and `8E61`. `0xFFFF8E47` is the slot section 61 walked by
hand; the other five arrive with it now that the whole controller is running.

None of the 105 carry names yet. The Select Monitor table names published copies,
and these are working values - which is the same distinction as section 50, from
the other side.

### 66a. What made it work

Nothing about the firmware changed between the run that traced nothing and this
one. What changed was removing two tasks whose function is to overwrite what the
harness injects, and both were found by experiment after static analysis had
missed them - one because its writer used an addressing mode the tracker cannot
follow, the other because the call that reaches it is indirect.

The recipe, for the next input:

  1. Inject at an address the firmware reads and does not itself recompute.
  2. Run a task list large enough to be the controller.
  3. Bisect it in parallel against a matched control to find what destroys the
     injection, and drop those tasks.
  4. Everything that then differs is what the input drives.

Step three is the one that needs the machine. Thirty-seven drives at ten minutes
each is six hours sequentially and about half an hour at twelve at a time.

## 67. A NATIVE SH-2E CORE, AND HOW FAR IT CAN BE TRUSTED

The p-code emulator was measured at about twenty thousand instructions a second.
The bisection of section 65 took thirty-seven drives at ten minutes each; running
twelve at once brought six hours down to thirty minutes, but the tax being paid is
interpretation of p-code inside a JVM and no number of cores removes it.

The suggestion was CUDA. It is the wrong tool and worth saying why rather than
just declining: the emulator interprets one instruction at a time with a data
dependency between every step and a branch in most of them, which is the shape a
GPU is worst at - it wants thousands of threads doing identical arithmetic over
independent data - and no CUDA backend for p-code exists, so it would mean
reimplementing SH-2E anyway. If SH-2E is going to be reimplemented, a plain C
interpreter on one core beats a GPU port of p-code by an order of magnitude and
takes a fraction of the effort.

`tools/sh2/sh2.c`, about six hundred lines. Measured against the same workloads:

    workload                        p-code        native
    one function, 20 ticks          8,256 ms       23 ms
    399 tasks, 60 ticks             ~10 min       345 ms
    399 tasks, full 568-tick drive  not attempted  2.4 s

That last is 292 million instructions in under three seconds, about 120 million a
second against the p-code emulator's twenty thousand.

### 67a. Two bugs it found in itself

Unimplemented opcodes are reported by encoding and address rather than skipped,
which caught both.

`mov.w @(disp,PC),Rn` **sign-extends**, and not doing so turned the negative stack
adjustment that opens most functions into a large positive one. The stack pointer
walked out of RAM and the function returned after ninety instructions instead of
eight thousand. This is the same sign extension that section 45 turned on - a
16-bit literal is how this architecture names a 0xFFFF.... address at all.

`rotcl` was ninety percent of the remaining misses on its own. The compiler uses it
for every multi-word shift, so leaving it out corrupts arithmetic across the image
while the emulator still appears to run perfectly.

### 67b. How far it is validated - and it is not far enough

Against the p-code emulator, comparing every cell where that emulator states a
value:

    one function, 20 ticks           358 of 358 cells      exact
    101 tasks, 20 ticks           38,595 of 38,728 cells   99.66 %
    134 tasks                     34,194 of 34,306         99.67 %
    167 tasks                     34,564 of 34,659         99.73 %
    399 tasks, 60 ticks          120,455 of 129,947        92.70 %

Exact on a single function, and degrading as tasks are added. The correlation
points at a cause that is not an opcode: the remaining unimplemented encodings all
occur at addresses like 0x20, 0x38 and 0x7F - inside the interrupt vector table,
several of them odd and therefore not instruction boundaries at all. A task entered
with zeroed registers computes a null jump and executes the vector table as code.
The p-code emulator does the same, as its reads of `ram:f18e0560` in section 64b
show, but two emulators wandering through garbage do not wander identically.

So the divergence is probably not a fault in the core. **Probably is not good
enough.** Until it is exact on a task list, findings come from the p-code emulator
and the native core is used for search - bisection, sweeps, anything where the
answer will be confirmed by a slower run afterwards. A fast emulator that is subtly
wrong is worse than a slow one, and this file has enough entries already about
tools that produced confident wrong answers.

## 68. THE INPUT DEPENDENCY MAP OF THE CONTROLLER

Section 62 could only sweep inputs against one function, because a drive of the
full task list took ten minutes and 119 inputs would have been twenty hours. On
the native core each drive is about a third of a second, so the sweep that was out
of reach takes ninety seconds.

The fidelity question of section 67b does not apply here, and it is worth being
precise about why. The native core diverges from p-code by 7 percent over a long
task list and the cause is still open. That would matter if the question were what
value an address holds. It is not: the question is which addresses move when an
input moves, and that is answered by comparing two native runs to each other. Any
systematic error is present in both arms and cancels. The map describes dependency
structure, not absolute values.

### 68a. Two constants, not a sweep

The first attempt reported every one of the 119 inputs driving all 2,265 moving
addresses, which is an experiment failing rather than a firmware that is entirely
coupled. Sweeping an input while the control holds it means the two runs differ at
every tick from the first, and with 399 tasks sharing state the trajectories
separate completely.

Holding the input at one constant against another isolates it. The schedule
selector then drives 15 addresses and an inert input drives none, and the figure is
stable from the second tick onward rather than growing - so this is real dependency
and not divergence.

Two harness faults were found on the way, both of the kind that produce a confident
answer rather than an error. A task list of 399 entries is about 4,400 characters
and passing it as one argument through `wsl` silently failed to start the process -
which read as every input driving nothing. And `os.path.join` on Windows produces
backslashes, which WSL does not treat as separators, so the runs wrote to one file
while the reader opened a stale one.

### 68b. The map

Sixteen of the 119 inputs drive anything at all. 153 addresses are driven by
exactly one input.

    input         drives   where
    0xFFFFA6A2       85    0xFFFF36xx, 0xFFFF85xx, 0xFFFF8Dxx, 0xFFFF8Exx, 0xFFFF91xx
    0xFFFF8CF1       16    0xFFFF8D48-0xFFFF8D67, one tight cluster
    0xFFFF9F55       15    0xFFFFBCxx and 0xFFFFBExx
    0xFFFF380A       13    0xFFFF37xx, 0xFFFF39xx
    0xFFFF3AAC       10    scattered, including 0xFFFF8654 and 0xFFFF895E
    0xFFFFA442        8    0xFFFF9F5x, 0xFFFFA042
    0xFFFFA448        8    the same set but 0xFFFFA023 instead of 0xFFFFA042
    0xFFFF3808..16    5    each, in a repeating pattern
    0xFFFFA01A        2
    0xFFFF3AA8        1    0xFFFF8E84

`0xFFFFA6A2` is much the largest driver in the firmware and has no name yet.

### 68c. Two things the shape of the map says

**There is an array of eight identical channels.** `0xFFFF3808`, `380A`, `380C`,
`380E`, `3810`, `3812`, `3814` and `3816` each drive the same five slots at the
same relative offsets - `0x3808` drives `0x37F8`, `0x395A`, `0x395B`, `0x397A`,
`0x3982`; `0x380C` drives `0x37FC`, `0x395E`, `0x395F`, `0x397C`, `0x3984`. Eight
inputs two bytes apart, each producing the same four derived quantities two bytes
apart. That is one routine over an array, and finding what the array is will name
eight inputs and thirty-odd outputs at once.

**`0xFFFFA442` and `0xFFFFA448` are a pair.** They drive an identical set of six
addresses and then diverge on exactly one - `0xFFFFA042` against `0xFFFFA023`. Two
channels of the same measurement, kept apart only at the last step, which is what a
plausibility check between redundant sensors looks like.

### 68d. A caveat on the schedule selector

The 15 addresses `0xFFFF9F55` drives are all in `0xFFFFBC99`-`0xFFFFBEFB`, and the
harness puts the stack at `0xFFFFBF00`. These are stack locals of whatever consumed
the value, not persistent state. The dependency is real - the selector demonstrably
changes what the code computes - but the addresses it appears at here are
temporaries, and naming them would be naming stack slots. The single-function sweep
of section 62 saw the same selector move 48 addresses, so the two agree that it
matters while disagreeing about where its effect is visible.

### 68e. What the eight channels are

Each of the eight begins the same way: read the channel, compare it against a
threshold, and if it is at or above the threshold check a chain of flags before
doing anything.

    00089A64  mov.w @r2,r6      ; [000A2678] = 0x170     the threshold
    00089A66  mov.l ...,r5      ; 0xFFFF3808             the channel
    00089A68  mov.w @r5,r2
    00089A6A  cmp/ge r6,r2
    00089A6C  bf 0x00089ad6                              below it, do nothing
    00089A6E  mov.l ...,r6      ; 0xFFFF8921             a flag
    00089A70  mov.b @r6,r2
    00089A72  tst r2,r2
    00089A74  bf 0x00089ad6                              set, do nothing
    ... three more flag checks in the same shape

**All eight read their threshold from the same ROM location, 0x000A2678.** Eight
channels, one shared calibration constant, identical code, and a chain of enabling
conditions before acting: that is eight instances of the same diagnostic monitor,
not eight different measurements. The five addresses each channel drives are its
counter, timer and flags.

Two things follow. `0x000A2678` is a calibratable diagnostic threshold and belongs
in the definition. And naming any one of the eight channels names all eight, along
with the forty addresses they drive - which is the largest single naming
opportunity the dependency map offers.

## 69. THE LARGEST DRIVER IS A FILTERED STATE, NOT A RAW INPUT

`0xFFFFA6A2` is the biggest single driver in the dependency map of section 68 - 85
addresses - and had no name. Following it settled what it is, though not yet what
it measures.

### 69a. It is written, through a pointer

The cross-reference reports no writer. It has one. At `0x0007A90A`:

    0007A8FC  mov.l ...,r6      ; 0x000CE404, a calibration byte = 0x33
    0007A8FE  mov.b @r6,r2
    0007A902  mov #0x1,r2
    0007A904  shll8 r2          ; 0x100
    0007A906  sub r6,r2         ; 256 - 51 = 205
    0007A908  extu.w r2,r5      ; the gain
    0007A90A  mov.l ...,r4      ; 0xFFFFA6A2 - the DESTINATION
    0007A90E  jsr @r2           ; 0x0000289C

and `0x0000289C` is a shared slew-rate filter:

    0000289C  mov r4,r1         ; r1 = destination pointer
    000028A4  mov.w @r1,r2      ; current value
    000028A6  cmp/ge r5,r2      ; against the target
    000028AC  sub r5,r2         ; move toward it by gain/256
    000028AE  mul.l r2,r4
    000028B2  shlr8 r6
    000028C6  mov.w r6,@r1      ; and write it back

So `0xFFFFA6A2` is not a raw input at all. It is a **slew-limited state variable**,
its rate of change set by the calibration byte at `0x000CE404`, and the write is
invisible to any cross-reference that stops at a call boundary because the
destination arrives in a register. A byte-width version of the same filter sits at
`0x000028CC`.

`0x000CE404` is therefore a calibratable filter constant and belongs in the
definition.

### 69b. What it does not explain

The obvious next thought was that this is the mechanism behind section 60's
central puzzle - 119 addresses read often and written by nothing. It is not.
Counting every call site whose `r4` was just loaded with a RAM address: 93 distinct
addresses are handed to a callee as a pointer, 13 of those have no writer the
cross-reference can see, and **exactly one of them is in the list of 119**.

So pointer-passing accounts for `0xFFFFA6A2` and twelve others, and the other 118
remain unexplained. Worth saying plainly, because the pattern was compelling enough
to look like a general answer after one example.

### 69c. What it measures is still open

A 16-bit quantity, scaled by 0.1 into a float at `0xFFFF8D8C` by the unit
conversion block at `0x0002B510`, alongside `0xFFFFA6CF` scaled by 0.01. It lives
two dozen bytes from `0xFFFFA6D8`, which the Select Monitor table names SI-Drive
Mode, so the block is vehicle-level state. Sweeping it moves two floats in the
control block at `0xFFFF8E6C` and `0xFFFF8E78`.

Tenths, sixteen bits, slew limited, and it reaches more of the firmware than any
other single value. Road speed would fit all of that. So would several other
things, and this file has enough entries about plausible answers that turned out
wrong, so it stays unnamed until something decides it.

## 70. THE HARNESS WAS RUNNING A RAM SELF TEST ON EVERY TICK

Chasing what writes `0xFFFFA6A2` turned up something larger. Watching writes during
a drive with nothing injected - so that any write seen is the firmware's own -
showed `0xFFFF9077` and `0xFFFF9053` both written by a single instruction at
`0x00008D9A`, with the same value, 0x5A.

That instruction is inside a block copy:

    00008D86  mov.l ...,r5      ; 0xFFFF2800   end
    00008D88  mov.l ...,r14     ; 0xFFFF3000
    00008D8C  mov.l ...,r4      ; 0xFFFF2000   source
    00008D90  mov #-0x70,r1
    00008D92  shll8 r1          ; 0xFFFF9000   destination
    00008D98  mov.l @r4+,r2
    00008D9A  mov.l r2,@r1      ; copy 2 KB
    ...
    00008DA6  mov.l ...,r4      ; 0x5AA5A55A
    00008DA8  mov.l r4,@r2      ; fill the source with the test pattern

`0x5AA5A55A` is the classic memory test pattern. This is a **RAM self test**: save
`0xFFFF2000`-`0xFFFF27FF` into `0xFFFF9000`-`0xFFFF97FF`, write the pattern over
the source, verify, restore. Run once at startup on the car.

It is task `0x00008D58`, it is in the task list of section 63, and it has been
running **on every tick of every drive** in sections 64 to 69.

### 70a. What that explains

Section 61c called `0xFFFF9077`-`0xFFFF90B3` "the hottest block in the firmware,
476 read sites and no writer", made it the centrepiece of the input surface, and
swept all of it. Nothing moved, in section 62a, and the conclusion drawn was that
the harness ran only one function.

The real reason is simpler. **That block is the RAM test's save area.** Its 476
read sites are the test's own verify loop. It is not control state, it was never
going to respond to anything, and neither was `0xFFFF2000`-`0xFFFF27FF`, the region
being tested.

### 70b. Finding the rest of them

A tick-to-tick diff cannot see this: a routine that writes the same value every
tick shows no change after the first. So the native core now records its write set
- every distinct address written, whatever the value - and that makes block
operations obvious. Run alone, task `0x00008D58` writes 4,108 bytes in two 2 KB
contiguous runs.

Total bytes is the wrong test, though. The gather of section 61, `0x0002CD9C`,
writes 1,061 bytes and is entirely legitimate. What separates a block operation
from control code is a long *contiguous* run: control code touches scattered bytes.
Four tasks write a contiguous run of 512 bytes or more - `0x00008D58`,
`0x00065C80`, `0x00065CFC` and `0x00065D0A` - and the gather is correctly kept.

### 70c. What changed, and what did not

With those four dropped and the two test regions excluded from the candidate
inputs:

                                    before    after
    candidate inputs                   119       70
    addresses moving on their own    2,265      727
    inputs that drive anything          16       16
    addresses driven by one input      153      145

**Two thirds of the apparent activity in every drive was the memory test.** The
dependency structure survived almost unchanged, which is the reassuring part: the
map of section 68 was measuring something real, and was not an artefact of the
noise it was measured through.
