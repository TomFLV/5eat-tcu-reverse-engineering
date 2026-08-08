# Resuming the perturbation sweep

The sweep names calibration tables by changing them and watching what moves
(FINDINGS 85). It writes its results after every single run, so it can be stopped
at any point and picked up without losing work.

## Resume

```
set FIVEEAT_WORK=D:/5eat-work
python tools/denso_perturb.py --all --resume ^
    --json tools\denso_perturb_results.json
```

`--resume` reads the existing json and skips every table/condition pair already
recorded, so it starts where it stopped rather than at the beginning.

## What it is doing

185 shipped tables, each under four drives - cruise, acceleration, kickdown, and
one with the ATF hot - at two scale factors, doubling and halving. 1,480 runs at
roughly 15 seconds each, so about six hours from cold.

Four drives because a table read only when hot moves nothing on a drive that never
gets there, and that must read as "not exercised" rather than "no meaning". Two
factors because in a controller full of limits, doubling and halving are not
mirror images of each other.

## Reading it while it runs

```
python -c "import json;d=json.load(open('tools/denso_perturb_results.json'));print(sum(len(v.get('conditions',{})) for v in d.values()),'runs')"
```

or start the monitor again:

```
bash tools/bench/watch_perturb.sh
```

## When it finishes

Run it once more without `--resume` skipping anything - it will find every pair
already present and print the summary, which collapses the conditions into one
verdict per table and ranks names by how few tables move them. A name that most
tables move is a hub and not a finding; that filter is the point.
