"""Convert a video into an animation for animate.py.

    uv run examples/video2anim.py VIDEO NAME [--fps 30] [--threshold 128] [--invert] [--rotate 90]
    uv run examples/animate.py play NAME

The video is rotated clockwise by --rotate degrees, fitted to the panel in
physical units (a month column is 2.5 row pitches wide), letterboxed, and
binarized.
Needs ffmpeg on PATH.
"""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from caldera.protocol import DAYS_IN_MONTH

COLS, ROWS = 12, 31
COLUMN = 2.5  # month column pitch relative to day row pitch
DIR = Path(__file__).parents[1] / "animations"


def probe(video: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True,
    ).stdout
    w, h = map(int, out.strip().split(","))
    return w, h


ROTATIONS = {0: "", 90: "transpose=1,", 180: "hflip,vflip,", 270: "transpose=2,"}


def read_frames(video: str, fps: float, rotate: int) -> np.ndarray:
    """Greyscale frames as (n, ROWS, COLS), the video letterboxed onto the grid."""
    w, h = probe(video)
    if rotate in (90, 270):
        w, h = h, w
    scale = min(COLS * COLUMN / w, ROWS / h)  # pitches per source pixel
    cols = min(COLS, max(1, round(w * scale / COLUMN)))
    rows = min(ROWS, max(1, round(h * scale)))
    left, top = (COLS - cols) // 2, (ROWS - rows) // 2
    vf = (
        f"{ROTATIONS[rotate]}fps={fps},scale={cols}:{rows}:flags=area,"
        f"pad={COLS}:{ROWS}:{left}:{top}:color=black,format=gray"
    )
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", video, "-vf", vf, "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, ROWS, COLS)


def to_words(lit: np.ndarray) -> list[int]:
    return [sum(1 << d for d in range(DAYS_IN_MONTH[m]) if lit[d, m]) for m in range(COLS)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("video")
    parser.add_argument("name")
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument("--rotate", type=int, choices=sorted(ROTATIONS), default=0, help="degrees clockwise")
    args = parser.parse_args()

    grey = read_frames(args.video, args.fps, args.rotate)
    lit = grey >= args.threshold
    if args.invert:
        lit = ~lit
    DIR.mkdir(exist_ok=True)
    out = DIR / f"{args.name}.json"
    out.write_text(json.dumps({"fps": args.fps, "frames": [to_words(f) for f in lit]}))
    print(f"{out}: {len(lit)} frames at {args.fps:g} fps")


if __name__ == "__main__":
    main()
