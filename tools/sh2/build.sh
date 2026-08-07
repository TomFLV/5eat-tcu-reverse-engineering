#!/bin/bash
set -e
# The work directory holds the build. FIVEEAT_WORK chooses it; the default sits
# beside the clone, so this script works from a fresh checkout rather than only
# on the machine it was written on.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="${FIVEEAT_WORK:-$(dirname "$REPO")/work}"
mkdir -p "$WORK/sh2"
cp "$HERE/sh2.c" "$WORK/sh2/sh2.c"
cd "$WORK/sh2"
gcc -O2 -Wall -Wextra -o sh2 sh2.c
echo "built: $(ls -la sh2 | awk '{print $5}') bytes"
