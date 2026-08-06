# ECU-side tooling

The TCU does not measure engine torque. It is told, over CAN 0x410 byte 0, by the
engine ECU — and section 19 puts that value at the head of the line pressure
chain. Every vehicle log we have is TCU-side and carries no torque column, so for
a long time that byte was fed as zero and the chain sat untouched no matter how
faithfully the rest of the frame was delivered.

It was never really missing. The ECU derives requested torque from accelerator
pedal angle and engine speed, and the logs carry both of those. Reading the
requested-torque map out of the ECU calibration turns two columns we already had
into the torque signal we did not.

## The matching ECU

The TCU image this project works against is `Impreza_STI_3.583_JDM2011`, unit
A3DE207100, calibration WQDE2WB1 — a JDM STI A-Line, which is the 5EAT car. The
ECU on the other end of its CAN bus is **AZ1G502L**: 2009 JDM Impreza STI,
automatic, SH7058, 1 MB. Same processor family as the Denso TCU, so the SH-2E
language, the disassembly scripts and the emulation harness all apply unchanged.

Verified on load: the string `AZ1G502L` sits at 0x2004 exactly where the
definition says, the reset vector is 0x00000C0C and the initial stack pointer is
0xFFFFBFA0 — the same RAM ceiling as the TCU.

## Inputs are fetched, not redistributed

Neither the ROM nor the RomRaider definition file is ours, so neither is committed
here. Both are fetched into a working directory outside the repository, which the
tools locate via `ECU_WORK_DIR` or one of the mirrored defaults:

    mkdir -p "$ECU_WORK_DIR/rom"
    curl -sL -o "$ECU_WORK_DIR/ecu_defs.xml" \
      https://raw.githubusercontent.com/TD-D/SubaruDefs/master/RomRaider/ecu/metric/ecu_defs.xml
    curl -sL -o "$ECU_WORK_DIR/rom/AZ1G502L.bin" \
      https://raw.githubusercontent.com/bludgod/RomRaider/master/JDM/Impreza/AZ1G502L-2009-JDM-Subaru-Impreza-STI-AT.hex

The definitions are the RomRaider project's work. The ROM collection is a
community one. The `.hex` extension is a misnomer — the files are raw 1 MB
images, not Intel HEX.

## The tools

| | |
|---|---|
| `list_ecus.py` | every calibration in the definition file, filterable by transmission, year, model |
| `ecu_def.py` | resolve one calibration through its base chain and print table shapes and addresses |
| `find_table.py` | which calibrations actually locate a given table — a table can be well defined and still unusable for a particular ROM |
| `read_table.py` | read a table out of a ROM; also the `load_table()` entry point everything else uses |
| `torque.py` | torque from pedal and engine speed, and the torque column for the vehicle logs |

## Two things worth knowing before trusting the output

**The definition is split in half.** A base entry carries every table's shape —
type, axes, scaling, units — and each calibration overrides only the addresses,
because the same table lives somewhere different in every ROM. Read one half alone
and you get either what a table means or where it is, never both. `AZ1G502L`
overrides 297 tables.

**The axis endianness in the definitions is wrong for these ROMs.** They tag the
float axes little-endian while the ROM stores them big-endian like everything else
on an SH7058. Believing the tag is the dangerous kind of wrong: the table data
comes out perfect and only the axes turn to denormals near 1e-41, so the result
still prints and still looks like a table. `read_table.py` reads the declared
endianness, checks whether the values are ones a real axis could hold, and flips
if not.

## What it produced

`Requested Torque A (Accelerator Pedal) SI-DRIVE Intelligent` at 0xDDD54, a 15×16
grid of big-endian uint16 scaled by 0.0078125, on axes of pedal angle 0–100 % and
engine speed 800–6800 rpm. The three SI-DRIVE modes behave as documented:
Intelligent tapers from 261 Nm at 800 rpm down to 212 above 2800, while Sport and
Sport Sharp hold a flat 350 Nm from 2000 to 6000 rpm. At 30 % pedal and 3000 rpm
the modes read 155, 190 and 222.5 Nm.

Applied to the 568-row log, torque peaks at 350 Nm with 184 rows under load. At
the wide-open-throttle row — 100 % pedal, 5598 rpm — the frame reads byte 0 =
0x7E = 126 = 252 Nm, byte 1 = 0x9D = 157 on its own 1.6 Nm scale for the same
252 Nm, pedal 0xFE, engine speed bytes 0xDE 0x15 = 5598. The frame agrees with
itself on every field, which is the check that matters: bytes 0 and 1 are the same
torque on different scales, so copying one into the other — as an earlier version
did — understates maximum torque by a fifth and does it quietly.

Feed it in with:

    python torque.py --log --csv torque_from_log.csv
    python ../denso_make_profile.py --out drive.csv
