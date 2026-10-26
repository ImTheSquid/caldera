"""Show a webcam on the calendar as a live mirror, with a preview window to tune it.

    uv run examples/mirror.py --list
    uv run examples/mirror.py [--camera INDEX|NAME] [--mode edge|thresh|dither]
    uv run examples/mirror.py --preview-only

The panel is 12x31 pixels, so the frame is cropped to the panel's aspect, mirrored,
reduced to a float field per pad (edges, local contrast, or brightness), smoothed over
time and binarized. The preview shows the camera with the crop box, and the panel as
it will light. Runs in host mode, so the brightness buttons are handled here.

Keys (preview window): c camera, m mode, [ ] level, + - zoom, w a s d pan,
t face tracking, i invert, q quit.
"""

import argparse
from dataclasses import dataclass

import cv2
import numpy as np

from caldera import BrightnessButton, Calendar, Frame, Mode
from caldera.protocol import DAYS_IN_MONTH, MAX_BRIGHTNESS

COLS, ROWS = 12, 31
COLUMN = 2.5  # month column pitch relative to day row pitch
ASPECT = (COLS - 1) * COLUMN / (ROWS - 1)  # physical width / height of the pad grid
MODES = ("edge", "thresh", "dither")
EDGE_SCALE = 8  # edges are found at this many samples per pad
EDGE_GAIN = 2.5  # cell edge coverage that counts as fully lit is 1 / EDGE_GAIN
LOCAL_SIGMA = 4.0  # pads; thresh compares each pad with its surroundings at this scale
LOCAL_GAIN = 1.5
MIN_SPREAD = 24.0  # grey levels; a flatter scene is not stretched further
FACE_SPAN = 2.8  # crop height in face heights while tracking
DETECT_EVERY = 3  # frames
DETECT_WIDTH = 320
BRIGHTNESS_STEP = 20
PIXEL = 16  # preview pixels per row pitch
HEADER = 28
LIT, DIM = (80, 190, 255), (45, 45, 45)  # BGR


def camera_names() -> list[str]:
    """Camera names in OpenCV's AVFoundation index order, or probed placeholders."""
    try:
        import AVFoundation as av

        devices = av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo)
        # OpenCV indexes built-in cameras ahead of external ones
        devices = sorted(devices, key=lambda d: d.deviceType() != av.AVCaptureDeviceTypeBuiltInWideAngleCamera)
        return [str(d.localizedName()) for d in devices]
    except ImportError:
        pass
    names = []
    for i in range(8):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            names.append(f"camera {i}")
        cap.release()
    return names


def pick_camera(spec: str | None, names: list[str]) -> int:
    if spec is None:
        return next((i for i, n in enumerate(names) if "virtual" not in n.lower()), 0)
    if spec.isdigit():
        return int(spec)
    matches = [i for i, n in enumerate(names) if spec.lower() in n.lower()]
    if not matches:
        raise SystemExit(f"no camera matches {spec!r}; try --list")
    return matches[0]


def open_camera(index: int) -> cv2.VideoCapture | None:
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if cap.isOpened() and cap.read()[0]:
        return cap
    cap.release()
    return None


def crop_box(width: int, height: int, zoom: float, cx: float, cy: float) -> tuple[int, int, int, int]:
    """The panel-shaped box (x, y, w, h) at 1/zoom of the largest that fits, centred on
    (cx, cy) in frame fractions and kept inside the frame."""
    h = min(height, width / ASPECT) / zoom
    w = h * ASPECT
    x = min(max(cx * width - w / 2, 0), width - w)
    y = min(max(cy * height - h / 2, 0), height - h)
    return round(x), round(y), max(1, round(w)), max(1, round(h))


def stretch(gray: np.ndarray) -> np.ndarray:
    """Spread the 5th-95th percentile of grey levels over 0-255."""
    lo, hi = np.percentile(gray, (5, 95))
    return np.clip((gray - lo) * (255.0 / max(hi - lo, MIN_SPREAD)), 0, 255)


