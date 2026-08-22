"""Phase-1 live-monitor tests: SSM codec round-trip, mock TCU read/poke, and the
LiveMonitor snapshot — all without hardware."""
import time
from tcu_sim import ssm, tcu_map
from tcu_sim.simulator import Simulator
from tcu_sim.ssm_transport import MockTransport
from tcu_sim.live import LiveMonitor

fails = 0
def check(name, cond, detail=""):
    global fails
    print(("[PASS] " if cond else "[FAIL] ") + name + (("  << "+detail) if detail and not cond else ""))
    if not cond: fails += 1

# 1) checksum + frame shape
req = ssm.build_read_addresses([0x8047F3, 0x8050EA])
check("read-addr frame header", req[:3] == bytes([0x80, 0x18, 0xF0]))
check("read-addr checksum", ssm.checksum(req[:-1]) == req[-1])
check("write-addr frame", ssm.build_write_addr(0x804D6B, 0x16)[4] == ssm.CMD_WRITE_ADDR)

# 2) mock transport read/parse round-trip
sim = Simulator(); sim.can_ok = False
sim.vehicle.s.selector = "P"
mt = MockTransport(sim)
payload = mt.query(req, ssm.CMD_READ_ADDRS)
check("mock returns one byte per address", len(payload) == 2, "got %d" % len(payload))
check("range byte = 0x84 in Park", payload[0] == 0x84, "got 0x%02X" % payload[0])
check("mbox comm flag clear (no P1601)", payload[1] == 0x00, "got 0x%02X" % payload[1])

# 3) init handshake
initp = mt.query(ssm.build_init(), ssm.CMD_INIT)
check("init parses rom id", ssm.parse_init(initp)["rom_id"] == "4D42353030")

# 4) poke round-trips through mock RAM
mt.query(ssm.build_write_addr(0x804D6B, 0x18), ssm.CMD_WRITE_ADDR)
back = mt.query(ssm.build_read_addresses([0x804D6B]), ssm.CMD_READ_ADDRS)
check("poke sticks in mock RAM", back[0] == 0x18, "got 0x%02X" % back[0])

# 5) address-map decoders
mem = {a: 0 for a in tcu_map.all_byte_addrs()}
mem[0x8050EA] = 0x80                        # memory-box comm fault bit
row = tcu_map.decode(next(e for e in tcu_map.WATCH if e["addr"] == 0x8050EA), mem)
check("mbox fault decodes to label", "COMM FAULT" in row["display"], row["display"])
mem2 = {a: 0 for a in tcu_map.all_byte_addrs()}
mem2[0x804DAE] = 0x55; mem2[0x804DAF] = 0x55
sig = tcu_map.decode(next(e for e in tcu_map.WATCH if e["addr"] == 0x804DAE), mem2)
check("mbox signature reads 0x5555", sig["display"] == "0x5555", sig["display"])

# 6) LiveMonitor end-to-end against the mock
lm = LiveMonitor(sim)
r = lm.connect({"kind": "mock"})
check("live connect ok", r.get("ok") is True, str(r))
time.sleep(0.4)
snap = lm.snapshot()
check("snapshot connected", snap["connected"] is True)
check("snapshot has groups", len(snap["groups"]) >= 5, "%d groups" % len(snap["groups"]))
check("snapshot polling", snap["polls"] > 0, "polls=%d" % snap["polls"])
names = {row["name"] for g in snap["groups"] for row in g["rows"]}
check("watch covers memory box", "Mbox signature" in names)
# live poke via the monitor
lm.poke(0x8050EA, 0x80)
time.sleep(0.4)
snap2 = lm.snapshot()
mbox = next(row for g in snap2["groups"] for row in g["rows"] if row["addr"] == 0x8050EA)
check("live poke raises P1601 in snapshot", "COMM FAULT" in mbox["display"], mbox["display"])
lm.disconnect()
check("disconnect clears connected", lm.connected is False)

print("\n%d/%d checks passed" % (16 - fails, 16))
raise SystemExit(1 if fails else 0)
