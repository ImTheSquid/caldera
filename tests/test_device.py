import time

import pytest

from caldera import BrightnessButton, Calendar, CalendarError, Frame, Mode, Touch
from fake import FakeDevice


@pytest.fixture
def dev():
    return FakeDevice()


@pytest.fixture
def cal(dev):
    with Calendar(stream=dev, boot_timeout=1, reply_timeout=0.2) as c:
        yield c


def test_set_get(cal, dev):
    cal[3, 14] = True
    assert dev.received[-1] == "SET 2 13 1"
    assert cal[3, 14]
    assert not cal[3, 15]


def test_write_read_round_trip(cal):
    frame = Frame([(i * 0x1234567) for i in range(12)])
    cal.write(frame)
    assert cal.read() == frame


def test_save_revert(cal):
    cal[1, 1] = True
    cal.save()
    cal.clear()
    assert cal.read() == Frame()
    cal.revert()
    assert cal.read().lit() == [(1, 1)]


def test_brightness_and_mode(cal):
    cal.brightness = 50
    assert cal.brightness == 50
    cal.mode = Mode.HOST
    assert cal.mode is Mode.HOST


def test_err_raises(cal):
    with pytest.raises(CalendarError, match="unknown"):
        cal.command("BOGUS")


def test_events_interleaved_with_replies(cal, dev):
    dev.emit("EV T 0 0", "x: 0\ty: 0", "EV B BRIGHT", "EV garbage")
    cal.ping()
    assert list(cal.events(timeout=0.1)) == [Touch(1, 1), BrightnessButton("BRIGHT")]


def test_reply_timeout(cal, dev):
    dev.mute = True
    with pytest.raises(TimeoutError):
        cal.ping()


def test_late_reply_is_not_misattributed(cal, dev):
    dev.mute = True
    with pytest.raises(TimeoutError):
        cal.command("BRI")
    dev.emit("OK 128")  # the late reply to BRI
    dev.mute = False
    time.sleep(0.05)
    assert cal.command("MODE") == "L"


def test_lines_before_banner_are_ignored():
    dev = FakeDevice()
    dev.out.queue.appendleft(b"OK stale\n")
    with Calendar(stream=dev, boot_timeout=1) as cal:
        cal.ping()


def test_version_mismatch():
    with pytest.raises(CalendarError, match="protocol 2"):
        Calendar(stream=FakeDevice(banner="READY EDC 2"), boot_timeout=1)


def test_missing_banner():
    with pytest.raises(TimeoutError):
        Calendar(stream=FakeDevice(banner="# nothing"), boot_timeout=0.2)


def test_command_length_guard(cal):
    with pytest.raises(ValueError):
        cal.command("W 0 " + "x" * 80)
