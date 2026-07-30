# Tools

Run from the repo root. Stock Python 3, no dependencies.

```bash
python tools/checksum.py --fix edited.bin      # after EVERY edit, before flashing
python tools/generate_romraider_def.py         # rebuild the definition
python tools/validate_xml_defs.py              # gate: must pass before shipping
python tools/plot_shift_map.py rom/91D1206000_5EAT.bin
python tools/scan_threshold_curves.py --unmapped-only
```

| Tool | Does |
|---|---|
| `checksum.py` | Verify/fix the checksum. RomRaider can't do this one. |
| `generate_romraider_def.py` | Builds the definition. **Edit this, not the XML.** |
| `validate_xml_defs.py` | Checks every address against its own firmware. |
| `plot_shift_map.py` | Shift schedule as a PNG chart. |
| `scan_threshold_curves.py` | Finds shift-curve-shaped arrays. 82 found, 8 mapped ([§15](../FINDINGS.md)). |
| `extract_pressure_curves.py` | Line-pressure curves in kPa. |
| `test_checksum.py` | Round-trip tests for `checksum.py`. |
| `romraider-cli/` | Verify + render through RomRaider's real classes ([README](romraider-cli/README.md)). |
| `ghidra/` | Decompilation pipeline. Needs rimwall's M32R module, not upstream's. |

`*.json` are generated but committed — deriving them needs a full Ghidra pass.

### Three things that bite

**Verification has levels, and they catch different bugs.** Addresses can be
perfect and RomRaider still ignores the table; it can load the table and still
present it unusably. That's why `validate_xml_defs.py`, `Verify3D` and
`RenderTable` all exist.

**Pattern scanning is not proof.** A loose scan gives 307 candidates here, mostly
coincidence. Every confirmed table came from call-site enumeration instead.

**Never extrapolate offsets between firmwares.** One has `SpeedTrimA` at +142 where
its siblings are at +144. Generation aborts on a mismatch — that's the check that
caught it.

### Adding a firmware

1. `.bin` into `rom/`, confirm `checksum.py` says OK.
2. `ghidra/decompile_all_roms.sh` — imports at base `0x0`, seeds vectors, decompiles.
3. Find the lookup routines: interpolation at `main`, `main+0xD8`, `main+0x1A4`;
   record lookup at `main-0xEC`.
4. Enumerate their call sites, read the table pointer from each argument.
5. Add a profile to `ROM_PROFILES`, regenerate, validate.
