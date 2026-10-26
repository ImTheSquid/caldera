"""Serial client for an Every Day Calendar running firmware/caldera."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from datetime import date
from typing import Protocol

import serial
from serial.tools import list_ports

from .protocol import (
    BAUD,
    MAX_LINE,
    VERSION,
    CalendarError,
    Event,
    Frame,
    Key,
    Mode,
    encode_brightness,
    encode_set,
    encode_write,
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


class Calendar:
    """A connected calendar. Opening the port resets the board (~6s boot)."""

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
        self._replies: queue.Queue[str] = queue.Queue()
        self._events: queue.Queue[Event] = queue.Queue()
        self._ready = threading.Event()
        self._version: int | None = None
        self._closed = threading.Event()
        self._lock = threading.Lock()
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

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._closed.set()
        self._stream.close()
        self._reader.join(timeout=1)

    def _read_loop(self) -> None:
        buf = b""
        while not self._closed.is_set():
            try:
                chunk = self._stream.read(64)
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
                self._replies.put(line)
            # Anything else is firmware debug output.
        except (CalendarError, ValueError):
            pass  # a corrupted line must not kill the reader

    def command(self, line: str) -> str:
        """Send one raw protocol line and return the OK payload."""
        if len(line) >= MAX_LINE or "\n" in line:
            raise ValueError(f"command too long or multi-line: {line!r}")
        with self._lock:
            while not self._replies.empty():  # late replies from a timed-out command
                self._replies.get_nowait()
            self._stream.write(line.encode("ascii") + b"\n")
            try:
                reply = self._replies.get(timeout=self.reply_timeout)
            except queue.Empty:
                raise TimeoutError(f"no reply to {line!r}") from None
        return parse_reply(reply)

    def ping(self) -> None:
        self.command("PING")

    def read(self) -> Frame:
        return parse_frame(self.command("GET"))

    def write(self, frame: Frame) -> None:
        for line in encode_write(frame):
            self.command(line)

    def __getitem__(self, key: Key) -> bool:
        return self.read()[key]

    def __setitem__(self, key: Key, on: bool) -> None:
        self.command(encode_set(key, on))

    def set_today(self, on: bool = True) -> None:
        self[date.today()] = on

    def clear(self) -> None:
        """Turn every LED off. Not persisted until save()."""
        self.command("CLR")

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
        self.command(encode_brightness(level))

    @property
    def mode(self) -> Mode:
        return Mode(self.command("MODE"))

    @mode.setter
    def mode(self, mode: Mode) -> None:
        self.command(f"MODE {mode.value}")

    def next_event(self, timeout: float | None = None) -> Event | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def events(self, timeout: float | None = None) -> Iterator[Event]:
        """Yield events until none arrives for `timeout` seconds (forever if None)."""
        while (event := self.next_event(timeout)) is not None:
            yield event
