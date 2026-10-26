"""Serial client for an Every Day Calendar running firmware/caldera."""

from __future__ import annotations

import queue
import secrets
import threading
from collections import deque
from collections.abc import Iterator
from datetime import date
from typing import Protocol

import serial
from serial.tools import list_ports

from .protocol import (
    BAUD,
    MAX_LINE,
    VERSION,
    WINDOW,
    CalendarError,
    Event,
    Frame,
    Key,
    Mode,
    encode_brightness,
    encode_frame,
    encode_set,
    parse_banner,
    parse_event,
    parse_frame,
    parse_reply,
)

FTDI_FT232R = (0x0403, 0x6001)


class Stream(Protocol):
    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> int | None: ...
    def close(self) -> None: ...


def find_port() -> str:
    ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) == FTDI_FT232R]
    if len(ports) != 1:
        raise CalendarError(f"expected one FT232R port, found {ports or 'none'}")
    return ports[0]


class _Slot:
    """A sent line awaiting its OK/ERR reply."""

    __slots__ = ("line", "size", "wait", "expect", "reply", "done")

    def __init__(self, line: str, size: int, wait: bool, expect: str | None = None):
        self.line = line
        self.size = size
        self.wait = wait  # a caller will read the reply; otherwise ERR is deferred
        self.expect = expect  # if set, other replies before it are stale and dropped
        self.reply: str | None = None
        self.done = threading.Event()


