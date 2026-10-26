"""Teach the mirror your handwriting.

    uv run examples/haunted/train.py collect [--rounds 8] [--letters ABC]
    uv run examples/haunted/train.py fit

collect flashes each letter, then waits for you to draw it anywhere on the
calendar; the letter is taken 1s after you lift. Moon clears a bad drawing,
sun skips the letter. Samples are appended to data/samples.json as you go.
fit prints k-fold accuracy and the worst confusions, then saves data/model.npz.
"""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from caldera import BrightnessButton, Calendar, Contact, Mode, Release
from font import glyph
from ink import Ink
from recognize import LETTERS, Sample, evaluate, train
from scene import compose

DATA = Path(__file__).with_name("data")
SAMPLES = DATA / "samples.json"
MODEL = DATA / "model.npz"
FPS = 50
PROMPT = 1.0  # seconds the target letter is shown


def load_samples() -> list[Sample]:
    if not SAMPLES.exists():
        return []
    return [(s["letter"], [[tuple(p) for p in st] for st in s["strokes"]]) for s in json.loads(SAMPLES.read_text())]


def save_samples(samples: list[Sample]) -> None:
    DATA.mkdir(exist_ok=True)
    SAMPLES.write_text(json.dumps([{"letter": letter, "strokes": strokes} for letter, strokes in samples]))


def draw_letter(cal: Calendar, letter: str) -> list | None:
    """Show the letter, then capture one drawing of it; None if skipped."""
    cal.write(compose(glyph(letter)))
    time.sleep(PROMPT)
    while cal.next_event(timeout=0) is not None:
        pass
    ink = Ink()
    tick = time.perf_counter()
    while True:
        while (event := cal.next_event(timeout=0)) is not None:
            if isinstance(event, Contact):
                ink.contact((event.month, event.day))
            elif isinstance(event, Release):
                ink.release(time.perf_counter())
            elif isinstance(event, BrightnessButton):
                if event.kind == "BRIGHT":
                    return None
                ink.take()
        if ink.ready(time.perf_counter()):
            return ink.take()
        cal.write(compose(ink.pads()))
        tick = max(tick + 1 / FPS, time.perf_counter())
        time.sleep(max(0.0, tick - time.perf_counter()))


def collect(rounds: int, letters: str) -> None:
    samples = load_samples()
    with Calendar() as cal:
        original = cal.read()
        cal.mode = Mode.HOST
        try:
            for r in range(rounds):
                for letter in random.sample(letters, len(letters)):
                    print(f"round {r + 1}/{rounds}: draw {letter}", end=" ", flush=True)
                    strokes = draw_letter(cal, letter)
                    if strokes is None:
                        print("skipped")
                        continue
                    samples.append((letter, strokes))
                    save_samples(samples)
                    print(f"({sum(s[0] == letter for s in samples)} of {letter})")
        except KeyboardInterrupt:
            pass
        finally:
            cal.write(original)
            cal.mode = Mode.LOCAL
    print(f"{len(samples)} samples in {SAMPLES}")


def fit() -> None:
    samples = load_samples()
    counts = {letter: sum(s[0] == letter for s in samples) for letter in LETTERS}
    if missing := [letter for letter, n in counts.items() if n < 2]:
        raise SystemExit(f"need at least 2 samples of each letter; short: {''.join(missing)}")
    rng = np.random.default_rng(0)
    accuracy, misses = evaluate(samples, rng)
    print(f"{len(samples)} samples, 4-fold accuracy {accuracy:.1%}")
    for (truth, guess), n in misses.most_common(8):
        print(f"  {truth} read as {guess}: {n}/{counts[truth]}")
    DATA.mkdir(exist_ok=True)
    train(samples, rng).save(MODEL)
    print(f"saved {MODEL}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--rounds", type=int, default=8)
    c.add_argument("--letters", default=LETTERS, type=str.upper)
    sub.add_parser("fit")
    args = parser.parse_args()
    if args.cmd == "collect":
        collect(args.rounds, args.letters)
    else:
        fit()


if __name__ == "__main__":
    main()
