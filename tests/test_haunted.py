import json
import queue
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import numpy as np
import pytest
from demons import ROAM, Horde
from font import ROWS, Marquee, columns, glyph
from ink import Ink, physical, rasterize
from main import LURK, Mirror
from oracle import CAP, FALLBACK, ask, clean
from recognize import train
from scene import VALID


def test_imps_stay_on_pads():
    horde = Horde(8, random.Random(1))
    for i in range(3000):
        now = i / 50
        horde.step(now, 1 / 50)
        if i % 300 == 0:
            horde.bands = LURK if horde.bands == ROAM else ROAM
        assert set(horde.pads(now)) <= VALID


def test_lurking_imps_clear_the_text_band():
    horde = Horde(4, random.Random(4))
    horde.bands = LURK
    for i in range(500):
        horde.step(i / 50, 1 / 50)
    for i in range(500, 3000):
        now = i / 50
        horde.step(now, 1 / 50)
        assert not [p for imp in horde.imps if imp.respawn_at is None for p in imp.cells(now) if p[1] in ROWS]


def test_sprite_is_three_columns_wide():
    imp = Horde(1, random.Random(5)).imps[0]
    m, d = imp.head
    assert {c[0] for c in imp.cells(0.0)} == {m - 1, m, m + 1}
    assert {c[1] for c in imp.cells(0.0)} == set(range(d, d + 5))


def test_poke_bursts_imp_and_respawns():
    horde = Horde(1, random.Random(2))
    imp = horde.imps[0]
    assert horde.poke(imp.head, 0.0)
    assert imp.respawn_at is not None and horde.bursts
    horde.step(5.0, 0.02)
    assert horde.imps[0].respawn_at is None
    assert not horde.bursts


def test_poke_miss_scatters():
    horde = Horde(1, random.Random(3))
    imp = horde.imps[0]
    m, d = imp.head
    pad = (m, d - 4) if d > 5 else (m, d + 6)
    assert not horde.poke(pad, 0.0)
    assert imp.flee_until > 0


def test_marquee_waits_for_text_then_drains():
    mq = Marquee()
    mq.push("HI")
    for _ in range(20):
        mq.tick(0.5)
    assert mq.offset == len(columns("HI")) and not mq.done  # newest text parked at the right edge
    assert {m for m, _ in mq.pads()} == {5, 6, 7, 9, 10, 11}
    mq.close()
    for _ in range(20):
        mq.tick(0.5)
    assert mq.done and mq.pads() == []


def test_glyph_centered_in_text_band():
    pads = glyph("A")
    assert {m for m, _ in pads} == {5, 6, 7}
    assert {d for _, d in pads} == set(range(9, 19))


def test_ink_fills_gaps_and_commits_after_pause():
    ink = Ink()
    ink.contact((1, 1))
    ink.contact((1, 5))
    ink.release(10.0)
    assert {(1, d) for d in range(1, 6)} <= ink.pads()
    assert not ink.ready(10.5) and ink.ready(11.0)
    assert ink.take() == [[(1, 1), (1, 5)]] and not ink.strokes


def test_rasterize_ignores_position_and_size():
    small = rasterize(physical([[(2, 3), (2, 8)]]))
    big = rasterize(physical([[(9, 10), (9, 25)]]))
    assert np.array_equal(small, big)
    assert small.max() == 1.0


def shapes():
    """Three easily separated letters drawn at a few positions and sizes."""
    out = []
    for m, d, s in [(2, 2, 1), (5, 4, 2), (3, 8, 3), (7, 3, 2), (6, 12, 1)]:
        out.append(("I", [[(m, d), (m, d + 6 * s)]]))
        out.append(("L", [[(m, d), (m, d + 6 * s), (m + 2 * s, d + 6 * s)]]))
        out.append(("O", [[(m, d), (m + 2 * s, d), (m + 2 * s, d + 6 * s), (m, d + 6 * s), (m, d)]]))
    return out


def test_mlp_learns_distinct_shapes():
    rng = np.random.default_rng(0)
    model = train(shapes(), rng, copies=10, epochs=20)
    assert model.predict([[(10, 5), (10, 20)]])[0] == "I"
    assert model.predict([[(4, 2), (4, 14), (6, 14)]])[0] == "L"
    assert model.predict([[(3, 3), (6, 3), (6, 18), (3, 18), (3, 3)]])[0] == "O"


def test_clean_keeps_drawable_text():
    assert clean("Hello,  mortal… 👹\nYou’re mine!") == "HELLO, MORTAL YOU'RE MINE!"


@pytest.fixture
def llm():
    """A stand-in chat endpoint that streams `llm.reply` in small fragments."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            server.requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            try:
                for i in range(0, len(server.reply), 3):
                    chunk = {"choices": [{"delta": {"content": server.reply[i : i + 3]}}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
            except BrokenPipeError:
                pass  # the client stops reading once it hits the cap

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.requests = []
    server.reply = ""
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def reply(server, message):
    out = queue.Queue()
    ask(message, out, url=f"http://127.0.0.1:{server.server_port}/v1/chat/completions").join(5)
    return "".join(iter(out.get, None))


def test_oracle_streams_cleaned_reply(llm):
    llm.reply = "Your soul smells delicious, mortal."
    assert reply(llm, "HI") == "YOUR SOUL SMELLS DELICIOUS, MORTAL."
    messages = llm.requests[0]["messages"]
    assert llm.requests[0]["stream"] and messages[-1] == {"role": "user", "content": "HI"}
    assert [m["role"] for m in messages[:3]] == ["system", "user", "assistant"]


def test_oracle_caps_at_word_boundary(llm):
    llm.reply = "doom " * 30
    text = reply(llm, "HI")
    assert len(text) <= CAP and text.endswith("DOOM...")


def test_oracle_falls_back_when_unreachable():
    out = queue.Queue()
    ask("HI", out, url="http://127.0.0.1:9/v1/chat/completions").join(5)
    assert "".join(iter(out.get, None)) == FALLBACK


def test_mirror_reads_writing_and_scrolls_reply(llm):
    llm.reply = "Boo."
    reader = SimpleNamespace(predict=lambda strokes: ("H", 0.9))
    url = f"http://127.0.0.1:{llm.server_port}/v1/chat/completions"
    mirror = Mirror(SimpleNamespace(brightness=100), Horde(0), reader, "demon", url)
    for d in range(1, 6):
        mirror.contact((3, d), 0.0)
    assert mirror.state == "writing"
    mirror.release(0.1)
    mirror.step(1.2, 0.02)
    assert mirror.text == "H"
    mirror.button("BRIGHT", 1.3)
    assert mirror.state == "replying"
    for i in range(2000):
        mirror.step(1.3 + i * 0.1, 0.1)
        if mirror.state == "idle":
            break
        time.sleep(0.001)
    assert mirror.state == "idle"
    assert llm.requests[0]["messages"][-1]["content"] == "H"


def test_short_tap_pokes_without_writing():
    reader = SimpleNamespace(predict=lambda strokes: ("H", 0.9))
    mirror = Mirror(SimpleNamespace(brightness=100), Horde(0), reader, "demon", "http://127.0.0.1:9")
    mirror.contact((3, 3), 0.0)
    mirror.release(0.1)
    assert mirror.state == "idle" and not mirror.ink.strokes