def field(crop: np.ndarray, mode: str) -> np.ndarray:
    """A (ROWS, COLS) float field in 0-1 where higher lights the pad more."""
    if mode == "edge":
        big = cv2.resize(crop, (COLS * EDGE_SCALE, ROWS * EDGE_SCALE), interpolation=cv2.INTER_AREA)
        big = cv2.GaussianBlur(stretch(big.astype(np.float32)), (0, 0), 1.2).astype(np.uint8)
        edges = cv2.dilate(cv2.Canny(big, 40, 100), np.ones((3, 3), np.uint8))
        cover = cv2.resize(edges.astype(np.float32) / 255, (COLS, ROWS), interpolation=cv2.INTER_AREA)
        return np.clip(cover * EDGE_GAIN, 0, 1)
    gray = stretch(crop.astype(np.float32))
    low = cv2.resize(gray, (COLS, ROWS), interpolation=cv2.INTER_AREA) / 255
    if mode == "thresh":
        local = cv2.GaussianBlur(low, (0, 0), LOCAL_SIGMA, borderType=cv2.BORDER_REFLECT)
        return np.clip(0.5 + (low - local) * LOCAL_GAIN, 0, 1)
    return low


def dither(values: np.ndarray) -> np.ndarray:
    """Floyd-Steinberg to booleans at threshold 0.5."""
    v = values.astype(np.float64).copy()
    out = np.zeros(v.shape, bool)
    rows, cols = v.shape
    for y in range(rows):
        for x in range(cols):
            out[y, x] = v[y, x] >= 0.5
            err = v[y, x] - out[y, x]
            if x + 1 < cols:
                v[y, x + 1] += err * 7 / 16
            if y + 1 < rows:
                if x > 0:
                    v[y + 1, x - 1] += err * 3 / 16
                v[y + 1, x] += err * 5 / 16
                if x + 1 < cols:
                    v[y + 1, x + 1] += err / 16
    return out


def binarize(values: np.ndarray, mode: str, level: float) -> np.ndarray:
    """Lit pads as a (ROWS, COLS) bool array; a higher level lights more."""
    if mode == "dither":
        return dither(values + (level - 0.5))
    return values >= 1 - level


def to_frame(lit: np.ndarray) -> Frame:
    """Row d, column m is day d+1 of month m+1; days a month lacks are dropped."""
    return Frame([sum(1 << d for d in range(DAYS_IN_MONTH[m]) if lit[d, m]) for m in range(COLS)])


class FaceTracker:
    def __init__(self) -> None:
        self.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.n = 0

    def find(self, gray: np.ndarray) -> tuple[float, float, float] | None:
        """The largest face as (cx, cy, height), in frame fractions."""
        self.n += 1
        if self.n % DETECT_EVERY:
            return None
        h, w = gray.shape
        small = cv2.resize(gray, (DETECT_WIDTH, round(h * DETECT_WIDTH / w)))
        faces = self.cascade.detectMultiScale(small, 1.2, 5, minSize=(30, 30))
        if len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        sh, sw = small.shape
        return (x + fw / 2) / sw, (y + fh / 2) / sh, fh / sh


