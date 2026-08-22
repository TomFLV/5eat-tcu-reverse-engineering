"""LLM-agent demo: drive the simulator entirely through its HTTP API (the way an
autonomous agent would), run + log the full battery, pull logs back, and analyze.
Proves the tool is AI-ready end-to-end. Run against the live server."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8642"


def get(p):
    return json.load(urllib.request.urlopen(BASE + p, timeout=120))


def post(p, body):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=180))


def fetch_log(name):
    return urllib.request.urlopen(BASE + "/api/log/" + name, timeout=60).read().decode().splitlines()


print("STEP 1 — discover the tool via API")
roms = get("/api/roms")["roms"]
runs = get("/api/runs")["runs"]
valid = [r for r in roms if r["valid_5eat"]]
rom = valid[0]["id"]
print("  %d ROMs (%d with real ratios), %d runs available" % (len(roms), len(valid), len(runs)))
print("  chosen firmware: %s" % next(r["name"] for r in roms if r["id"] == rom))

print("\nSTEP 2 — run + log the full battery through POST /api/headless")
POWERS = ["Stock ~250hp", "400 hp", "600 hp", "800 hp", "1000+ hp"]
named = [r["id"] for r in runs if not r["id"].startswith("drive_")]
drives = [r["id"] for r in runs if r["id"].startswith("drive_")]
data = []
t0 = time.time()
for run in named:
    for pw in POWERS:
        data.append(post("/api/headless", {"run_id": run, "power": pw, "rom": rom, "sample_hz": 5}))
for run in drives:
    for pw in ["Stock ~250hp", "800 hp"]:
        data.append(post("/api/headless", {"run_id": run, "power": pw, "rom": rom, "sample_hz": 2}))
print("  %d simulations dispatched + logged via API in %.1fs" % (len(data), time.time() - t0))

print("\nSTEP 3 — pull logs back via API")
logs = get("/api/logs")["logs"]
total_mb = sum(l["size"] for l in logs) / 1e6
print("  %d log files retrievable, %.1f MB total" % (len(logs), total_mb))

print("\nSTEP 4 — fetch + parse a log (verify it is full, machine-readable CAN data)")
lines = fetch_log(logs[0]["name"])
hdr = json.loads(lines[0])
mid = json.loads(lines[1 + len(lines) // 2])
print("  %s: %d rows" % (logs[0]["name"], len(lines) - 1))
print("  header keys: %s" % ", ".join(list(hdr.keys())))
print("  a mid row -> t=%.0fs %s spd=%.0f gear=%s rpm=%d atf=%.0f" %
      (mid["t"], mid["phase"], mid["speed"], mid["gear"], mid["rpm"], mid["atf1"]))
print("  CAN in row: rx410=%s tx420=%s tx422=%s" %
      (mid["can"]["rx"]["410"], mid["can"]["tx"]["420"], mid["can"]["tx"]["422"]))

print("\nSTEP 5 — LLM analysis of the dataset")
# power scaling from WOT runs
wot = {d["power"]: d["summary"]["t100"] for d in data if d["run"] == "wot_pull" and d["summary"]["t100"]}
print("  WOT 0-100 by power:", {k.split()[0]: v for k, v in wot.items()})
# ATF warm-up on the longest drive
d120 = next((d for d in data if d["run"] == "drive_120" and d["power"].startswith("Stock")), None)
if d120:
    ln = fetch_log(next(l["name"] for l in logs if l["name"].startswith("drive_120") and "Stock" in l["name"]))
    rows = [json.loads(x) for x in ln[1:]]
    print("  drive_120 ATF: %.0f C cold -> %.0f C warm (peak %.0f)" %
          (rows[0]["atf1"], rows[-1]["atf1"], max(r["atf1"] for r in rows)))
# anomaly scan across all summaries
anom = [(d["run"], d["power"].split()[0]) for d in data if d["summary"] and d["summary"].get("dtcs")]
print("  runs with unexpected DTCs:", anom or "none")
print("  every summary complete:", all(d["summary"] for d in data))
print("\nDONE — the full battery was run, logged, retrieved and analyzed entirely through the API.")
