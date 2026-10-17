"""EMO-80 (MrdStoreBlue) full SpO2 download engine.

Awaits each response directly, so the whole transfer is one linear sequence.

Wire protocol (from EMAY APK decompile: MrdStoreBlue + z5 + i4 + j4 + u0):
  A2 set time (BCD yy mo dd hh mi ss); A7 get info list {0,0,0}
  A8 get one data block; A9 delete all {0,0,0,0}
  List/data page: request -> response(source) -> if endFlag!=1 ACK {0} -> next

Auto-upload only (no auto-delete). Every
listed session is pulled on every run; use Emay80Client.delete_all() separately
if you want to clear the device's storage.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from statistics import median
import time

from bleak import BleakClient
from bleak.exc import BleakError

from . import protocol as p
from .const import NOTIFY_CHAR_UUID, WRITE_CHAR_UUID

_LOGGER = logging.getLogger(__name__)

MAX_RESENDS = 2


@dataclass
class SessionHeader:
    serial: int
    duration_s: int
    datetime_str: str


@dataclass
class SessionResult:
    serial: int
    datetime_str: str
    duration_s: int
    spo2_points: list[float] = field(default_factory=list)
    bpm_points: list[float] = field(default_factory=list)
    last_spo2: float = 0.0
    last_bpm: float = 0.0
    raw_len: int = 0


@dataclass
class DownloadReport:
    sessions: list[SessionResult] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)

    @property
    def log(self) -> str:
        return "\n".join(self.log_lines)

    @property
    def summary(self) -> str:
        lines = ["# serial datetime dur_s"]
        for s in self.sessions:
            lines.append(f"{s.serial} {s.datetime_str} {s.duration_s}")
        return "\n".join(lines)

    @property
    def last_spo2(self) -> float:
        for s in reversed(self.sessions):
            if s.last_spo2:
                return s.last_spo2
        return 0.0

    @property
    def last_bpm(self) -> float:
        for s in reversed(self.sessions):
            if s.last_bpm:
                return s.last_bpm
        return 0.0


def _median_nonzero(values: list[float]) -> float:
    nonzero = [v for v in values if v > 0]
    if not nonzero:
        return 0.0
    return float(median(nonzero))


class TimeoutOrBadResponse(Exception):
    """Raised internally when a request exhausts its retries."""


class Emay80Client:
    """Wraps a connected BleakClient with the MrdStoreBlue request/response protocol."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client
        self._reassembler = p.Reassembler()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._log: list[str] = []

    def _logln(self, msg: str) -> None:
        _LOGGER.debug("emay_emo80: %s", msg)
        self._log.append(msg)

    async def start(self) -> None:
        await self._client.start_notify(NOTIFY_CHAR_UUID, self._on_notify)

    async def stop(self) -> None:
        try:
            await self._client.stop_notify(NOTIFY_CHAR_UUID)
        except (BleakError, EOFError, OSError):
            pass

    def _on_notify(self, _handle: int, data: bytearray) -> None:
        self._reassembler.feed(bytes(data), self._queue.put_nowait)

    async def _request(
        self,
        frame: bytes,
        expect_cmd: int,
        timeout_s: float,
        retries: int = MAX_RESENDS,
    ) -> bytes:
        """Write a frame and wait for a matching-cmd response, resending on timeout."""
        attempt = 0
        while True:
            await self._client.write_gatt_char(WRITE_CHAR_UUID, frame)
            try:
                deadline = time.monotonic() + timeout_s
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    resp = await asyncio.wait_for(self._queue.get(), timeout=remaining)
                    if len(resp) >= 2 and resp[1] == expect_cmd:
                        return resp
                    # Not the frame we're waiting on; keep waiting for the real one.
            except TimeoutError:
                if attempt >= retries:
                    self._logln(f"timeout, giving up on cmd 0x{expect_cmd:02X}")
                    raise TimeoutOrBadResponse(expect_cmd)
                attempt += 1
                self._logln(f"timeout, resend {attempt} (cmd 0x{expect_cmd:02X})")

    async def set_time(self) -> bool:
        now = time.localtime()
        frame = p.cmd_set_time(now.tm_year % 100, now.tm_mon, now.tm_mday,
                                now.tm_hour, now.tm_min, now.tm_sec)
        try:
            await self._request(frame, p.CMD_SET_TIME, timeout_s=1.5)
            self._logln("time set")
            return True
        except TimeoutOrBadResponse:
            self._logln("set-time unacked, continuing anyway")
            return False

    @staticmethod
    def _parse_session_header(frame: bytes) -> tuple[SessionHeader | None, bool]:
        lenp = (frame[3] << 8) | frame[4]
        payload = frame[5:]
        if lenp < 16:
            return None, True  # end_flag treated as true, matching the C++ fallback
        end_flag = payload[1]
        serial = (payload[2] << 8) | payload[3]
        duration = (
            (payload[11] << 24) | (payload[12] << 16) | (payload[13] << 8) | payload[14]
        )
        dt = (
            f"{2000 + p.from_bcd(payload[5]):04d}-{p.from_bcd(payload[6]):02d}-"
            f"{p.from_bcd(payload[7]):02d} {p.from_bcd(payload[8]):02d}:"
            f"{p.from_bcd(payload[9]):02d}:{p.from_bcd(payload[10]):02d}"
        )
        return SessionHeader(serial=serial, duration_s=duration, datetime_str=dt), end_flag == 1

    async def list_sessions(self) -> list[SessionHeader]:
        sessions: list[SessionHeader] = []
        frame = p.cmd_get_spo2_info()
        timeout_s = 1.5
        while True:
            try:
                resp = await self._request(frame, p.CMD_GET_SPO2_INFO, timeout_s=timeout_s)
            except TimeoutOrBadResponse:
                self._logln("list ended by timeout")
                break
            header, is_end = self._parse_session_header(resp)
            if header is not None:
                sessions.append(header)
                self._logln(
                    f"session serial={header.serial} {header.datetime_str} "
                    f"dur={header.duration_s}s"
                )
            if is_end:
                break
            frame = p.build(p.CMD_GET_SPO2_INFO, p.RESP, [0])  # ACK -> next session
            timeout_s = 1.2
        return sessions

    async def download_session(self, serial: int) -> bytes:
        raw = bytearray()
        pkg = 1
        frame = p.cmd_get_one_data(serial, pkg, 200)
        stalls = 0
        while True:
            try:
                resp = await self._request(
                    frame, p.CMD_GET_ONE_DATA, timeout_s=1.5 if pkg == 1 else 1.2
                )
            except TimeoutOrBadResponse:
                break
            lenp = (resp[3] << 8) | resp[4]
            payload = resp[5:]
            if lenp < 4:
                break
            end_flag = payload[1]
            rpkg = (payload[2] << 8) | payload[3]
            if rpkg != pkg:
                # The device sometimes stops honoring our per-package ACK
                # gating and free-runs ahead on its own (observed jumping
                # from pkg 34 straight to 67 and climbing indefinitely).
                # Resync to whatever it reports rather than resending our
                # stale ACK forever -- data for any skipped packages in
                # between is unrecoverable, but this lets the transfer
                # actually finish instead of looping until timeout/forever.
                self._logln(f"pkg mismatch got={rpkg} want={pkg} -- resyncing")
                stalls += 1
                if stalls > 20:
                    self._logln("too many pkg mismatches, aborting session")
                    break
                pkg = rpkg
            else:
                stalls = 0
            raw.extend(payload[4:lenp])
            self._logln(f"pkg {pkg} got {lenp - 4}B end={end_flag}")
            if end_flag == 1:
                break
            pkg += 1
            frame = p.ack(p.CMD_GET_ONE_DATA, 0)  # ACK -> next package
        return bytes(raw)

    async def delete_all(self) -> bool:
        try:
            await self._request(p.cmd_delete_all(), p.CMD_DELETE_ALL, timeout_s=2.0)
            self._logln("delete-all acked")
            return True
        except TimeoutOrBadResponse:
            self._logln("delete-all unacked")
            return False

    @staticmethod
    def _decode_session(header: SessionHeader, raw: bytes) -> SessionResult:
        spo2_points: list[float] = []
        bpm_points: list[float] = []
        last_spo2 = 0.0
        last_bpm = 0.0
        for i, v in enumerate(raw):
            if i % 2 == 0:
                if v < 20 or v > 100:
                    v = 0
                spo2_points.append(float(v))
                if v:
                    last_spo2 = v
            else:
                if v == 255:
                    v = 0
                bpm_points.append(float(v))
                if v:
                    last_bpm = v
        med = _median_nonzero(spo2_points)
        if med:
            last_spo2 = med
        med = _median_nonzero(bpm_points)
        if med:
            last_bpm = med
        return SessionResult(
            serial=header.serial,
            datetime_str=header.datetime_str,
            duration_s=header.duration_s,
            spo2_points=spo2_points,
            bpm_points=bpm_points,
            last_spo2=last_spo2,
            last_bpm=last_bpm,
            raw_len=len(raw),
        )

    async def run_full_download(self) -> DownloadReport:
        self._log.clear()
        self._logln("== EMO-80 download start ==")
        await self.set_time()
        headers = await self.list_sessions()
        report = DownloadReport()
        for header in headers:
            raw = await self.download_session(header.serial)
            if not raw:
                self._logln(f"session serial={header.serial} no data")
                continue
            result = self._decode_session(header, raw)
            self._logln(
                f"session serial={header.serial} downloaded {result.raw_len}B -> "
                f"{len(result.spo2_points)} spo2 pts, {len(result.bpm_points)} bpm pts"
            )
            report.sessions.append(result)
        if headers:
            # Clear the device's storage now that everything has been pulled,
            # so future downloads don't have to re-fetch already-seen sessions
            # (each redownload was getting slower as history piled up).
            await self.delete_all()
        self._logln("== download complete ==")
        report.log_lines = list(self._log)
        return report
