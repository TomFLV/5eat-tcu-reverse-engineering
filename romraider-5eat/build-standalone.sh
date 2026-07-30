#!/usr/bin/env bash
# Build the standalone Windows package from source.
#
# Produces RomRaider-5EAT/ containing a bundled Java runtime, so the end user
# installs nothing. This is the script that made the release ZIP; run it if you
# would rather build from source than trust a binary, or to rebuild against a
# newer upstream.
#
# Requires: git, a JDK 21+ (for javac and jlink), ant, curl, unzip.
#
#   ./build-standalone.sh [output-dir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
OUT="${1:-$REPO/build/RomRaider-5EAT}"
WORK="${TMPDIR:-/tmp}/rr5eat-build"

# Pinned so the patch applies cleanly. Upstream moves and the patch touches
# build.xml, ECUExec.java, LookAndFeelManager.java and RomCellRenderer.java -
# bump this deliberately, and re-check the patch, rather than tracking master.
UPSTREAM_URL="https://github.com/RomRaider/RomRaider.git"
UPSTREAM_REV="dafe0c36c1a68efadbeedb2825f3855463fdbc35"

# Temurin 21 JRE for Windows x64. The bundled runtime is what makes the package
# standalone; it is Eclipse's build, redistributed unmodified under GPLv2 with
# Classpath Exception.
JRE_URL="https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse"

say() { printf '\n=== %s\n' "$*"; }

command -v ant >/dev/null || { echo "ant not found" >&2; exit 1; }
command -v javac >/dev/null || { echo "javac not found - need a JDK 21+" >&2; exit 1; }

say "checking out upstream RomRaider at $UPSTREAM_REV"
rm -rf "$WORK"; mkdir -p "$WORK"
git -C "$WORK" init -q src
git -C "$WORK/src" remote add origin "$UPSTREAM_URL"
git -C "$WORK/src" fetch -q --depth 1 origin "$UPSTREAM_REV"
git -C "$WORK/src" checkout -q FETCH_HEAD

say "applying 5EAT patches"
# jdk21-build.patch makes it compile at all on a modern JDK; upstream targets
# Java 1.6, which no current javac accepts. romraider-5eat.patch is the UI work
# (FlatLaf, theme-aware cell rendering, text antialiasing).
git -C "$WORK/src" apply --verbose "$HERE/patches/jdk21-build.patch"
git -C "$WORK/src" apply --verbose "$HERE/patches/romraider-5eat.patch"

say "building"
( cd "$WORK/src" && ant clean jar )

say "assembling $OUT"
rm -rf "$OUT"; mkdir -p "$OUT"
cp "$WORK/src/dist/RomRaider.jar" "$OUT/"
cp -r "$WORK/src/lib/common" "$OUT/lib"
cp -r "$WORK/src/src/main/resources/i18n" "$OUT/i18n"
cp "$WORK/src/LICENSE" "$OUT/license.txt" 2>/dev/null \
  || cp "$WORK/src/license.txt" "$OUT/license.txt"
cp "$HERE/launchers/"*.vbs "$HERE/launchers/"*.bat "$OUT/"
cp "$HERE/launchers/log4j.properties" "$OUT/lib/"
mkdir -p "$OUT/definitions"
cp "$REPO/definitions/5eat_tcu_romraider_defs.xml" "$OUT/definitions/"
cp "$HERE/README.md" "$OUT/README.txt"

say "fetching Temurin 21 JRE"
curl -fSL "$JRE_URL" -o "$WORK/jre.zip"
unzip -q "$WORK/jre.zip" -d "$WORK/jre"
mv "$WORK"/jre/*/ "$OUT/jre"

say "done"
du -sh "$OUT"
cat <<EOF

Built: $OUT
Run it with RomRaider.vbs on Windows. Nothing needs installing.

To make the release archive:
  cd "$(dirname "$OUT")" && zip -qr RomRaider-5EAT-windows-x64.zip RomRaider-5EAT
EOF
