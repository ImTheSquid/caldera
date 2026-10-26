from datetime import date

import pytest

from caldera.protocol import (
    MAX_LINE,
    BrightnessButton,
    CalendarError,
    Contact,
    Frame,
    Release,
    Touch,
    encode_brightness,
    encode_frame,
    encode_set,
    index,
    parse_event,
    parse_frame,
    parse_reply,
)


def test_index_is_zero_based():
    assert index((1, 1)) == (0, 0)
    assert index(date(2026, 12, 31)) == (11, 30)


@pytest.mark.parametrize("key", [(0, 1), (13, 1), (2, 29), (4, 31), (1, 0), date(2028, 2, 29)])
def test_index_rejects_missing_pads(key):
    with pytest.raises(ValueError):
        index(key)


def test_frame_set_get_and_lit():
    f = Frame()
    f[3, 14] = True
    f[date(2026, 12, 31)] = True
    assert f[3, 14] and not f[3, 15]
    assert f.words[2] == 1 << 13
    assert f.lit() == [(3, 14), (12, 31)]
    f[3, 14] = False
    assert f.lit() == [(12, 31)]


def test_frame_masks_missing_pads():
    assert Frame([0xFFFFFFFF] * 12).words[1] == (1 << 28) - 1


def test_encode_set():
    assert encode_set((3, 14), True) == "SET 2 13 1"
    assert encode_set((3, 14), False) == "SET 2 13 0"


def test_encode_brightness_range():
    assert encode_brightness(200) == "BRI 200"
    with pytest.raises(ValueError):
        encode_brightness(201)


def test_parse_reply():
    assert parse_reply("OK") == ""
    assert parse_reply("OK 42") == "42"
    with pytest.raises(CalendarError, match="nope"):
        parse_reply("ERR nope")
    with pytest.raises(CalendarError):
        parse_reply("garbage")


def test_parse_frame_round_trip():
    f = Frame([i << i for i in range(12)])
    assert parse_frame(" ".join(f"{w:X}" for w in f.words)) == f
    with pytest.raises(CalendarError):
        parse_frame("1 2 3")
    with pytest.raises(CalendarError):
        parse_frame(" ".join(["zz"] * 12))


def test_parse_event():
    assert parse_event("EV T 2 13") == Touch(3, 14)
    assert parse_event("EV B DIM") == BrightnessButton("DIM")
    assert parse_event("EV D 11 30") == Contact(12, 31)
    assert parse_event("EV U") == Release()
    with pytest.raises(CalendarError):
        parse_event("EV X")


def test_encode_frame_layout():
    f = Frame()
    f[1, 1] = True  # January bit 0: last char of month 0
    f[12, 31] = True  # December bit 30: first char of month 11
    line = encode_frame(f)
    assert len(line) == 73 and len(line) <= MAX_LINE
    assert line[6] == "1" and line[67] == "1"
    assert line.count("0") == 70
