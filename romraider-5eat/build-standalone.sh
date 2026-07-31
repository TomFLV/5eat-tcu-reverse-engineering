#!/usr/bin/env bash
# Build the 5EAT RomRaider application from source.
#
# Checks out the pinned upstream RomRaider, applies this project's patches, builds
# the jar, and stages everything the application ships with - definitions, ROM
# images, the checksum tool, the translation bundles merged into the jar.
#
# The result is the jpackage INPUT directory. Turning it into the released
# RomRaider-TCU.exe with a bundled runtime is a jpackage step that only produces a
# Windows image when run on Windows; the exact command is printed at the end.
#
# Requires: git, a JDK 21+, ant, curl, unzip, zip.
#
#   ./build-standalone.sh [staging-dir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
OUT="${1:-$REPO/build/app-input}"
WORK="${TMPDIR:-/tmp}/rr5eat-build"
APP_VERSION="${APP_VERSION:-1.4.3}"

# Pinned so the patch applies cleanly. Upstream moves and the patch touches
# build.xml, ECUExec.java, LookAndFeelManager.java and RomCellRenderer.java -
# bump this deliberately, and re-check the patch, rather than tracking master.
UPSTREAM_URL="https://github.com/RomRaider/RomRaider.git"
UPSTREAM_REV="dafe0c36c1a68efadbeedb2825f3855463fdbc35"

# The bundled runtime is what makes the package standalone. jpackage builds it from
# the JDK running the packaging step, so there is no separate JRE download; use a
# Temurin 21 JDK on the Windows side to get the runtime this project has shipped.

say() { printf '\n=== %s\n' "$*"; }

command -v ant >/dev/null || { echo "ant not found" >&2; exit 1; }
command -v javac >/dev/null || { echo "javac not found - need a JDK 21+" >&2; exit 1; }

say "checking out upstream RomRaider at $UPSTREAM_REV"
rm -rf "$WORK"; mkdir -p "$WORK"
git -C "$WORK" init -q src
git -C "$WORK/src" remote add origin "$UPSTREAM_URL"
git -C "$WORK/src" fetch -q --depth 1 origin "$UPSTREAM_REV"
git -C "$WORK/src" checkout -q FETCH_HEAD

say "fetching FlatLaf"
# Upstream does not ship FlatLaf, and the look-and-feel patch needs it. Pinned so a
# rebuild is reproducible rather than tracking whatever is current.
FLATLAF_VER=3.4.1
curl -fSL "https://repo1.maven.org/maven2/com/formdev/flatlaf/${FLATLAF_VER}/flatlaf-${FLATLAF_VER}.jar" \
     -o "$WORK/src/lib/common/flatlaf.jar"

say "applying 5EAT patches"
# jdk21-build.patch makes it compile at all on a modern JDK; upstream targets
# Java 1.6, which no current javac accepts. romraider-5eat.patch is the UI work
# (FlatLaf, theme-aware cell rendering, text antialiasing).
git -C "$WORK/src" apply --verbose "$HERE/patches/jdk21-build.patch"
git -C "$WORK/src" apply --verbose "$HERE/patches/romraider-5eat.patch"

say "building"
# There is no "jar" target: upstream builds per-platform, and the Windows jar is
# what this package ships. It lands in build/windows/lib, not in dist.
( cd "$WORK/src" && ant clean build-windows )

JAR="$WORK/src/build/windows/lib/RomRaider.jar"
[ -f "$JAR" ] || { echo "ant did not produce $JAR" >&2; exit 1; }

say "assembling $OUT"
rm -rf "$OUT"; mkdir -p "$OUT"
cp "$JAR" "$OUT/"
# Keep the lib/common/ nesting. `cp -r src/lib/common "$OUT/lib"` onto a directory
# that does not exist yet flattens it to lib/*.jar, which still runs but does not
# match the layout every released package has used.
mkdir -p "$OUT/lib"
cp -r "$WORK/src/lib/common" "$OUT/lib/common"
# Merge the translation bundles INTO the jar rather than shipping them beside it.
# They live at the repo root, not under src/main/resources, and ResourceBundle looks
# for them on the CLASSPATH - a loose directory that is not on the classpath gives
# "Can't find bundle for base name com.romraider.ECUExec" at startup and nothing
# else useful. Merging also survives `ant clean`, which rebuilds the jar without
# them; the check below fails the build rather than shipping one that is missing.
( cd "$WORK/src/i18n" && jar uf "$OUT/RomRaider.jar" . )

BUNDLES=$(unzip -l "$OUT/RomRaider.jar" | grep -c '\.properties$' || true)
if [ "$BUNDLES" -lt 50 ]; then
    echo "ERROR: only $BUNDLES translation bundles in the jar, expected about 78." >&2
    echo "Shipping this would fail at startup with a missing-bundle error." >&2
    exit 1
fi
say "$BUNDLES translation bundles merged into the jar"
cp "$WORK/src/LICENSE" "$OUT/license.txt" 2>/dev/null \
  || cp "$WORK/src/license.txt" "$OUT/license.txt"

cp "$HERE/log4j.properties" "$OUT/"
mkdir -p "$OUT/definitions"
# BOTH families. The 5EAT was built with a Hitachi M32R and a Denso SH705x, and
# they need separate definitions; shipping only the first leaves every Denso car
# unsupported with no indication why.
cp "$REPO/definitions/5eat_tcu_romraider_defs.xml" "$OUT/definitions/"
cp "$REPO/definitions/5eat_tcu_denso_romraider_defs.xml" "$OUT/definitions/"
cp "$REPO/README.md" "$OUT/README.txt"

# The ROM images and the checksum tool ship with the application so it is usable
# the moment it is extracted. The images are other people's dumps - roms/README.txt
# records that, and the project README carries the full provenance.
mkdir -p "$OUT/roms"
cp "$REPO"/rom/*.bin "$OUT/roms/"
[ -d "$REPO/rom-denso" ] && cp "$REPO"/rom-denso/*.bin "$OUT/roms/"
cp "$REPO/tools/checksum.py" "$OUT/"

say "staged application input at $OUT"
du -sh "$OUT"

cat <<EOF

Staged: $OUT

That directory is the jpackage INPUT, not the finished application. The released
package is a jpackage app-image - RomRaider-TCU.exe next to a bundled runtime -
and jpackage produces a Windows image only when run on Windows, so that step
cannot happen here. From Windows, with a JDK 21+ on PATH:

  jpackage --type app-image --name RomRaider-TCU \\
      --input "$OUT" --main-jar RomRaider.jar \\
      --main-class com.romraider.ECUExec \\
      --icon romraider-5eat/romraider-ico.ico \\
      --app-version $APP_VERSION --dest build \\
      --add-launcher tcu-cli=romraider-5eat/tcu-cli.properties \\
      --java-options -Xmx1024M \\
      --java-options -Dawt.useSystemAAFontSettings=lcd \\
      --java-options -Dswing.aatext=true \\
      --java-options -Dromraider.theme=dark \\
      --java-options -Dsun.java2d.uiScale.enabled=true \\
      --java-options -Dflatlaf.useWindowDecorations=true \\
      --java-options -Dflatlaf.menuBarEmbedded=true \\
      --java-options -Dlog4j.configuration=file:'\$APPDIR'/log4j.properties

Then archive it:
  cd build && zip -qr RomRaider-TCU-windows-x64.zip RomRaider-TCU

Verify the archive rather than the build tree - extract RomRaider.jar back OUT of
the finished zip and check it has the translation bundles. Shipping a jar that was
correct in the build tree and wrong in the zip is a mistake this project has
already made once.
EOF
