"""SSM transports: something that moves an SSM request to the TCU and returns the
response payload. Two real-world ones plus a mock so the whole pipeline (and the
dashboard panel) runs with no hardware.

  MockTransport          - a fake TCU whose RAM is synthesized from the running
                           Simulator; honors pokes. Exercises the real ssm codec.
  TactrixSerialTransport - the Tactrix OpenPort 2.0 (or any FTDI K-line cable)
                           presented as a COM port, SSM2 at 4800 8N1.

The serial layer is implemented to the documented SSM-over-K-line framing but is
marked BENCH-VERIFY: confirm the OpenPort's mode (serial VCP vs J2534) and timing
against the real TCU before trusting it. The J2534 path is stubbed with pointers.
"""
from __future__ import annotations
import time
from typing import Dict, Optional

from . import ssm


class Transport:
    kind = "base"

    def open(self) -> None: ...
    def close(self) -> None: ...

    def query(self, request: bytes, req_cmd: int, timeout: float = 0.6) -> bytes:
        """Send an SSM request frame; return the response payload (post-command
        bytes). Raise ssm.SsmError / IOError on failure."""
        raise NotImplementedError

    def describe(self) -> str:
        return self.kind


# --------------------------------------------------------------------------- #
# Mock TCU — RAM synthesized from the live Simulator state                     #
# --------------------------------------------------------------------------- #
class MockTransport(Transport):
    kind = "mock"

    def __init__(self, sim):
        self.sim = sim
        self._ram: Dict[int, int] = {}
        self._pokes: Dict[int, int] = {}     # sticky user writes win over synth

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    # --- fake memory ------------------------------------------------------- #
    def _put16(self, a: int, v: int) -> None:
        v &= 0xFFFF
        self._ram[a] = (v >> 8) & 0xFF
        self._ram[a + 1] = v & 0xFF

    def _synthesize(self) -> None:
        s = self.sim.vehicle.s
        RANGE = {"P": 0x84, "R": 0x94, "N": 0xA4, "D": 0xC4, "M": 0xC4}
        self._ram[0x8047F3] = RANGE.get(s.selector, 0xC4)
        self._ram[0x804955] = 1 if s.selector == "P" else 0
        g = s.tcu_current_gear
        self._ram[0x8050F8] = g if g >= 1 else 0
        self._put16(0x80468C, int(max(0, s.turbine_rpm)))
        self._put16(0x80468E, int(max(0, s.output_rpm)))
        self._put16(0x8047C6, int(max(0, min(0xFFFF, s.engine_rpm))))
        # analog shadows: raw counts that track the modeled temps/voltage
        self._put16(0x804C2E, int(s.atf_temp1 * 10) & 0xFFFF)
        self._put16(0x804C32, int(s.atf_temp2 * 10) & 0xFFFF)
        self._put16(0x804C34, 138)                     # ~13.8 V -> raw-ish
        self._ram[0x804813] = int(max(0, min(255, s.atf_temp1 + 50)))
        self._ram[0x804816] = int(max(0, min(255, s.atf_temp1 + 50)))
        sol = s.solenoids or {}
        self._ram[0x80504C] = int(sol.get("PL", 0) * 2.55) & 0xFF
        self._ram[0x80505A] = int(sol.get("PL", 0) * 2.55) & 0xFF
        self._put16(0x804A9A, int(s.line_pressure_kpa) & 0xFFFF)
        self._put16(0x804A9C, int(s.line_pressure_kpa * 0.6) & 0xFFFF)
        # memory box: healthy read cycle
        self._ram[0x804D6B] = 0x16
        self._ram[0x804D6C] = 0
        self._ram[0x804D6E] = int(time.perf_counter() * 20) % 0x3A
        self._put16(0x804D70, 0x5555)
        self._put16(0x804DAE, 0x5555)
        self._put16(0x8053C2, 0x0000)
        self._ram[0x8050EA] = 0x00                     # bit7 clear = no P1601
        # dtc flag bytes + counts
        for a in (0x804118, 0x80411C, 0x804120, 0x804124, 0x8050EB):
            self._ram[a] = 0x00
        ndtc = len(s.tcu_dtcs or [])
        self._ram[0x8052D8] = ndtc & 0xFF
        self._ram[0x8052D5] = ndtc & 0xFF
        self._ram[0x805261] = 0x80                     # power-ok
        # SSM-index reads (TCU translates idx<0x200): ATF as (temp+50) so x-50 recovers
        # it; DTC group current/confirmed bytes are 0 when healthy.
        self._ram[0x56] = int(max(0, min(255, s.atf_temp1 + 50)))
        self._ram[0x5A] = int(max(0, min(255, s.atf_temp2 + 50)))
        for idx in (0x9C, 0x9D, 0x9E, 0xA6, 0xF0, 0xF1, 0xF2, 0xF3, 0x123, 0x124, 0x125, 0x162,
                    0xBC, 0xBD, 0xBE, 0xC6, 0xF4, 0xF5, 0xF6, 0xF7, 0x12B, 0x12C, 0x12D, 0x167):
            self._ram[idx] = 0x00
        # user pokes override synthesized values
        self._ram.update(self._pokes)

    def _read(self, addr: int) -> int:
        return self._ram.get(addr, 0)

    def query(self, request: bytes, req_cmd: int, timeout: float = 0.6) -> bytes:
        self._synthesize()
        data = request[4:-1]                            # strip header(4) + cksum(1)
        if req_cmd == ssm.CMD_READ_ADDRS:
            addrs = data[2:]                            # skip cmd + response-mode
            payload = bytes(self._read((addrs[i] << 16) | (addrs[i + 1] << 8) | addrs[i + 2])
                            for i in range(0, len(addrs), 3))
        elif req_cmd == ssm.CMD_READ_BLOCK:
            a = (data[2] << 16) | (data[3] << 8) | data[4]
            count = data[5] + 1
            payload = bytes(self._read(a + i) for i in range(count))
        elif req_cmd in (ssm.CMD_WRITE_ADDR, ssm.CMD_WRITE_BLOCK):
            a = (data[1] << 16) | (data[2] << 8) | data[3]
            vals = data[4:]
            for i, v in enumerate(vals):
                self._pokes[a + i] = v
            payload = vals
        elif req_cmd == ssm.CMD_INIT:
            payload = bytes.fromhex("A21810") + bytes.fromhex("4D42353030") + b"\x00\x00\x00"
        else:
            raise ssm.SsmError("mock: unsupported cmd 0x%02X" % req_cmd)
        # assemble a real response frame and parse it back through the codec
        body = bytes([ssm.HDR, ssm.TOOL, ssm.TCU, len(payload) + 1,
                      (req_cmd + ssm.RESP) & 0xFF]) + payload
        frame = body + bytes([ssm.checksum(body)])
        return ssm.find_response(frame, req_cmd)


