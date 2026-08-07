#!/bin/bash
# Re-check every claim this repository makes that can be checked mechanically.
#
# CI runs most of these on every push, but CI checks a commit; this checks the
# working tree in front of you, which is the thing you are about to trust. It is
# also what a "verified on <date>" line has to be backed by, or the date is
# decoration.
#
#   bash tools/verify-all.sh
#
# Exits non-zero if anything fails, so it can gate a release.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# python3 on Linux, python on Windows under Git Bash. Hardcoding either makes the
# script report nine failures on the other, which looks exactly like nine broken
# checks.
#
# "command -v" is not enough on Windows: it finds the Microsoft Store stub named
# python3.exe, which exists, is on PATH, and does nothing but print an
# advertisement - so every check failed with a message about the Store. Test that
# the interpreter actually runs.
PY=""
for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import sys" >/dev/null 2>&1; then
        PY="$cand"; break
    fi
done
[ -n "$PY" ] || { echo "no working python interpreter found" >&2; exit 2; }
pass=0; fail=0
run() {
    local label="$1"; shift
    if out=$("$@" 2>&1); then
        printf "  %-44s ok\n" "$label"; pass=$((pass+1))
    else
        printf "  %-44s FAIL\n" "$label"; fail=$((fail+1))
        echo "$out" | tail -3 | sed 's/^/       /'
    fi
}

echo "=== definitions against the ROM images"
run "M32R: 5,911 address checks"        "$PY" tools/validate_xml_defs.py
run "Denso: 5,112 address checks"       "$PY" tools/validate_denso_defs.py
run "no table aliases its own cells"    "$PY" tools/check_table_aliasing.py

echo "=== checksums"
run "checksum round-trip self-tests"    "$PY" tools/test_checksum.py
printf "  %-44s " "all 16 M32R images verify"
f=0; for r in rom/*.bin; do "$PY" tools/checksum.py "$r" >/dev/null 2>&1 || f=1; done
[ $f -eq 0 ] && { echo "ok"; pass=$((pass+1)); } || { echo "FAIL"; fail=$((fail+1)); }

echo "=== generators reproduce what is committed"
"$PY" tools/generate_romraider_def.py >/dev/null 2>&1
"$PY" tools/generate_denso_def.py >/dev/null 2>&1
"$PY" tools/generate_logger_def.py >/dev/null 2>&1
printf "  %-44s " "definitions regenerate byte-identically"
git diff --quiet -- definitions/ && { echo "ok"; pass=$((pass+1)); } || { echo "FAIL"; fail=$((fail+1)); }

echo "=== other self-tests"
run "table offset derivation self-test"  "$PY" tools/find_rom_offsets.py --self-test
run "nothing left unscaled"              "$PY" tools/detect_fixed_point.py
run "DTC table found in all 9 Denso"     "$PY" tools/denso_find_dtc.py --min 10

echo "=== file integrity"
run "every tracked file matches its manifest"  "$PY" tools/write-manifests.py --check

echo "=== hygiene"
printf "  %-44s " "every tracked python parses"
bad=0
for f in $(git ls-files "*.py"); do
    "$PY" -c "import ast,io;ast.parse(io.open('$f',encoding='utf-8').read())" 2>/dev/null || bad=1
done
[ $bad -eq 0 ] && { echo "ok"; pass=$((pass+1)); } || { echo "FAIL"; fail=$((fail+1)); }

printf "  %-44s " "no machine-specific paths in docs"
if git ls-files "*.md" | xargs grep -l "Users.Tom\|/home/rust" >/dev/null 2>&1; then
    echo "FAIL"; fail=$((fail+1))
else echo "ok"; pass=$((pass+1)); fi

# This script names the patterns it searches for, so scanning every tracked file
# includes scanning this one, and it matches itself. Exclude it, and the manifests,
# which record hashes rather than content.
printf "  %-44s " "no secrets in tracked files"
if git ls-files | grep -v "verify-all.sh" | grep -v "MANIFEST.sha256"    | xargs grep -ilE "headwater|password *=|api[_-]?key" >/dev/null 2>&1; then
    echo "FAIL"; fail=$((fail+1))
else echo "ok"; pass=$((pass+1)); fi

echo
echo "$pass passed, $fail failed"
exit $fail