class Calendar:
    """A connected calendar. Opening the port resets the board (~7s boot).

    Display changes (frames, pixels, brightness, mode, clear) are pipelined: they
    return once queued and their errors surface on a later call or flush().
    Reads and EEPROM operations wait for the device.
    """

    def __init__(
        self,
        port: str | None = None,
        *,
        stream: Stream | None = None,
        boot_timeout: float = 10.0,
        reply_timeout: float = 1.0,
    ):
        self.reply_timeout = reply_timeout
        self._stream = stream or serial.Serial(port or find_port(), BAUD, timeout=0.1)
        self._events: queue.Queue[Event] = queue.Queue()
        self._pending: deque[_Slot] = deque()
        self._inflight = 0
        self._error: CalendarError | None = None
        self._cv = threading.Condition()
        self._ready = threading.Event()
        self._version: int | None = None
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if not self._ready.wait(boot_timeout):
            self.close()
            raise TimeoutError(f"no READY banner within {boot_timeout}s")
        if self._version != VERSION:
            self.close()
            raise CalendarError(f"firmware speaks protocol {self._version}, expected {VERSION}")

    def __enter__(self) -> Calendar:
        return self

    def __exit__(self, exc_type: object, *exc: object) -> None:
        try:
            if exc_type is None:
                self.flush()
        finally:
            self.close()

    def close(self) -> None:
        self._closed.set()
        self._stream.close()
        self._reader.join(timeout=1)

    def _read_loop(self) -> None:
        buf = b""
        while not self._closed.is_set():
            try:
                chunk = self._stream.read(getattr(self._stream, "in_waiting", 0) or 1)
            except Exception:
                if self._closed.is_set():
                    return
                raise
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                self._dispatch(raw.decode("ascii", "replace").strip())

    def _dispatch(self, line: str) -> None:
        try:
            if line.startswith("READY"):
                self._version = parse_banner(line)
                self._ready.set()
            elif not self._ready.is_set():
                return
            elif line.startswith("EV "):
                self._events.put(parse_event(line))
            elif line.startswith(("OK", "ERR")):
                self._complete(line)
            # Anything else is firmware debug output.
        except (CalendarError, ValueError):
            pass  # a corrupted line must not kill the reader

    def _complete(self, line: str) -> None:
        with self._cv:
            if not self._pending:
                return  # reply to a command dropped by a resync
            slot = self._pending[0]
            if slot.expect is not None and line != slot.expect:
                return
            self._pending.popleft()
            self._inflight -= slot.size
            slot.reply = line
            if not slot.wait and line.startswith("ERR") and self._error is None:
                self._error = CalendarError(f"{slot.line!r}: {line[4:]}")
            self._cv.notify_all()
        slot.done.set()

    def _send(self, line: str, wait: bool, expect: str | None = None) -> _Slot:
        if len(line) > MAX_LINE or "\n" in line:
            raise ValueError(f"command too long or multi-line: {line!r}")
        data = line.encode("ascii") + b"\n"
        slot = _Slot(line, len(data), wait, expect)
        with self._cv:
            room = self._cv.wait_for(lambda: self._inflight + slot.size <= WINDOW, self.reply_timeout)
            if room:
                self._pending.append(slot)
                self._inflight += slot.size
                self._stream.write(data)
        if not room:
            self._resync()
            raise TimeoutError(f"device stopped acknowledging before {line!r}")
        return slot

    def _wait(self, slot: _Slot) -> str:
        if not slot.done.wait(self.reply_timeout):
            self._resync()
            raise TimeoutError(f"no reply to {slot.line!r}")
        return slot.reply or ""

    def _drop_pending(self) -> None:
        with self._cv:
            for slot in self._pending:
                slot.reply = "ERR dropped by resync"
                slot.done.set()
            self._pending.clear()
            self._inflight = 0

    def _resync(self) -> None:
        """Forget unanswered commands and wait for the device to echo a fresh token."""
        self._drop_pending()
        token = secrets.token_hex(4)
        slot = self._send(f"PING {token}", wait=True, expect=f"OK {token}")
        if not slot.done.wait(self.reply_timeout):
            self._drop_pending()
            raise TimeoutError("device unresponsive")

    def _raise_error(self) -> None:
        with self._cv:
            error, self._error = self._error, None
        if error is not None:
            raise error

    def send(self, line: str) -> None:
        """Queue one raw protocol line without waiting for its reply."""
        self._raise_error()
        self._send(line, wait=False)

    def command(self, line: str) -> str:
        """Send one raw protocol line and return the OK payload."""
        self._raise_error()
        reply = self._wait(self._send(line, wait=True))
        self._raise_error()  # from queued commands answered before this one
        return parse_reply(reply)

    def flush(self) -> None:
        """Wait until every queued command is acknowledged; raise any error among them."""
        with self._cv:
            drained = self._cv.wait_for(lambda: not self._pending, self.reply_timeout)
        if not drained:
            self._resync()
            raise TimeoutError("queued commands were not acknowledged")
        self._raise_error()

    def ping(self) -> None:
        self.command("PING")

    def read(self) -> Frame:
        return parse_frame(self.command("GET"))

    def write(self, frame: Frame) -> None:
        """Queue a whole-calendar frame. Not persisted until save()."""
        self.send(encode_frame(frame))

    def __getitem__(self, key: Key) -> bool:
        return self.read()[key]

    def __setitem__(self, key: Key, on: bool) -> None:
        self.send(encode_set(key, on))

    def set_today(self, on: bool = True) -> None:
        self[date.today()] = on

    def clear(self) -> None:
        """Turn every LED off. Not persisted until save()."""
        self.send("CLR")

    def save(self) -> None:
        """Persist the displayed LEDs to EEPROM."""
        self.command("SAVE")

    def revert(self) -> None:
        """Discard unsaved changes, reloading from EEPROM."""
        self.command("LOAD")

    @property
    def brightness(self) -> int:
        return int(self.command("BRI"))

    @brightness.setter
    def brightness(self, level: int) -> None:
        self.send(encode_brightness(level))

    @property
    def mode(self) -> Mode:
        return Mode(self.command("MODE"))

    @mode.setter
    def mode(self, mode: Mode) -> None:
        self.send(f"MODE {mode.value}")

    def next_event(self, timeout: float | None = None) -> Event | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def events(self, timeout: float | None = None) -> Iterator[Event]:
        """Yield events until none arrives for `timeout` seconds (forever if None)."""
        while (event := self.next_event(timeout)) is not None:
            yield event
