# Building RomRaider on a modern JDK

RomRaider's `build.xml` targets Java 1.6, which no JDK since 11 can compile
(source levels below 8 were removed). [`jdk21-build.patch`](jdk21-build.patch)
makes it build on JDK 21.

```bash
git clone https://github.com/RomRaider/RomRaider.git
cd RomRaider
patch -p0 < /path/to/jdk21-build.patch
sudo apt-get install -y ant openjdk-21-jdk
ant build-linux      # or build-windows
# -> build/linux/lib/RomRaider.jar
```

Builds clean on JDK 21 — warnings only, no errors.

## What the patch changes

| Change | Why |
|---|---|
| `javac.source`/`javac.target` `1.6` → `21` | JDK 12+ dropped source 6; JDK 20 dropped 7 |
| `compiler="javac${javac.target}"` → `"modern"` | would resolve to `javac21`, an Ant adapter that doesn't exist |
| Removed `bootclasspath` | JDK 9+ rejects it for source levels above 8 |
| Replaced a Nashorn `<scriptdef>` with `<tstamp>` | Nashorn was removed in Java 15. It only uppercased the month in the version string, so no JS engine is warranted |

## Why this was needed here

Not for the definition — that turned out to be our bug, fixed with static axes
(see [`../romraider-cli/`](../romraider-cli/)). But building from source is what
made the failure visible: it exposed that `Table3D.calcCellRanges()` dereferences
the axis cells, which is why an axis-less 3D table throws and RomRaider reports
"There was an error loading table".

Reading the source beat guessing at the XML schema.

## Note on the installed 1.0.0 vs a source build

The upstream tree is version 1.1.0 (build 1227), newer than the 1.0.0 release.
The 3D tables in this project verify against **both**. rimwall reported 0.8.2
failing to load them, which the static-axis fix addresses.
