RomRaider TCU — standalone Windows build
========================================

A build of RomRaider that edits Subaru 5EAT transmission ROMs out of the box.
Definitions for sixteen firmwares, all sixteen ROM images, and a Java runtime are
all bundled, so nothing needs installing and nothing needs configuring.

Download the ZIP from the [Releases page](../../releases), extract the whole
folder, and run **RomRaider-TCU.exe**.


Getting started
---------------

1. Run `RomRaider-TCU.exe`.
2. `File -> Open`, and pick any `.bin` from the `app\roms` folder — or your own.
3. Expand the tree on the left.

The right definition is selected automatically from the calibration ID at
`0x8008`. There is nothing to choose and no path to set up. If a ROM is not one
of the sixteen, it will decline to load tables — that is the safety mechanism
working, not a bug.


The shift map
-------------

**Transmission - Shift Schedule → Shift Map**

All eight shift points in one table, in the form a five-speed automatic is
normally calibrated: vehicle speed across accelerator pedal angle, one row per
shift event.

Read a cell as *this shift happens at this road speed when the pedal is here*.
Raise a value to delay the shift, lower it to bring the shift on earlier. The four
upshift rows come first, then the four downshifts — the gap between an upshift and
its matching downshift is the hysteresis that stops the transmission hunting
between two gears, so move the pair together unless you mean to change it.

Every value is vehicle speed in km/h, confirmed against the factory shift chart.

Cells showing `-` are not editable. Each curve is stored as its own polyline with
its own breakpoints, and this table lines all eight up on the shared pedal axis; a
`-` marks a pedal position where that particular curve has no vertex in the ROM,
so there is no byte to change. Leaving it blank is deliberate — the alternative
was inventing a number.


Other tables worth knowing
--------------------------

Every value is in real units wherever a conversion has actually been established.

| Category | What it holds |
|---|---|
| Transmission - Shift Schedule | The shift map, above |
| Transmission - Line Pressure | Line pressure targets in **kPa** against engine RPM |
| Transmission - Engine Speed Curves | Six curves on a confirmed RPM breakpoint |
| Transmission - Shift Correction | Per-gear signed correction curves |
| Transmission - Sensor Calibration | ATF temperature sensor linearisation |
| Transmission - Temperature Curves | Thresholds in °F |

Some tables are still labelled `raw`. Those are the ones whose physical quantity
has not been established from the firmware. An honest `raw` is better than a
plausible unit that turns out to be wrong, because a wrong unit reads as
confirmed.


RPM range
---------

Engine speed is stored as a `uint16` scaled by 1/8, so **8191 RPM is the ceiling**
these tables can represent. There is real headroom for a built engine — the stock
calibration already parks a breakpoint at 8160 RPM — but a target above 8191 RPM
cannot be expressed and will clip.


Checksum
--------

**Handled for you.** These ROMs carry **two** checksums and the TCU checks both on
start-up. This build implements both as a RomRaider plugin, so saving a ROM corrects
them automatically. There is no extra step, and no "Checksum Fix" table to tick.

The first is a 32-bit big-endian two's-complement additive sum, stored twice at
`0x8000` and `0x8004`. The region it covers is **not** the same in every image —
some use `0x60000`, some the whole file — so it is detected per ROM rather than
assumed, because assuming either one produces a confidently wrong answer on half the
family.

The second is a balance at `0x8020`, covering everything from there to the end of the
payload. Three firmwares require the full 32-bit sum to reach `0x5AA5A55A`; the rest
test only its low half against `0x5AA5` and keep their balance in the halfword at
`0x8022`. Both forms are detected per image.

**Releases up to 1.4.2 maintained only the first**, so a ROM edited and saved with one
of those fails its own integrity check. Re-save with 1.4.3 or later.

Verified byte-for-byte against the project's Python implementation on all sixteen
images, and end to end: each ROM is edited through the real editor write path, saved,
and checked by an independent implementation of the firmware's own rule.

`app\checksum.py` is still bundled if you want to check an image outside the editor:

    python app\checksum.py your_rom.bin

