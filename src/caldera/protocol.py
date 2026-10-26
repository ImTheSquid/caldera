"""Line protocol spoken by firmware/caldera/caldera.ino.

The device uses 0-based (month, day); everything public here is 1-based.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

VERSION = 1
BAUD = 38400
MAX_LINE = 60  # firmware RX buffer is 64 bytes
MAX_BRIGHTNESS = 200
WORDS_PER_WRITE = 6
DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

Key = tuple[int, int] | date


class CalendarError(Exception):
    """The device rejected a command or sent something unparseable."""


class Mode(Enum):
    LOCAL = "L"  # touch toggles the day on the device, and is reported
    HOST = "H"  # touch is only reported


@dataclass(frozen=True)
class Touch:
    month: int
    day: int


@dataclass(frozen=True)
class BrightnessButton:
    kind: str  # "DIM" or "BRIGHT"


Event = Touch | BrightnessButton


def index(key: Key) -> tuple[int, int]:
    """Validate a 1-based (month, day) or date and return the 0-based device index."""
    month, day = (key.month, key.day) if isinstance(key, date) else key
    if not 1 <= month <= 12:
        raise ValueError(f"month {month} out of range 1-12")
    if not 1 <= day <= DAYS_IN_MONTH[month - 1]:
        raise ValueError(f"no pad for {month}/{day}")
    return month - 1, day - 1


def _mask(m0: int) -> int:
    return (1 << DAYS_IN_MONTH[m0]) - 1


class Frame:
    """Every LED's state as 12 bitmask words, bit d of word m = month m+1, day d+1."""

    __slots__ = ("words",)

    def __init__(self, words: list[int] | None = None):
        words = list(words) if words is not None else [0] * 12
        if len(words) != 12:
            raise ValueError("a frame has 12 months")
        self.words = [w & _mask(m) for m, w in enumerate(words)]

    def __getitem__(self, key: Key) -> bool:
        m, d = index(key)
        return bool(self.words[m] >> d & 1)

    def __setitem__(self, key: Key, on: bool) -> None:
        m, d = index(key)
        if on:
            self.words[m] |= 1 << d
        else:
            self.words[m] &= ~(1 << d)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Frame) and self.words == other.words

    def __repr__(self) -> str:
        return f"Frame({self.lit()})"

    def lit(self) -> list[tuple[int, int]]:
        return [
            (m + 1, d + 1)
            for m, w in enumerate(self.words)
            for d in range(DAYS_IN_MONTH[m])
            if w >> d & 1
        ]


def encode_set(key: Key, on: bool) -> str:
    m, d = index(key)
    return f"SET {m} {d} {int(bool(on))}"


def encode_write(frame: Frame) -> list[str]:
    return [
        f"W {start} " + " ".join(f"{w:08x}" for w in frame.words[start : start + WORDS_PER_WRITE])
        for start in range(0, 12, WORDS_PER_WRITE)
    ]


def encode_brightness(level: int) -> str:
    if not 0 <= level <= MAX_BRIGHTNESS:
        raise ValueError(f"brightness {level} out of range 0-{MAX_BRIGHTNESS}")
    return f"BRI {level}"


def parse_reply(line: str) -> str:
    """Return the payload of an OK line, raise on ERR."""
    if line == "OK" or line.startswith("OK "):
        return line[3:]
    if line.startswith("ERR"):
        raise CalendarError(line[4:] or "error")
    raise CalendarError(f"unexpected reply {line!r}")


def parse_frame(payload: str) -> Frame:
    try:
        words = [int(p, 16) for p in payload.split()]
    except ValueError:
        words = []
    if len(words) != 12:
        raise CalendarError(f"bad frame {payload!r}")
    return Frame(words)


def parse_event(line: str) -> Event:
    parts = line.split()
    match parts:
        case ["EV", "T", m, d]:
            return Touch(int(m) + 1, int(d) + 1)
        case ["EV", "B", kind]:
            return BrightnessButton(kind)
    raise CalendarError(f"bad event {line!r}")


def parse_banner(line: str) -> int:
    match line.split():
        case ["READY", "EDC", version]:
            return int(version)
    raise CalendarError(f"bad banner {line!r}")
