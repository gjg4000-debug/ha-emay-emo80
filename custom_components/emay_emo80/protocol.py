"""MrdStoreBlue (EMO-80) frame protocol.

Protocol reconstructed for interoperability from the EMAY Android app
(com.fei.bluelibrary.mrd.MrdStoreBlue + u0 + z5).

Frame: E2 cmd dir len_hi len_lo [payload N] E3 xor
  dir = 0x2F request / 0x4F response
  xor = XOR(cmd, dir, len_hi, len_lo, payload...)  (E2/E3 not included)
"""

from __future__ import annotations

from collections.abc import Callable

REQ = 0x2F
RESP = 0x4F

CMD_RESET = 0xA1
CMD_SET_TIME = 0xA2
CMD_GET_TIME = 0xA3
CMD_GET_BATTERY = 0xA4
CMD_GET_DEVICE_INFO = 0xA5
CMD_GET_STORAGE = 0xA6
CMD_GET_SPO2_INFO = 0xA7
CMD_GET_ONE_DATA = 0xA8
CMD_DELETE_ALL = 0xA9


def build(cmd: int, direction: int, payload: bytes | list[int] = b"") -> bytes:
    """Build one E2..E3 frame."""
    payload = bytes(payload)
    length = len(payload)
    body = bytes([cmd, direction, (length >> 8) & 0xFF, length & 0xFF]) + payload
    checksum = 0
    for b in body:
        checksum ^= b
    return bytes([0xE2]) + body + bytes([0xE3, checksum])


def cmd_reset() -> bytes:
    return build(CMD_RESET, REQ)


def cmd_get_time() -> bytes:
    return build(CMD_GET_TIME, REQ)


def cmd_get_battery() -> bytes:
    return build(CMD_GET_BATTERY, REQ)


def cmd_get_device_info() -> bytes:
    return build(CMD_GET_DEVICE_INFO, REQ)


def cmd_get_storage() -> bytes:
    return build(CMD_GET_STORAGE, REQ)


def cmd_get_spo2_info() -> bytes:
    return build(CMD_GET_SPO2_INFO, REQ, [0, 0, 0])


def cmd_delete_all() -> bytes:
    return build(CMD_DELETE_ALL, REQ, [0, 0, 0, 0])


def to_bcd(v: int) -> int:
    return ((v // 10) << 4) | (v % 10)


def cmd_set_time(yy: int, mo: int, dd: int, hh: int, mi: int, ss: int) -> bytes:
    return build(
        CMD_SET_TIME,
        REQ,
        [to_bcd(yy), to_bcd(mo), to_bcd(dd), to_bcd(hh), to_bcd(mi), to_bcd(ss)],
    )


def cmd_get_one_data(serial: int, pkg: int, size: int) -> bytes:
    return build(
        CMD_GET_ONE_DATA,
        REQ,
        [
            3,
            (serial >> 8) & 0xFF,
            serial & 0xFF,
            (pkg >> 8) & 0xFF,
            pkg & 0xFF,
            (size >> 8) & 0xFF,
            size & 0xFF,
        ],
    )


def ack(cmd: int, resp: int = 0) -> bytes:
    return build(cmd, RESP, [resp])


def from_bcd(b: int) -> int:
    return ((b >> 4) * 10) + (b & 0x0F)


class Reassembler:
    """Feeds raw ff02 notification bytes and yields complete validated frames.

    Direct port of emay_mrd::Reassembler.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes, on_frame: Callable[[bytes], None]) -> None:
        self._buf.extend(data)
        while True:
            start = self._buf.find(0xE2)
            if start == -1:
                self._buf.clear()
                return
            if start > 0:
                del self._buf[:start]
            if len(self._buf) < 5:
                return  # need E2 cmd dir len_hi len_lo
            lenp = (self._buf[3] << 8) | self._buf[4]
            total = 5 + lenp + 2  # header(5) + payload + E3 + xor
            if len(self._buf) < total:
                return  # wait for more
            if self._buf[5 + lenp] != 0xE3:
                del self._buf[0:1]
                continue
            checksum = 0
            for i in range(1, 5 + lenp):
                checksum ^= self._buf[i]
            if checksum != self._buf[total - 1]:
                del self._buf[0:1]
                continue
            frame = bytes(self._buf[:total])
            del self._buf[:total]
            on_frame(frame)
