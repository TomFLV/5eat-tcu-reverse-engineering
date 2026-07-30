RomRaider for the Subaru 5EAT TCU — standalone Windows build
============================================================

A build of RomRaider that opens 5EAT transmission ROMs out of the box, with the
definition for eleven firmwares already bundled and a Java runtime included so
nothing needs installing.

Download the ZIP from the [Releases page](../../releases), extract the whole
folder, and double-click **RomRaider.vbs**.


Running it
----------

    RomRaider.vbs         normal launch, no console window   <- use this
    RomRaider.bat         same, but briefly flashes a console
    RomRaider-debug.bat   keeps a console and writes console.log

Then `File -> Open` and pick a 5EAT `.bin`. RomRaider matches the calibration ID
at `0x8008` and picks the right definition itself — there is nothing to choose.
If your ROM is not one of the eleven it will decline to load tables, which is the
safety mechanism working rather than a bug.

Do not move `RomRaider.jar` out of the folder; it needs `jre`, `lib`, `i18n` and
`definitions` beside it.


Where the interesting tables are
--------------------------------

Every value is in real units. Nothing is displayed as a raw integer where a
confirmed conversion exists.

| Category | What it holds |
|---|---|
| Transmission - Shift Schedule | Eight shift curves, in km/h against % accelerator |
| Transmission - Line Pressure | Line pressure targets in kPa against engine RPM |
| Transmission - Engine Speed Curves | Six curves on a confirmed RPM breakpoint |
| Transmission - Shift Correction | Per-gear signed correction curves |
| Transmission - Sensor Calibration | ATF temperature sensor linearisation |
| Transmission - Temperature Curves | Thresholds in °F |

The record-array curves appear as pairs — for example `Shift 1-2 Upshift Curve -
km/h` and `Shift 1-2 Upshift Curve - % pedal`. That is deliberate: a single grid
holding both quantities could not carry a unit, so each is a separate table and
they line up row for row. Vertex `3a` of one is the same point on the curve as
vertex `3a` of the other.

Some tables are still labelled `raw`. Those are the ones whose physical quantity
has not been established from the firmware. An honest `raw` is better than a
plausible unit that turns out to be wrong.


RPM range
---------

Engine speed is stored as a `uint16` scaled by 1/8, so **8191 RPM is the ceiling**
these tables can represent. There is real headroom for a built engine — the stock
calibration already parks a breakpoint at 8160 RPM — but a target above 8191 RPM
cannot be expressed and will clip.


Checksum — read this before flashing
------------------------------------

RomRaider **cannot** fix this ROM's checksum. Its checksum support is hardcoded
per ECU family in Java and does not cover this M32R TCU. There is deliberately no
"Checksum Fix" table, because shipping one would imply it works.

After saving a modified ROM, correct the checksum with the project tool:

    python tools/checksum.py --fix your_edited.bin

An image with a bad checksum may be rejected outright, or may run unpredictably.


What this is and is not for
---------------------------

This edits a ROM file you already have. You cannot read or write the car through
it — RomRaider's logging and flashing target Subaru engine ECUs on a different CPU
family. To get an image off a TCU or back onto one, use
[FastECU](https://github.com/miikasyvanen/FastECU).


Theme
-----

Dark by default. To change it, edit the launcher:

    -Dromraider.theme=light     light theme
    -Dromraider.theme=system    the original Windows look


If something goes wrong
-----------------------

Run `RomRaider-debug.bat`. It writes `console.log` next to the executable, which
matters because RomRaider raises some errors through dialog boxes that never reach
its own log — `console.log` is the only place those stack traces appear.

Its own log is at `%USERPROFILE%\.RomRaider\rr_system.log`.


Building it yourself
--------------------

    ./build-standalone.sh

Checks out upstream RomRaider at the pinned revision, applies the two patches in
`patches/`, builds, and assembles the folder including the runtime. Requires git,
a JDK 21+, ant, curl and unzip.


What is modified versus upstream
--------------------------------

Built from [RomRaider](https://github.com/RomRaider/RomRaider) (GPL-2.0) at
revision `dafe0c3`, with two patches:

`patches/jdk21-build.patch` — makes it compile on a current JDK:

* source and target raised to 21; upstream targets Java 1.6, which no modern
  javac accepts, and the bootclasspath reference was removed
* a Nashorn script whose only job was to uppercase a month in the version string
  was replaced with a plain Ant `tstamp` — Nashorn was removed in Java 15

`patches/romraider-5eat.patch` — the interface:

* look and feel prefers FlatLaf, selectable with `-Dromraider.theme`. The Windows
  look and feel is bitmap-scaled on this machine and renders blurred
* text antialiasing hints set at startup; the fuzziness was grayscale AA, not
  DPI scaling
* `RomCellRenderer` derives its colours and fonts from the active look and feel
  instead of hardcoded `Color.WHITE`, `(220,220,255)` and `Tahoma 11`, so the
  ROM tree is legible on a dark theme
* FlatLaf provides its own window decorations, so LAF-decorated frames are
  disabled when it is active

No change was needed to load the 5EAT tables themselves. An earlier assumption
that RomRaider would need forking for that was wrong — the 3D tables simply
needed static X and Y axis children, because `Table3D.calcCellRanges()`
dereferences the axis cells and throws on an axis-less table.

RomRaider is GPL-2.0; see `license.txt`. The bundled runtime is
[Eclipse Temurin](https://adoptium.net/) (GPLv2 with Classpath Exception),
redistributed unmodified. Neither is my work.
