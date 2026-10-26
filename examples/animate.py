"""Draw animations on the calendar frame by frame, then play them back from here.

    uv run examples/animate.py edit NAME [--fps 8]
    uv run examples/animate.py play NAME [--fps N] [--loop] [--audio FILE]
    uv run examples/animate.py list

edit: tap a pad to toggle it, or drag to paint (the first pad decides on or
off). Sun stores the frame and keeps drawing on a copy of it; moon undoes the
last stroke, or with none left, takes the last stored frame back for editing.
Every store saves animations/NAME.json; Ctrl-C saves too. Editing an existing
name continues after its last frame. Both modes run in host mode and never
touch the saved calendar.

play --audio: FILE is played on the host with afplay, restarting each loop.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

from caldera import BrightnessButton, Calendar, Contact, Frame, Mode, Release
from caldera.protocol import index

DIR = Path(__file__).parents[1] / "animations"
BLINK = 0.15  # seconds dark after a store, so it registers


def path(name: str) -> Path:
    if not name or "/" in name or name.startswith("."):
        raise SystemExit(f"bad animation name {name!r}")
    return DIR / f"{name}.json"


def load(name: str) -> tuple[list[Frame], float | None]:
    p = path(name)
    if not p.exists():
        return [], None
    data = json.loads(p.read_text())
    return [Frame(words) for words in data["frames"]], data["fps"]


def save(name: str, frames: list[Frame], fps: float) -> None:
    DIR.mkdir(exist_ok=True)
    path(name).write_text(json.dumps({"fps": fps, "frames": [f.words for f in frames]}))


def line(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    """Pads after a up to b, one pad per step."""
    n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    return [(round(a[0] + (b[0] - a[0]) * i / n), round(a[1] + (b[1] - a[1]) * i / n)) for i in range(1, n + 1)]


class Editor:
    def __init__(self, frames: list[Frame]):
        self.frames = frames
        self.work = Frame(frames[-1].words) if frames else Frame()
        self.strokes: list[list[tuple[tuple[int, int], bool]]] = []  # (pad, previous value) per stroke
        self.paint: bool | None = None  # value of the stroke in progress
        self.last: tuple[int, int] | None = None
        self.reopened = False  # work is a stored frame taken back by undo

    def contact(self, pad: tuple[int, int]) -> None:
        if self.paint is None:
            self.paint = not self.work[pad]
            self.strokes.append([])
            path = [pad]
        else:
            path = line(self.last, pad)
        self.last = pad
        for p in path:
            try:
                index(p)
            except ValueError:
                continue  # interpolated through a missing pad
            if self.work[p] != self.paint:
                self.strokes[-1].append((p, self.work[p]))
                self.work[p] = self.paint

    def release(self) -> None:
        if self.strokes and not self.strokes[-1]:
            self.strokes.pop()
        self.paint = self.last = None

    def store(self) -> None:
        self.frames.append(Frame(self.work.words))
        self.strokes.clear()
        self.reopened = False

    def undo(self) -> str:
        if self.strokes:
            for p, was in reversed(self.strokes.pop()):
                self.work[p] = was
            return "undid stroke"
        if self.frames:
            self.work = self.frames.pop()
            self.reopened = True
            return f"editing frame {len(self.frames) + 1}"
        return "nothing to undo"

    def result(self) -> list[Frame]:
        """Stored frames, plus the working one if it holds unstored drawing."""
        return self.frames + [self.work] if self.strokes or self.reopened else list(self.frames)


def edit(cal: Calendar, name: str, fps: float | None) -> None:
    frames, stored_fps = load(name)
    fps = fps or stored_fps or 8.0
    editor = Editor(frames)
    print(f"{name}: {len(frames)} frames; sun stores, moon undoes, Ctrl-C saves and quits")
    try:
        while True:
            event = cal.next_event(timeout=0.5)
            if isinstance(event, Contact):
                editor.contact((event.month, event.day))
            elif isinstance(event, Release):
                editor.release()
            elif isinstance(event, BrightnessButton) and event.kind == "BRIGHT":
                editor.release()
                editor.store()
                save(name, editor.frames, fps)
                print(f"stored frame {len(editor.frames)}")
                cal.write(Frame())
                time.sleep(BLINK)
            elif isinstance(event, BrightnessButton):
                editor.release()
                print(editor.undo())
            cal.write(editor.work)
    except KeyboardInterrupt:
        pass
    frames = editor.result()
    save(name, frames, fps)
    print(f"saved {len(frames)} frames to {path(name)}")


def play(cal: Calendar, name: str, fps: float | None, loop: bool, audio: Path | None = None) -> None:
    frames, stored_fps = load(name)
    if not frames:
        raise SystemExit(f"no animation {name!r} in {DIR}")
    period = 1 / (fps or stored_fps)
    sound: subprocess.Popen[bytes] | None = None
    tick = time.perf_counter()
    try:
        while True:
            if audio:
                sound = subprocess.Popen(["afplay", str(audio)])
                tick = time.perf_counter()
            for frame in frames:
                cal.write(frame)
                tick = max(tick + period, time.perf_counter())  # never catch up in a burst
                time.sleep(max(0.0, tick - time.perf_counter()))
            if not loop:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if sound and sound.poll() is None:
            sound.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("edit", "play"):
        p = sub.add_parser(cmd)
        p.add_argument("name")
        p.add_argument("--fps", type=float)
    sub.choices["play"].add_argument("--loop", action="store_true")
    sub.choices["play"].add_argument("--audio", type=Path, help="sound file to play alongside")
    sub.add_parser("list")
    args = parser.parse_args()

    if args.cmd == "list":
        for p in sorted(DIR.glob("*.json")):
            data = json.loads(p.read_text())
            print(f"{p.stem}: {len(data['frames'])} frames at {data['fps']:g} fps")
        return
    path(args.name)  # reject a bad name before the 7s boot
    if args.cmd == "play" and args.audio and not args.audio.is_file():
        raise SystemExit(f"no audio file {args.audio}")
    with Calendar() as cal:
        original = cal.read()
        cal.mode = Mode.HOST
        try:
            if args.cmd == "edit":
                edit(cal, args.name, args.fps)
            else:
                play(cal, args.name, args.fps, args.loop, args.audio)
        finally:
            cal.write(original)
            cal.mode = Mode.LOCAL


if __name__ == "__main__":
    main()