An image with a bad checksum may be rejected outright, or may run unpredictably.


What this is and is not for
---------------------------

This edits a ROM file you already have. You cannot read or write the car through
it — RomRaider's logging and flashing target Subaru engine ECUs on a different CPU
family. To get an image off a TCU or back onto one, use
[FastECU](https://github.com/miikasyvanen/FastECU).


Batch use
---------

    RomRaider-TCU.exe --cli <command> <definition.xml> <rom.bin> [...]

Runs headless and prints one JSON object; the exit status is 0 only when the answer
is yes. Commands are `info`, `tables`, `dump`, `checksum`, `set` and `selftest`.

    RomRaider-TCU.exe --cli checksum defs.xml rom.bin --fix fixed.bin
    RomRaider-TCU.exe --cli selftest defs.xml roms\*.bin

This drives the same parser and the same save path as the window does, so it is a
check of the application and not of a reimplementation of it.


Theme
-----

Dark by default. Pass `-Dromraider.theme=light` or `=system` to change it.


If something goes wrong
----------------------

The log is at `%USERPROFILE%\.RomRaider\rr_system.log`.


Building it yourself
--------------------

    ./build-standalone.sh

Checks out upstream RomRaider at the pinned revision, applies the patches in
`patches/`, builds the jar, merges the translation bundles into it and stages
everything the application ships with — definitions, ROM images, the checksum
tool. Requires git, a JDK 21+, ant, curl and unzip.

What that leaves you is the jpackage *input* directory, not the finished
application. The released package is a jpackage app-image — `RomRaider-TCU.exe`
beside a bundled runtime — and jpackage only produces a Windows image when run on
Windows, so the script prints the exact `jpackage` command to run there rather
than pretending to do it.

Verify the finished archive, not the build tree: extract `RomRaider.jar` back out
of the zip and check the translation bundles are in it. A jar that was correct in
the build tree and wrong in the zip shipped once as 1.4.1 and would not start.


What is modified versus upstream
--------------------------------

Built from [RomRaider](https://github.com/RomRaider/RomRaider) (GPL-2.0) at
revision `dafe0c3`. Two patches, both in `patches/`.

**`jdk21-build.patch`** — makes it compile on a current JDK. Source and target
raised to 21 (upstream targets Java 1.6, which no modern javac accepts), and a
Nashorn script whose only job was to uppercase a month in the version string
replaced with a plain Ant `tstamp`, Nashorn having been removed in Java 15.

**`romraider-5eat.patch`** — the functional changes:

* **Sparse tables.** `Table3D` can map every cell to an explicit address, with
  cells that have no storage rendered read-only. Without this the shift schedule
  could only be eight separate tables: the curves sit at eight addresses with
  different lengths, and no curve uses every pedal position.
* **Striding axes.** `skipCells` moved from `Table3D` up to `Table`, so an *axis*
  can stride. A record interleaves two quantities, so reading one as the axis and
  the other as the data needs both to step over the other.
* **First run is not an error.** A missing settings file was reported through a
  modal dialog titled "Error" that blocked the main window, so on a machine that
  had never run RomRaider it looked like the application failed to start.
* **Definitions found automatically.** The definition path was only read from
  `settings.xml` as an absolute path, so a shipped package found nothing on
  anyone else's machine. It now looks beside the application first.
* **Interface.** FlatLaf look and feel selectable with `-Dromraider.theme`, text
  antialiasing hints set at startup, and `RomCellRenderer` deriving colours and
  fonts from the active look and feel instead of hardcoded `Color.WHITE` and
  `Tahoma 11`, so the ROM tree is legible on a dark theme.

RomRaider is GPL-2.0; see `license.txt`. The bundled runtime is
[Eclipse Temurin](https://adoptium.net/) 21, redistributed unmodified (GPLv2 with
Classpath Exception). The ROM images in `app\roms` were collected and shared by
the community — see the [project README](../#credits) for provenance. None of
those three are my work.