@dataclass
class View:
    mode: str
    level: float
    smooth: float
    invert: bool
    track: bool
    zoom: float = 1.0
    cx: float = 0.5
    cy: float = 0.5
    flip_y: bool = False
    mirror: bool = True
    state: np.ndarray | None = None

    def follow(self, face: tuple[float, float, float], size: tuple[int, int], alpha: float = 0.2) -> None:
        fx, fy, fh = face
        width, height = size
        base = min(height, width / ASPECT)
        target = min(max(base / (fh * height * FACE_SPAN), 1.0), 6.0)
        self.cx += (fx - self.cx) * alpha
        self.cy += (fy - self.cy) * alpha
        self.zoom += (target - self.zoom) * alpha

    def lit(self, frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        height, width = frame.shape[:2]
        box = crop_box(width, height, self.zoom, self.cx, self.cy)
        x, y, w, h = box
        crop = frame[y : y + h, x : x + w]
        if self.flip_y:
            crop = cv2.flip(crop, 0)
        values = field(crop, self.mode)
        self.state = values if self.state is None else self.state + (values - self.state) * self.smooth
        lit = binarize(self.state, self.mode, self.level)
        return (~lit if self.invert else lit), box


def render(frame: np.ndarray, box: tuple[int, int, int, int], lit: np.ndarray, view: View, camera: str) -> np.ndarray:
    """Camera with its crop box beside the panel drawn at its physical pad spacing."""
    shown = frame.copy()
    x, y, w, h = box
    cv2.rectangle(shown, (x, y), (x + w, y + h), (0, 255, 0), max(2, frame.shape[1] // 320))
    height = ROWS * PIXEL
    shown = cv2.resize(shown, (round(frame.shape[1] * height / frame.shape[0]), height))
    panel = np.zeros((height, round(COLS * COLUMN * PIXEL), 3), np.uint8)
    for m in range(COLS):
        for d in range(DAYS_IN_MONTH[m]):
            centre = (round((m + 0.5) * COLUMN * PIXEL), round((d + 0.5) * PIXEL))
            cv2.circle(panel, centre, PIXEL // 2 - 2, LIT if lit[d, m] else DIM, -1)
    body = np.hstack([shown, panel])
    bar = np.zeros((HEADER, body.shape[1], 3), np.uint8)
    text = f"{camera} | {view.mode} level {view.level:.2f} zoom {view.zoom:.1f}"
    text += f"{' | invert' if view.invert else ''}{' | track' if view.track else ''}"
    cv2.putText(bar, text, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, body])


def handle_key(key: int, view: View) -> bool:
    """Apply a preview key; return False to quit."""
    match chr(key) if key != 255 else "":
        case "q" | "\x1b":
            return False
        case "m":
            view.mode = MODES[(MODES.index(view.mode) + 1) % len(MODES)]
            view.state = None
        case "[":
            view.level = max(0.0, view.level - 0.05)
        case "]":
            view.level = min(1.0, view.level + 0.05)
        case "+" | "=":
            view.zoom = min(8.0, view.zoom * 1.1)
        case "-":
            view.zoom = max(1.0, view.zoom / 1.1)
        case "a":
            view.cx -= 0.03
        case "d":
            view.cx += 0.03
        case "w":
            view.cy -= 0.03
        case "s":
            view.cy += 0.03
        case "i":
            view.invert = not view.invert
        case "t":
            view.track = not view.track
    view.cx, view.cy = min(max(view.cx, 0), 1), min(max(view.cy, 0), 1)
    return True


def run(args: argparse.Namespace, cal: Calendar | None) -> None:
    names = camera_names()
    index = pick_camera(args.camera, names)
    cap = open_camera(index)
    if cap is None:
        raise SystemExit(f"cannot read camera {index}; allow camera access for your terminal, or try --list")
    view = View(args.mode, args.level, args.smooth, args.invert, args.track, flip_y=args.flip_y, mirror=not args.no_mirror)
    tracker = FaceTracker()
    sent: Frame | None = None
    level = cal.brightness if cal else 0
    cv2.namedWindow("mirror")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            if view.mirror:
                frame = cv2.flip(frame, 1)
            if view.track and (face := tracker.find(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))):
                view.follow(face, frame.shape[1::-1])
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lit, box = view.lit(gray)
            if cal is not None:
                out = to_frame(lit)
                if out != sent:
                    cal.write(out)
                    sent = out
                while (event := cal.next_event(timeout=0)) is not None:
                    if isinstance(event, BrightnessButton):
                        step = BRIGHTNESS_STEP if event.kind == "BRIGHT" else -BRIGHTNESS_STEP
                        level = max(0, min(MAX_BRIGHTNESS, level + step))
                        cal.brightness = level
            name = names[index] if index < len(names) else f"camera {index}"
            cv2.imshow("mirror", render(frame, box, lit, view, name))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("c") and names:
                nxt = (index + 1) % len(names)
                if (fresh := open_camera(nxt)) is not None:
                    cap.release()
                    cap, index = fresh, nxt
                continue
            if not handle_key(key, view):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--list", action="store_true", help="list cameras and exit")
    p.add_argument("--camera", help="camera index or part of its name (default: first real camera)")
    p.add_argument("--mode", choices=MODES, default="edge")
    p.add_argument("--level", type=float, default=0.5, help="0-1, higher lights more")
    p.add_argument("--smooth", type=float, default=0.5, help="0-1 weight of the newest frame")
    p.add_argument("--invert", action="store_true")
    p.add_argument("--track", action="store_true", help="crop around the largest face")
    p.add_argument("--flip-y", action="store_true", help="flip the panel vertically")
    p.add_argument("--no-mirror", action="store_true", help="do not flip horizontally")
    p.add_argument("--preview-only", action="store_true", help="do not talk to the calendar")
    args = p.parse_args()
    if args.list:
        for i, name in enumerate(camera_names()):
            print(f"{i}: {name}")
        return
    if args.preview_only:
        run(args, None)
        return
    with Calendar() as cal:
        base = cal.read()
        cal.mode = Mode.HOST
        print("mirroring; q in the preview window to stop")
        try:
            run(args, cal)
        finally:
            cal.write(base)
            cal.mode = Mode.LOCAL


if __name__ == "__main__":
    main()
