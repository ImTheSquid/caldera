"""Haunted mirror: imps skitter over the calendar, and a demon answers what you write.

    uv run examples/haunted/main.py [--keyboard] [--model llama3.2:3b]

Poke an imp to burst it. Draw letters one at a time anywhere on the glass; each
is read 1s after you lift and flashed back. Moon deletes the last letter (or
cancels), sun sends, and 6s of stillness also sends. The demon's reply scrolls
across the mirror. --keyboard takes typed lines instead of drawing.
Needs `OLLAMA_CONTEXT_LENGTH=2048 ollama serve` (the default context can take
many GB) and a model from train.py. Runs in host mode and never
saves, so the real calendar returns on Ctrl-C.
"""

import argparse
import queue
import sys
import threading
import time

from caldera import BrightnessButton, Calendar, Contact, Mode, Release
from caldera.protocol import MAX_BRIGHTNESS
from demons import HEIGHT, LOWEST, ROAM, Horde
from font import ROWS, Marquee, glyph
from ink import Ink
from oracle import MODEL, URL, ask, clean
from recognize import Model
from scene import Pad, compose
from train import MODEL as WEIGHTS

FPS = 50
BRIGHTNESS_STEP = 20
INK_START = 3  # distinct pads a stroke crosses before it is writing rather than a poke
FLASH = 0.6  # seconds a recognized letter is shown
AUTO_SEND = 6.0
LURK = [(1, ROWS.start - HEIGHT), (ROWS.stop, LOWEST)]  # imp head rows that clear the text band


class Mirror:
    def __init__(self, cal: Calendar, horde: Horde, reader: Model | None, model: str, url: str):
        self.cal, self.horde, self.reader, self.model, self.url = cal, horde, reader, model, url
        self.level = cal.brightness
        self.state = "idle"  # idle -> writing -> replying -> idle
        self.ink = Ink()
        self.text = ""
        self.flash: tuple[str, float] | None = None
        self.activity = 0.0
        self.marquee: Marquee | None = None
        self.replies: queue.Queue = queue.Queue()

    def contact(self, pad: Pad, now: float) -> None:
        self.activity = now
        if self.state == "writing":
            self.ink.contact(pad)
            return
        self.horde.poke(pad, now)
        if self.state == "idle" and self.reader:
            self.ink.contact(pad)
            if len(self.ink.pads()) >= INK_START:
                self.state = "writing"
                self.horde.visible = False

    def release(self, now: float) -> None:
        self.ink.release(now)
        if self.state != "writing":
            self.ink.take()

    def button(self, kind: str, now: float) -> None:
        if self.state != "writing":
            step = BRIGHTNESS_STEP if kind == "BRIGHT" else -BRIGHTNESS_STEP
            self.level = max(0, min(MAX_BRIGHTNESS, self.level + step))
            self.cal.brightness = self.level
            return
        self.activity = now
        if kind == "BRIGHT":
            self.read(now)
            self.send(self.text)
        elif self.ink.strokes:
            self.ink.take()
        elif self.text:
            self.text = self.text[:-1]
            print(f"deleted: {self.text}")
        else:
            self.idle()

    def read(self, now: float) -> None:
        if self.ink.strokes:
            letter, p = self.reader.predict(self.ink.take())
            self.text += letter
            self.flash = (letter, now + FLASH)
            print(f"read {letter} ({p:.0%}): {self.text}")

    def send(self, message: str) -> None:
        self.idle()
        if not message:
            return
        print(f"> {message}\n< ", end="", flush=True)
        self.state = "replying"
        self.marquee = Marquee()
        self.replies = queue.Queue()
        ask(message, self.replies, self.model, self.url)
        self.horde.bands = LURK

    def idle(self) -> None:
        self.state = "idle"
        self.text = ""
        self.ink.take()
        self.marquee = None
        self.horde.visible = True
        self.horde.bands = ROAM

    def step(self, now: float, dt: float) -> None:
        if self.state == "writing":
            if self.ink.ready(now):
                self.read(now)
                self.activity = now
            elif not self.ink.strokes and now - self.activity > AUTO_SEND:
                self.send(self.text)
        elif self.state == "replying":
            while not self.replies.empty():
                word = self.replies.get()
                if word is None:
                    self.marquee.close()
                else:
                    self.marquee.push(word)
                    print(word, end="", flush=True)
            self.marquee.tick(dt)
            if self.marquee.done:
                print()
                self.idle()
        self.horde.step(now, dt)

    def pads(self, now: float) -> list[Pad]:
        if self.state == "writing":
            if self.flash and now < self.flash[1]:
                return glyph(self.flash[0])
            return list(self.ink.pads())
        if not self.marquee:
            return self.horde.pads(now)
        # Imps still running for cover, and bursts, never draw over the text
        return [p for p in self.horde.pads(now) if p[1] not in ROWS] + self.marquee.pads()


def typed() -> queue.Queue:
    lines: queue.Queue = queue.Queue()

    def run() -> None:
        for line in sys.stdin:
            lines.put(clean(line).strip())

    threading.Thread(target=run, daemon=True).start()
    return lines


def play(cal: Calendar, mirror: Mirror, lines: queue.Queue | None) -> None:
    tick = last = time.perf_counter()
    while True:
        while (event := cal.next_event(timeout=0)) is not None:
            now = time.perf_counter()
            if isinstance(event, Contact):
                mirror.contact((event.month, event.day), now)
            elif isinstance(event, Release):
                mirror.release(now)
            elif isinstance(event, BrightnessButton):
                mirror.button(event.kind, now)
        if lines and mirror.state == "idle" and not lines.empty():
            mirror.send(lines.get())

        now = time.perf_counter()
        mirror.step(now, now - last)
        last = now
        cal.write(compose(mirror.pads(now)))
        tick = max(tick + 1 / FPS, time.perf_counter())  # never catch up in a burst
        time.sleep(max(0.0, tick - time.perf_counter()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--imps", type=int, default=4)
    parser.add_argument("--keyboard", action="store_true", help="type messages instead of drawing them")
    parser.add_argument("--model", default=MODEL, help="LLM name for the endpoint")
    parser.add_argument("--url", default=URL, help="OpenAI-compatible chat completions URL")
    parser.add_argument("--brightness", type=int, help=f"0-{MAX_BRIGHTNESS}")
    args = parser.parse_args()

    reader = Model.load(WEIGHTS) if WEIGHTS.exists() else None
    if reader is None and not args.keyboard:
        print(f"no handwriting model at {WEIGHTS}; run train.py collect and fit to enable writing")
    with Calendar() as cal:
        original, level = cal.read(), cal.brightness
        if args.brightness is not None:
            cal.brightness = args.brightness
        cal.mode = Mode.HOST
        print("the mirror is awake; Ctrl-C to stop")
        try:
            play(cal, Mirror(cal, Horde(args.imps), reader, args.model, args.url), typed() if args.keyboard else None)
        except KeyboardInterrupt:
            pass
        finally:
            cal.write(original)
            cal.brightness = level
            cal.mode = Mode.LOCAL


if __name__ == "__main__":
    main()