# --------------------------------------------------------------------------- #
# Tactrix OpenPort 2.0 / FTDI K-line — SSM2 over a serial COM port             #
# --------------------------------------------------------------------------- #
class TactrixSerialTransport(Transport):
    kind = "tactrix-serial"

    def __init__(self, port: str, baud: int = 4800):
        self.port = port
        self.baud = baud
        self._ser = None

    def open(self) -> None:
        import serial                                   # pyserial, imported lazily
        self._ser = serial.Serial(self.port, self.baud, bytesize=8,
                                  parity="N", stopbits=1, timeout=0.05)
        self._ser.reset_input_buffer()

    def close(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def query(self, request: bytes, req_cmd: int, timeout: float = 0.6) -> bytes:
        if self._ser is None:
            raise IOError("serial port not open")
        self._ser.reset_input_buffer()
        self._ser.write(request)
        self._ser.flush()
        buf = bytearray()
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            chunk = self._ser.read(64)
            if chunk:
                buf += chunk
                # the K-line echoes our own bytes back; find_response skips them
                try:
                    return ssm.find_response(bytes(buf), req_cmd)
                except ssm.SsmError:
                    continue
        raise ssm.SsmError("timeout waiting for TCU (got %d bytes)" % len(buf))

    def describe(self) -> str:
        return "%s @ %s %d" % (self.kind, self.port, self.baud)


class TactrixJ2534Transport(Transport):
    """OpenPort 2.0 via its J2534 DLL (op20pt32.dll), ISO9141 @ 4800. Preferred if
    the OP2.0 is NOT in serial mode. Left as a bench task: load the DLL with
    ctypes, PassThruOpen/Connect(ISO9141), then PassThruWriteMsgs/ReadMsgs with
    the raw SSM frame as the message body."""
    kind = "tactrix-j2534"

    def open(self) -> None:
        raise NotImplementedError(
            "J2534 path not wired yet — use TactrixSerialTransport, or implement "
            "op20pt32.dll ISO9141 here once the OP2.0 mode is confirmed on the bench.")


def make_transport(spec: dict, sim=None) -> Transport:
    """spec = {'kind': 'mock'|'tactrix-serial'|'tactrix-j2534', 'port':..,'baud':..}"""
    kind = spec.get("kind", "mock")
    if kind == "mock":
        return MockTransport(sim)
    if kind == "tactrix-serial":
        return TactrixSerialTransport(spec.get("port", "COM3"), int(spec.get("baud", 4800)))
    if kind == "tactrix-j2534":
        return TactrixJ2534Transport()
    raise ValueError("unknown transport kind %r" % kind)
