# Headless RomRaider definition verifier

Loads a definition and a ROM using **RomRaider's own parser**, then reports what
it actually produced. Nothing here re-implements the schema — if RomRaider would
silently skip a table, mis-read an address, or fail to match a calibration ID,
that shows up here exactly as it would in the GUI.

This exists because everything else in the project verifies addresses against the
*ROM*. This verifies the definition against *RomRaider*, which is a different
question and was previously untested.

## Why it matters

An earlier version of this project shipped tables with a fabricated `Z Axis`
element. Every address was correct and every self-check passed — but RomRaider
silently ignored the tables, because that element does not exist in its schema.
Only loading it in RomRaider revealed it. This tool makes that check automatic.

## Building

Needs a JDK **with** AWT (not `-headless`), plus `xvfb` — RomRaider queries the
screen size while loading settings, so it cannot run truly headless.

```bash
sudo apt-get install -y openjdk-21-jdk xvfb
mkdir -p lib && cp /path/to/RomRaider/RomRaider.jar lib/
cp /path/to/RomRaider/lib/common/*.jar lib/
cp -r /path/to/RomRaider/i18n .
javac -cp 'lib/*' -d out DefCheck.java
```

A `settings.xml` must exist at `~/.RomRaider/settings.xml`. Without it,
`SettingsManager.load()` opens a modal dialog and the process hangs forever with
no output — copy one from a working RomRaider install.

## Running

```bash
xvfb-run -a java -cp "out:i18n:lib/*" DefCheck definitions.xml rom.bin
xvfb-run -a java -cp "out:i18n:lib/*" DefCheck definitions.xml rom.bin --tables
./runall.sh          # every ROM in the project
```

Output:

```
91D1206000_5EAT.bin    11 rom blocks  match=SUBARU_5EAT_91D1206000  tables= 81  faulty=0
```

- **rom blocks** — how many `<rom>` definitions the file contains
- **match** — which one RomRaider selected for this image, by calibration ID.
  `NO MATCH` means the ROM would open with no tables at all
- **tables** — how many RomRaider actually built, after inheritance
- **faulty** — tables RomRaider parsed but rejected. Should always be 0

## Verify3D — checking values, not just structure

`DefCheck` proves RomRaider *builds* the tables. It does not prove the values are
read correctly, because `unmarshallXMLDefinition` only creates table shells —
`Rom.populateTables()` is what reads the bytes.

`Verify3D` calls `populateTables()` and then compares **every 3D cell** against the
raw big-endian uint16 at the address the definition declares:

```bash
xvfb-run -a java -cp "out:i18n:lib/*" Verify3D definitions.xml rom.bin
./runall3d.sh
```

It also calls `SettingsManager.setTesting(true)`, which makes `populateTables()`
print stack traces instead of opening a modal "error loading table" dialog — under
xvfb that dialog blocks forever with no output, which is genuinely hard to diagnose.

### This caught a real bug

The 3D tables originally had **no X/Y axis children**. `Table3D.calcCellRanges()`
dereferences the axis DataCells, so `populateTable()` threw a NullPointerException
for every one of them, and RomRaider showed *"There was an error loading table"* —
exactly the error rimwall reported on 0.8.2.

`DefCheck` alone did **not** catch it: the tables unmarshalled fine and reported
`faulty=0`, because nothing had tried to read data yet.

The fix was `Static X Axis` / `Static Y Axis` children with literal `<data>`
labels, which RomRaider already supports. **No RomRaider modification was needed.**

## Current result

All eleven firmwares match their own `<rom>` block, and every 3D cell in every
firmware matches the ROM — **12,536 cells, zero mismatches**.
