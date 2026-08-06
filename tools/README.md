# Tools

Run from the repo root. Stock Python 3, no dependencies.

```bash
python tools/generate_romraider_def.py         # rebuild the definition
python tools/validate_xml_defs.py              # gate: must pass before shipping
python tools/plot_shift_map.py rom/91D1206000_5EAT.bin
python tools/checksum.py --fix edited.bin      # only if NOT using the bundled build
```

## Build and verify

| Tool | Does |
|---|---|
| `generate_romraider_def.py` | Builds the definition. **Edit this, not the XML.** |
| `validate_xml_defs.py` | Checks every address against its own firmware. Knows all six table geometries in use. |
| `romraider-cli/` | Verify and render through RomRaider's real classes ([README](romraider-cli/README.md)). |
| `extract_selector_table.py` | Locates the table deciding which shift schedule GROUP applies (FINDINGS 33) |
| `extract_atf_blend.py` | Locates the ATF blend window per firmware by reading each one's own decompiler output |
| `detect_fixed_point.py` | Finds tables stored as fixed point, provable from the stored bits alone |
| `checksum.py` / `test_checksum.py` | Verify/fix both checksums. The bundled build does this on save; this is for stock RomRaider or scripting. |
| `find_rom_offsets.py` | Derives a new firmware's table offsets. Run `--self-test` first: it must reproduce the offsets already recorded before its answers are worth anything. |

## Finders

Each writes a `*.json` the generator consumes. They locate tables **per firmware by
signature**, never by assuming an address holds across images.

| Tool | Finds |
|---|---|
| `extract_shift_modes.py` | All 50 shift modes — 10 conditions × 5 gear limits |
| `extract_line_pressure_targets.py` | Line pressure targets, engine torque → kPa |
| `extract_downshift_pressure.py` | Per-downshift pressure maps and ramp timing |
| `extract_dtc_table.py` | The 53 trouble codes, located by P-code signature |
| `extract_pressure_curves.py` | Line pressure curves, fingerprinted on the FSM's 1370 kPa |
| `scan_threshold_curves.py` | Every shift-curve-shaped array (82 on the reference ROM) |
| `classify_raw_tables.py` | Proposes fixed-point scales for tables still shipping raw |

## Other

| Tool | Does |
|---|---|
| `plot_shift_map.py` | Shift schedule as a PNG chart, stdlib only |
| `fetch_forum_thread.py` | Archives a RomRaider forum topic to `docs/` |
| `ghidra/` | Decompilation pipeline. Needs rimwall's M32R module, not upstream's. |

## The Denso family

The 5EAT was built with two controllers. Everything above is the Hitachi M32R; these
handle the **Denso SH705x** used by later JDM and EDM cars and the 2014 Tribeca. It
is a separate family end to end — separate ROMs in `rom-denso/`, separate definition,
separate checksum plugin — so it has its own generator rather than more entries in
the M32R one.

| Tool | Does |
|---|---|
| `generate_denso_def.py` | Builds `definitions/5eat_tcu_denso_romraider_defs.xml`. **Edit this, not the XML.** |
| `survey_denso_tcu.py` | Identifies a Denso image, checks its block integrity table, and decodes its shift tables |
| `find_denso_pointer_tables.py` | Finds the tables the firmware actually **indexes**, not merely the ones that parse. This is the filter that matters — see below |
| `denso_data_ranges.py` | Computes which bytes are calibration data, so a disassembly sweep does not decode them as code |
| `profile_denso_tables.py` | Measures every table: axis ranges, step patterns, monotonic rows, unused filler, firmware coverage. Proposes nothing |
| `cluster_denso_tables.py` | Groups those into ~86 families by shape and axis signature |

**Scanning for headers over-reports badly.** About 1770 structures per image satisfy
the header format; in a megabyte, plenty of 28-byte windows have pointers the right
distance apart by chance. The firmware settles it — tables are reached through arrays
of pointers to their headers, so a run of consecutive words all pointing at valid
headers is a real index. That leaves **140–186 tables per image**, and the definition
ships only those.

The twelve shift tables are **six upshift/downshift pairs**, not twelve schedules, and each has four live rows which are the four upshifts in order (1-2, 2-3, 3-4, 4-5). Both facts come from comparing a calibration against a log from the car running it; see FINDINGS 37.

One exception, deliberately: the shift-schedule block is identified by a run of
consecutive headers at an address rimwall reported independently, which is stronger
evidence than the pointer index. Filtering it by the index too breaks that run and
drops two schedules that are certainly real.

Denso use the same table format as their engine ECUs, which RomRaider already
understands, so no editor changes were needed to read them:

    +0x00 uint16 rows        +0x0C uint32 -> data, uint16
    +0x02 uint16 cols        +0x10 uint32 flags
    +0x04 uint32 -> X axis   +0x14 float  scale
    +0x08 uint32 -> Y axis   +0x18 float  offset      (28-byte stride)

Axes are IEEE-754 floats lying immediately before the data, X then Y. Requiring
exactly that spacing is what distinguishes a real header from a coincidental byte
run — without it the scan returns thousands of matches.

## Batch interface

The application itself is the fastest way to check a definition, because it is the
thing being checked. `tcu-cli.exe` in the release, or `--cli` on the main launcher,
runs headless and prints one JSON object.

```bash
tcu-cli info     <def.xml> <rom.bin>                    # identity, tables, checksums
tcu-cli tables   <def.xml> <rom.bin> [substring]        # list tables
tcu-cli dump     <def.xml> <rom.bin> <table>            # cell values
tcu-cli checksum <def.xml> <rom.bin> [--fix out.bin]    # report, optionally correct
tcu-cli set      <def.xml> <rom.bin> <table> <i> <v> <out.bin>
tcu-cli selftest [<def.xml> <rom.bin>...]               # no arguments: everything bundled
```

