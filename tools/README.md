# Tools

All paths are repo-relative; run them from the repository root.

## Everyday

| Tool | What it does |
|---|---|
| `checksum.py` | Verify or fix a ROM's checksum. **Run `--fix` after every edit, before flashing** — RomRaider cannot do it. Detects which of the two region conventions the image uses. |
| `test_checksum.py` | Round-trip tests for the above. Edits a copy, confirms it's flagged, fixes it, and confirms undoing the edit reproduces the original byte for byte. |
| `generate_romraider_def.py` | Builds `definitions/5eat_tcu_romraider_defs.xml` from every ROM in `rom/`. **Edit this, not the XML.** |
| `validate_xml_defs.py` | Checks every table address against the firmware it belongs to, matched by cal ID. |
| `romraider-cli/` | Loads the definition through **RomRaider's own parser** and reports what it built. See its [README](romraider-cli/README.md). |

Verification runs at three levels, and they answer different questions:

1. `generate_romraider_def.py` — does each address agree with the count field *the ROM itself stores*? Aborts generation if not.
2. `validate_xml_defs.py` — same check independently, across all firmwares, from the finished XML.
3. `romraider-cli/` — will **RomRaider** accept it? A definition can have flawless addresses and still be silently ignored if the schema is wrong. That has happened here.

## Exploratory

Used during reverse engineering, kept because they document the method.

| Tool | What it does |
|---|---|
| `scan_rom.py` | Entropy map — finds the code/calibration/blank regions. |
| `find_tables.py` | Arithmetic-progression scan; first surfaced the repeated-axis pattern. |
| `extract_tables.py` | Full `[count][axis][data]` extractor plus 32-bit pointer cross-reference. |
| `find_checksum.py` | Brute-forces standard checksum forms against the stored value. How the algorithm was found. |

> **Pattern scanning is not proof.** It yields 307 candidates in this ROM, mostly
> coincidence. Every confirmed table here came from call-site enumeration in the
> decompiler output instead. Use these to explore, not to conclude.

## Ghidra scripts (`ghidra/`)

Copy into `~/my_scripts/` and run via `analyzeHeadless`.

| Script | What it does |
|---|---|
| `SeedAuto.java` | **Start here.** Derives the real interrupt handlers from the ROM and runs full analysis. Works unchanged across firmwares. |
| `DecompileAll.java` | Decompiles every function to one file. Grep that before tracing anything by hand. |
| `Decompile.java` | Single function. |
| `XrefDump.java`, `FindWriters.java` | Cross-reference helpers. |

Seeding matters more than it sounds: the reset vector alone reaches ~130
functions, while seeding the four real interrupt handlers reaches ~1,090.

## Data files

Generated, but committed because deriving them needs a full Ghidra pass:

- `shift_curves.json` — per-firmware shift schedule addresses and row counts.
- `hysteresis_curves.json` — record-format curves in the base ROM, with names and traced inputs.
- `hysteresis_by_rom.json` — the same curves in the five firmwares where they map safely.

## Adding a firmware

1. Drop the `.bin` in `rom/`, confirm `python tools/checksum.py rom/yours.bin` says OK.
2. Import into Ghidra at base `0x0`, language `m32r:2:default`, then run
   `SeedAuto.java` and `DecompileAll.java`.
3. Find the lookup routines in the decompiler output. The three interpolation
   variants sit at `main`, `main+0xD8`, `main+0x1A4`; the record lookup at
   `main-0xEC`.
4. Enumerate their call sites and read the table pointer from each argument.
   Every firmware issues the same twelve in the same address order.
5. Add a profile to `ROM_PROFILES` with the offsets, regenerate, and validate.

**Do not extrapolate offsets between firmwares.** They are not uniform — one
firmware has `SpeedTrimA` at +142 while every other family in the same image is
at +144, and the 512 KB pair splits three ways. Generation aborts if a derived
address disagrees with the ROM, which is the check that caught both.
