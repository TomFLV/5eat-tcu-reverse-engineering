# Running the tools

*Written 2026-08-07. Every claim about what runs from a bare clone was verified by
running it, not by reading the source.*

Most of the analysis tools need more than a clone. This says exactly what, and
what happens if you skip it, because the failure mode is usually a tool that
runs, finds nothing, and reports that as a result.

## The work directory

Scratch space for the emulator, its build, and intermediate files far too large to
commit. Set `FIVEEAT_WORK`; the default is a `work` directory beside the clone.

```
export FIVEEAT_WORK=/path/to/work        # or on Windows: set FIVEEAT_WORK=D:\work
python tools/workdir.py                  # prints what resolved, and what is missing
```

Everything else derives from that and from the repository root, which is computed
from the tools' own location. Nothing is hardcoded to one machine any more —
fifteen files used to be.

## What IS in the repository

The SH-2E disassembly of the reference Denso firmware is committed:
`disasm-denso/Impreza_STI_3.583_JDM2011.asm`, 34 MB, ~650,000 instructions with
literal pool values resolved inline. Fourteen tools read it, and it was previously
excluded on a size figure that had been asserted rather than measured.

Regenerate it, or produce it for another image, with Ghidra and the SH-2E language
this project builds: `tools/ghidra/DensoDisasmAll.java`, see
[README-sh2e.md](../tools/ghidra/README-sh2e.md).

## What is NOT in the repository

| Needed by | What | Why not committed | How to get it |
|---|---|---|---|
| — | `disasm-denso/*.asm` | **now published** — 34 MB, not the ~300 MB this table used to claim | already in the clone |
| 6 tools | `$FIVEEAT_WORK/xref.json` | regenerable, large | `python tools/denso_xref.py` |
| naming tools | `tools/denso_callgraph.json` | regenerable | `python tools/denso_callgraph.py disasm-denso/<image>.asm --dump tools/denso_callgraph.json` |
| emulator tools | `$FIVEEAT_WORK/sh2/sh2` | a compiled binary | `gcc -O2 -o sh2 tools/sh2/sh2.c` |

The SH-2E disassembly needs a Ghidra language this project builds: see
[tools/ghidra/README-sh2e.md](../tools/ghidra/README-sh2e.md). Ghidra ships no
SH-2E, and the stock SH-2 gets the FPU instructions wrong rather than refusing
them, which is worse.

## What works with only a clone

These need nothing but the repository and Python:

```
python tools/validate_xml_defs.py           # 5,911 checks, 16 M32R firmwares
python tools/validate_denso_defs.py         # 5,112 checks, 9 Denso firmwares
python tools/check_table_aliasing.py        # tables that share ROM bytes
python tools/denso_find_dtc.py              # locates the DTC table in each image
python tools/checksum.py                    # checksum read/fix
python tools/test_checksum.py               # its round-trip tests
```

All of them read the ROM images, which ARE committed.

## Verifying the application

Loading a definition through RomRaider's own parser is a different check from
validating it against the ROM, and this project has shipped a definition that
passed the second and failed the first — a fabricated element made tables vanish
silently with every address correct.

That check needs a JDK with AWT, `xvfb`, and the built application jar, and is
described in [tools/romraider-cli/README.md](../tools/romraider-cli/README.md).
Use the jar from the built app image, not a stock RomRaider: stock has no
`subarutcudenso` checksum manager and throws before it parses a single table.

## Building FastECU and FreeSSM

Neither is vendored here. Both are other people's work - FastECU is Miika Syvänen's,
FreeSSM is Comer352L's and GPLv3 - and both build cleanly under WSL on Ubuntu 26.04.
They matter to this project because FastECU carries a K-line module for the Hitachi
M32R TCU and FreeSSM carries the transmission definitions cross-checked in FINDINGS
section 87.

    sudo apt install qt6-base-dev qt6-base-dev-tools qt6-serialport-dev \
        qt6-remoteobjects-dev qt6-websockets-dev qt6-charts-dev qt6-tools-dev \
        qt6-tools-dev-tools qt6-5compat-dev libssl-dev \
        qtbase5-dev qtbase5-dev-tools libqt5serialport5-dev libgl1-mesa-dev

    git clone https://github.com/miikasyvanen/FastECU
    mkdir -p build/fastecu && cd build/fastecu
    /usr/lib/qt6/bin/qmake ../../FastECU/FastECU.pro && make -j$(nproc)

    git clone https://github.com/Comer352L/FreeSSM
    mkdir -p build/freessm && cd build/freessm
    /usr/lib/qt5/bin/qmake ../../FreeSSM/FreeSSM.pro && make -j$(nproc)

FastECU is Qt6 and FreeSSM is Qt5, so both stacks have to be installed and the right
qmake invoked explicitly - the unqualified `qmake` on this distribution is Qt5 and
will not configure FastECU. Two dependencies are not obvious from the .pro file and
each stops the build with a missing header rather than a useful message:
`qt6-5compat-dev` for `QtCore5Compat/QTextCodec`, and `libssl-dev` for
`openssl/conf.h`.

**Take FastECU's master branch, not `development`.** The branch names invert the
usual expectation: master is newer (2026-07-25) than `development` (2025-04-13).

FreeSSM's `e5at-permanent-adjustments` branch adds definitions for adjustments the
Denso E5AT TCUs store permanently, and the code to send the save command. Master does
not have it.

### Reaching the interface from WSL

The USB device has to be handed across, and GUI windows come back through WSLg with
no configuration.

    usbipd bind   --busid 1-1        # once, from an elevated Windows shell
    usbipd attach --wsl --busid 1-1

`usbipd list` names the bus id. The Tactrix appears as `0403:cc4d`.
