"""SSM2 protocol codec for the Tribeca 5EAT TCU — transport-agnostic.

The firmware receive path validates a 3-byte header (0x80, 0x18, 0xF0): a request
to the TCU is  `0x80  0x18(dest=TCU)  0xF0(src=tool)  <len>  <data...>  <cksum>`,
and the TCU answers with dest/src swapped (0x80 0xF0 0x18 ...). Checksum is the
low byte of the sum of every byte from the 0x80 header through the last data byte.

Commands (response code = request + 0x40), all confirmed against the decoded
firmware SSM dispatcher (FUN_00025062 / FUN_00026814):
  0xA0 read block     -> 0xE0      0xA8 read addresses -> 0xE8
  0xB0 write block    -> 0xF0      0xB8 write address  -> 0xF8
  0xBF ECU init/ID    -> 0xFF

This module only builds/parses byte strings; a Transport actually moves them.
"""
from __future__ import annotations
from typing import Iterable, List

HDR = 0x80
TCU = 0x18          # destination address of the transmission ECU
TOOL = 0xF0         # our (diagnostic tool) address

CMD_READ_BLOCK = 0xA0
CMD_READ_ADDRS = 0xA8
CMD_WRITE_BLOCK = 0xB0
CMD_WRITE_ADDR = 0xB8
CMD_INIT = 0xBF
RESP = 0x40         # response code = request code + 0x40

# response-mode byte for read commands: 0x00 = single response (what a poller
# wants), 0x01 = respond continuously. We re-request each cycle, so single.
SINGLE = 0x00


class SsmError(Exception):
    pass


def checksum(frame: bytes) -> int:
    return sum(frame) & 0xFF


def _packet(dest: int, src: int, data: bytes) -> bytes:
    body = bytes([HDR, dest, src, len(data)]) + data
    return body + bytes([checksum(body)])


def _addr3(addr: int) -> bytes:
    return bytes([(addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])


def build_read_addresses(addrs: Iterable[int]) -> bytes:
    """0xA8: read one byte from each of the listed addresses; response returns the
    bytes in the same order. Ideal for a scattered watch-list."""
    data = bytes([CMD_READ_ADDRS, SINGLE])
    n = 0
    for a in addrs:
        data += _addr3(a)
        n += 1
    if n == 0:
        raise SsmError("read_addresses: empty address list")
    return _packet(TCU, TOOL, data)


def build_read_block(addr: int, count: int) -> bytes:
    """0xA0: read `count` consecutive bytes starting at addr (count 1..256)."""
    if not 1 <= count <= 256:
        raise SsmError("read_block: count must be 1..256")
    data = bytes([CMD_READ_BLOCK, SINGLE]) + _addr3(addr) + bytes([count - 1])
    return _packet(TCU, TOOL, data)


def build_write_addr(addr: int, value: int) -> bytes:
    """0xB8: write a single byte (a live poke)."""
    data = bytes([CMD_WRITE_ADDR]) + _addr3(addr) + bytes([value & 0xFF])
    return _packet(TCU, TOOL, data)


def build_write_block(addr: int, values: bytes) -> bytes:
    """0xB0: write a run of bytes starting at addr."""
    if not 1 <= len(values) <= 255:
        raise SsmError("write_block: 1..255 bytes")
    data = bytes([CMD_WRITE_BLOCK]) + _addr3(addr) + bytes(values)
    return _packet(TCU, TOOL, data)


def build_init() -> bytes:
    """0xBF: fetch SSM id + ROM id + capability bits (handshake / liveness probe)."""
    return _packet(TCU, TOOL, bytes([CMD_INIT]))


def find_response(buf: bytes, req_cmd: int) -> bytes:
    """Scan `buf` for the first well-formed response frame addressed to the tool
    (0x80 0xF0 0x18 ...) carrying the expected response code, and return its data
    payload (the bytes after the response-code byte, checksum stripped). Raises if
    no complete valid frame is present yet — the caller reads more and retries."""
    want = (req_cmd + RESP) & 0xFF
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != HDR:
            i += 1
            continue
        if i + 4 > n:
            break
        dest, src, ln = buf[i + 1], buf[i + 2], buf[i + 3]
        end = i + 4 + ln          # index of checksum byte
        if end >= n:
            break                 # frame not fully received yet
        frame = buf[i:i + 4 + ln]
        if checksum(frame) != buf[end]:
            i += 1
            continue
        if dest == TOOL and src == TCU and ln >= 1 and frame[4] == want:
            return frame[5:]      # payload after the response-code byte
        i = end + 1
    raise SsmError("no complete SSM response for cmd 0x%02X in %d bytes" % (req_cmd, n))


def parse_init(payload: bytes) -> dict:
    """Decode a 0xFF init payload into ssm_id / rom_id (hex) + raw capability bytes."""
    ssm_id = payload[0:3].hex().upper()
    rom_id = payload[3:8].hex().upper()
    return {"ssm_id": ssm_id, "rom_id": rom_id, "caps": payload[8:].hex().upper()}
