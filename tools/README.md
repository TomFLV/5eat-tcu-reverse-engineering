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
| `checksum.py` / `test_checksum.py` | Verify/fix the checksum. The bundled build does this on save; this is for stock RomRaider or scripting. |

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

1. `.bin` into `rom/`, confirm `checksum.py` says OK.
2. `ghidra/decompile_all_roms.sh` — imports at base `0x0`, seeds vectors, decompiles.
3. Run the finders; each locates its family by signature and will say if it can't.
4. Add a profile to `ROM_PROFILES`, regenerate, validate.
