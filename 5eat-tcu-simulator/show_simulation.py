"""Show a full data simulation: run one scenario and print every signal through
the whole drive, the shift events, CAN snapshots, and the summary."""
import json
from tcu_sim.simulator import run_headless
from tcu_sim import romdata
from tcu_sim.messages import decode_frame_display, FRAME_INFO

rom = next(r["id"] for r in romdata.list_roms() if r["valid_5eat"])
r = run_headless("errand", power="400 hp", rom=rom, sample_hz=10)
tel, ev, s = r["telemetry"], r["events"], r["summary"]

print("=" * 92)
print("FULL DATA SIMULATION  —  Errand (drive to the store)")
print("=" * 92)
print("firmware   : %s" % r["rom_name"])
print("gear ratios: %s" % r["gear_ratios"])
print("power      : %s" % r["power"])
print("duration   : %.1fs   shifts: %d   max speed: %d km/h   DTCs: %s"
      % (s["duration"], s["shifts"], s["max_speed"], s["dtcs"] or "none"))

print("\n--- DRIVE TIMELINE (every ~2s) ------------------------------------------------------------")
print("  t   phase              spd  rpm  gr  ped brk | turb  out slip line  atf1 atf2 lock  solenoids")
last = None
for row in tel[::20]:                      # ~2s at 10 Hz
    sol = "+".join(k for k, v in (row["solenoids"] or {}).items() if v >= 100)
    print("%4.0f  %-17s %4.0f %4d  %-2s %3d %3d | %4d %4d %4d %4d  %3.0f  %3.0f  %-3s  %s"
          % (row["t"], row["phase"][:17], row["speed"], row["rpm"], row["gear"],
             round(row["throttle"]*100), round(row["brake"]*100),
             row["turbine"], row["output"], row["slip"], row["line_kpa"],
             row["atf1"], row["atf2"], "yes" if row["lockup"] else "-", sol))

print("\n--- SHIFT EVENTS -------------------------------------------------------------------------")
for e in ev:
    print("  t=%5.1fs  %-16s  %s-shift %s  @ %d km/h  %d rpm"
          % (e["t"], e["phase"][:16], e["dir"], e["shift"], e["speed"], e["rpm"]))

print("\n--- LIVE CAN BUS at 3 moments (launch / cruise / hard-brake) -----------------------------")
picks = [("launch", tel[15]), ("cruise", tel[len(tel)//2]), ("brake", tel[-8])]
for label, row in picks:
    print("  [%s]  t=%.0fs  speed=%.0f gear=%s" % (label, row["t"], row["speed"], row["gear"]))
    allf = {**row["can"]["rx"], **row["can"]["tx"]}
    for cid in sorted(allf):
        b = allf[cid]
        spaced = " ".join(b[i:i+2] for i in range(0, len(b), 2))
        name = FRAME_INFO.get(cid, ("", ""))[0]
        print("      0x%-4s %-24s %-24s %s" % (cid, name[:24], spaced, decode_frame_display(cid, b)))

print("\n--- SUMMARY ------------------------------------------------------------------------------")
print("  %s" % json.dumps(s))
print("  log file: %s   (%d telemetry rows, full CAN capture per row)" % (r["log_file"], len(tel)))
