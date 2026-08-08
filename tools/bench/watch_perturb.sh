#!/bin/bash
# Report progress and new findings from the perturbation sweep.
#
# The sweep writes its json after every condition, so progress is readable while it
# runs. A line is emitted only when the number of tables with a NAMED effect
# changes: progress on its own is not worth a notification, a new name is.
#
# Paths are Windows-side deliberately. This runs under Git Bash, not WSL, so
# /mnt/... does not exist here - the first version of this script used WSL paths
# and died with "No such file or directory" before emitting anything.
set -u
J="C:/Users/Tom/Desktop/5eat-tcu-reverse-engineering/tools/denso_perturb_results.json"
PY=$(command -v python || command -v python3)
last=-1
while true; do
    if [ -f "$J" ]; then
        line=$("$PY" - "$J" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("0 0 0"); raise SystemExit
conds = sum(len(v.get("conditions", {})) for v in d.values())
named = sum(1 for v in d.values()
            if any(c["named"] for c in v.get("conditions", {}).values()))
print(len(d), conds, named)
PYEOF
)
        set -- $line
        tables=${1:-0}; conds=${2:-0}; named=${3:-0}
        if [ "$named" != "$last" ]; then
            echo "sweep $(( conds * 100 / 1480 ))% - $conds/1480 runs, $tables tables, $named with a named effect"
            last=$named
        fi
        [ "$conds" -ge 1480 ] && { echo "sweep complete: $conds runs"; exit 0; }
    fi
    sleep 240
done