**The contract, for scripting or for an LLM driving it:**

* **stdout is only ever JSON.** Logging goes to stderr, so `... 2>/dev/null | jq`
  is safe. One object per invocation, never a stream.
* **Exit status is the answer.** `0` means yes, non-zero means no. `info` and
  `checksum` fail when a checksum is wrong; `selftest` fails if any ROM fails.
* **Failures are structured too**: `{"ok":false,"error":"..."}`, and the error
  carries the root cause plus the first few stack frames, so a failure says where
  it happened rather than just what type it was.
* **Keys are stable.** `ok`, `error`, `xmlid`, `tables`, `checksumsValid`,
  `checksumsTotal`, `checksumOk`, `values`, `results`.
* **It is headless.** No display, no window, no dialog that can block waiting for
  someone to click it.

## Repository traffic

GitHub keeps view counts private to the repository owner and exposes only a rolling
fourteen-day window. There is no public badge for them: the third-party ones count
requests for the badge image, which is a different number and trivially inflated.
Download counts are public, which is why the README carries a badge for those and
not for views.

    gh api repos/:owner/:repo/traffic/views
    gh api repos/:owner/:repo/traffic/clones
    gh api repos/:owner/:repo/releases --jq '.[] | .tag_name, ([.assets[].download_count] | add)'

## Running the code

Ghidra ships a p-code emulator, and it works against the SH-2E language this project
added - so the Denso firmware can be executed rather than only read.

    python tools/denso_emulate.py 0x0002C3DA --regs r4=0x40
    #   155 instructions, 11 table loads, 4 distinct tables

    python tools/denso_emulate.py 0x0002C3DA --sweep r4=0,192,64

The sweep runs a function once per input value and reports which calibration tables
each run reaches, which is how an axis shows itself from the outside. Which tables a
run touches is read off the executed path: every calibration access on this core
goes through a PC-relative literal, so the path and the literal map together are
equivalent to instrumenting the reads.

Needs a listing from `DensoDisasmAll.java` and the output of `denso_literals.py`.
See FINDINGS section 49.

## What the code reads

`denso_literals.py` resolves every PC-relative literal load out of the ROM image -
all of them, not the 63% Ghidra annotates - and classifies each as a RAM variable, a
calibration table, code, or a constant.

    python tools/denso_literals.py disasm-denso/Impreza_STI_3.583_JDM2011.asm --tables

`denso_ram_xref.py` inverts it: for any RAM address, every instruction that touches
it, joined against the Select Monitor names. `denso_trace_ssm.py` names the working
variables behind the Select Monitor staging buffer (FINDINGS section 47).

## Naming the RAM

`map_ssm_parameters.py` joins the SSM parameter table in the ROM to FreeSSM's list
of what each SSM address means, which names on-chip RAM addresses:

```bash
python tools/map_ssm_parameters.py rom/*.bin
# ACD1A06000...  table 0x1D600  76 supported  37 named  27 traced to a variable
```

The named addresses are a staging buffer the Select Monitor reads, not the working
variables - but the routine that fills it names its sources, so the tool follows
that hop and reports the real variable and its scaling. Output goes to
`tools/ssm_parameters.json`.

Works on the sixteen M32R images. The Denso equivalent has not been located; see
FINDINGS section 40.

FreeSSM is Comer352L's, GPLv3. It is downloaded when the tool runs and is not
redistributed here. The approach is rimwall's, from forum topic 13725.

`selftest` is the one that matters: it loads each ROM, confirms the checksums as
shipped, edits a cell through the real write path, saves through `Rom.saveFile`, and
confirms them again. Nothing reaches the disk — `saveFile` returns bytes rather than
writing — so it is safe to point at the shipped ROMs.

With no arguments it finds the definitions and ROMs beside the installed application
and checks all of them, trying each definition against each image until one matches:

```bash
tcu-cli selftest
# {"results":[...],"ok":true,"failed":0}     25 firmwares, both families
```

Explicit paths still work, for one definition against a chosen set:

```bash
tcu-cli selftest definitions/5eat_tcu_romraider_defs.xml rom/*.bin
```

Pointing a definition at the wrong family is expected to fail: each declines ROMs it
does not match, which is the safety mechanism and not a bug.

## Three things that bite

**Verification has levels, and they catch different bugs.** Addresses can be perfect
and RomRaider still ignores the table; it can load the table and still present it
unusably. That's why `validate_xml_defs.py`, `Verify3D` and `RenderTable` all exist —
each has caught a defect the others missed.

**Pattern scanning is not proof.** A loose scan gives 307 candidates here, mostly
coincidence. Every confirmed table came from call-site enumeration or from following
a value through the code. `classify_raw_tables.py` deliberately adopts nothing.

**Never extrapolate offsets between firmwares.** One has `SpeedTrimA` at +142 where
its siblings are at +144. Generation aborts on a mismatch — that's the check that
caught it.

## Adding a firmware

1. `.bin` into `rom/`, confirm `checksum.py` reports both checksums OK.
2. `ghidra/decompile_all_roms.sh` — imports at base `0x0`, seeds vectors, decompiles.
3. Run the finders; each locates its family by signature and will say if it can't.
4. `find_rom_offsets.py --self-test`, then run it on the new image for its offsets.
5. Add a profile to `ROM_PROFILES`, regenerate, validate.
6. `tcu-cli selftest` over the whole `rom/` directory — the new firmware must load,
   edit, save and re-verify like the rest.

For a Denso image the first four steps do not apply: drop it in `rom-denso/` and run
`generate_denso_def.py`, which finds its tables itself.
