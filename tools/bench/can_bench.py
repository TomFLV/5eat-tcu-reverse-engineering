#!/usr/bin/env python3
"""Transmit the mapped CAN frames at a real TCU, and watch what it says back.

The emulator produced a signal map by holding each frame byte at two values and
diffing whole RAM images (FINDINGS 77c). Every line of it is a claim about a real
controller that has never seen one. This sends the same frames at hardware.

    python3 tools/bench/can_bench.py --listen                # what is on the bus
    python3 tools/bench/can_bench.py --idle                  # a plausible idle
    python3 tools/bench/can_bench.py --sweep rpm             # ramp one signal
    python3 tools/bench/can_bench.py --gear-nibble           # settle the encoding

Requires the CANtact Pro attached to WSL - see attach-cantact.ps1 - and the
interface up:

    sudo ip link set can0 up type can bitrate 500000

WHAT IS BEING TESTED, and what would falsify it:

  Frames 0x231 and 0x410 appeared to carry the same three signals into the same
  three control-block slots. If that is right, either frame should move the same
  reported parameters. If only one does, the map found an artefact of the
  emulator's task ordering rather than a property of the firmware.

  Gear appeared to sit in the HIGH NIBBLE of frame 0x491 byte 2: 0x40 gave gear 4,
  0x80 gave gear 8, and a plain 5 gave nothing. --gear-nibble sends 0x10 through
  0x60 and the reported gear should follow 1 through 6.

Nothing here reads the TCU's own parameters - that is the Select Monitor's job over
the OpenPort, on the Windows side. Run both and compare.
"""

import argparse
import sys
import time

try:
    import can
except ImportError:
    sys.exit("python-can is not installed - run tools/bench/setup-wsl-can.sh")

# Frame layouts as the emulator mapped them. Byte positions are from the signal
# map; the SCALING of most of these is not established, so the values below are
# raw bytes rather than engineering units, and are labelled as such.
FRAMES = {
    0x410: "engine data: byte 4 -> control block 8E48, byte 5 -> Engine Speed, "
           "byte 6 -> 8E52",
    0x231: "engine data, alternate layout: byte 0 -> Engine Speed, "
           "byte 4 -> Accelerator Pedal Travel",
    0x412: "pedal and road speed: byte 0 -> Accelerator Pedal Travel, "
           "bytes 3 and 4 reach the widest set of control-block slots",
    0x491: "gear: byte 2, in the HIGH NIBBLE",
}


def bus(channel, bitrate):
    try:
        return can.Bus(interface="socketcan", channel=channel, bitrate=bitrate)
    except Exception as e:
        sys.exit("cannot open %s: %s\n"
                 "Is the adapter attached and the link up?\n"
                 "  sudo ip link set %s up type can bitrate %d"
                 % (channel, e, channel, bitrate))


def frame(can_id, data):
    return can.Message(arbitration_id=can_id, data=bytes(data),
                       is_extended_id=False)


def idle_set(rpm=0x50, pedal=0x00, speed=0x00, gear=1, torque=0x10):
    """One plausible standing-still state, in every frame that carries it."""
    f410 = [0] * 8
    f410[4], f410[5], f410[6] = torque, rpm, 0
    f231 = [0] * 8
    f231[0], f231[4] = rpm, pedal
    f412 = [0] * 8
    f412[0], f412[3], f412[4] = pedal, speed, speed
    f491 = [0] * 8
    f491[2] = (gear & 0xF) << 4        # high nibble - see the module docstring
    return [frame(0x410, f410), frame(0x231, f231),
            frame(0x412, f412), frame(0x491, f491)]


def send_for(b, msgs, seconds, period=0.02):
    """Hold a state on the bus. A controller ignores a frame it sees once."""
    end = time.time() + seconds
    n = 0
    while time.time() < end:
        for m in msgs:
            b.send(m)
            n += 1
        time.sleep(period)
    return n


def _main(opened):
    # python-can warns "SocketcanBus was not properly shut down" if the interface
    # is left open. Harmless, but a warning nobody can act on is noise on a bench
    # where a real warning matters.
    def opened_bus(channel, bitrate):
        b = bus(channel, bitrate)
        opened.append(b)
        return b

    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="can0")
    ap.add_argument("--bitrate", type=int, default=500000)
    ap.add_argument("--listen", action="store_true",
                    help="receive only, and report what the controller sends")
    ap.add_argument("--idle", action="store_true")
    ap.add_argument("--sweep", choices=["rpm", "pedal", "speed", "torque"])
    ap.add_argument("--gear-nibble", action="store_true")
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    if args.listen:
        b = opened_bus(args.channel, args.bitrate)
        print("listening on %s for %.0fs - anything the TCU transmits\n"
              % (args.channel, args.seconds))
        seen = {}
        end = time.time() + args.seconds
        while time.time() < end:
            m = b.recv(timeout=0.5)
            if m is None:
                continue
            e = seen.setdefault(m.arbitration_id, {"n": 0, "last": None})
            e["n"] += 1
            e["last"] = bytes(m.data)
        if not seen:
            print("  nothing received. The controller may be silent until it sees")
            print("  traffic, the bitrate may be wrong, or termination may be")
            print("  missing - a CAN bus needs 120 ohms at each end.")
            return 1
        print("  %-6s %6s  %s" % ("id", "count", "last payload"))
        for cid in sorted(seen):
            print("  0x%03X  %6d  %s"
                  % (cid, seen[cid]["n"], seen[cid]["last"].hex(" ")))
        return 0

    b = opened_bus(args.channel, args.bitrate)

    if args.idle:
        print("holding a standing-still state for %.0fs" % args.seconds)
        for cid, what in sorted(FRAMES.items()):
            print("  0x%03X  %s" % (cid, what))
        n = send_for(b, idle_set(), args.seconds)
        print("\n  %d frames sent" % n)
        return 0

    if args.gear_nibble:
        print("gear encoding: sending 1 to 6 in the HIGH nibble of 0x491 byte 2.")
        print("Read Gear Position on the Select Monitor as this runs - it should")
        print("follow 1 to 6. If it reads 0 throughout, the nibble is wrong.\n")
        for g in range(1, 7):
            print("  gear %d  -> byte 2 = 0x%02X" % (g, (g & 0xF) << 4))
            send_for(b, idle_set(gear=g), 2.0)
        return 0

    if args.sweep:
        print("sweeping %s over %.0fs, in every frame that carries it\n"
              % (args.sweep, args.seconds))
        steps = 16
        for i in range(steps):
            v = int(i * 255 / (steps - 1))
            kw = {args.sweep: v}
            print("  %s = %3d" % (args.sweep, v))
            send_for(b, idle_set(**kw), args.seconds / steps)
        return 0

    ap.print_help()
    return 1


def main():
    """Run, and close whatever was opened however this ends.

    python-can warns "SocketcanBus was not properly shut down" if an interface is
    left open. Harmless in itself, but a warning nobody can act on is noise on a
    bench where a real warning matters.
    """
    opened = []
    try:
        return _main(opened)
    finally:
        for b in opened:
            try:
                b.shutdown()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
