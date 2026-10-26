"""3x5 font, drawn with rows doubled so glyphs come out roughly square, and a marquee."""

from scene import Pad

GLYPHS = {
    "A": (".#.", "#.#", "###", "#.#", "#.#"),
    "B": ("##.", "#.#", "##.", "#.#", "##."),
    "C": (".##", "#..", "#..", "#..", ".##"),
    "D": ("##.", "#.#", "#.#", "#.#", "##."),
    "E": ("###", "#..", "##.", "#..", "###"),
    "F": ("###", "#..", "##.", "#..", "#.."),
    "G": (".##", "#..", "#.#", "#.#", ".##"),
    "H": ("#.#", "#.#", "###", "#.#", "#.#"),
    "I": ("###", ".#.", ".#.", ".#.", "###"),
    "J": ("..#", "..#", "..#", "#.#", ".#."),
    "K": ("#.#", "#.#", "##.", "#.#", "#.#"),
    "L": ("#..", "#..", "#..", "#..", "###"),
    "M": ("#.#", "###", "###", "#.#", "#.#"),
    "N": ("##.", "#.#", "#.#", "#.#", "#.#"),
    "O": ("###", "#.#", "#.#", "#.#", "###"),
    "P": ("##.", "#.#", "##.", "#..", "#.."),
    "Q": (".#.", "#.#", "#.#", "##.", ".##"),
    "R": ("##.", "#.#", "##.", "#.#", "#.#"),
    "S": (".##", "#..", ".#.", "..#", "##."),
    "T": ("###", ".#.", ".#.", ".#.", ".#."),
    "U": ("#.#", "#.#", "#.#", "#.#", "###"),
    "V": ("#.#", "#.#", "#.#", "#.#", ".#."),
    "W": ("#.#", "#.#", "###", "###", "#.#"),
    "X": ("#.#", "#.#", ".#.", "#.#", "#.#"),
    "Y": ("#.#", "#.#", ".#.", ".#.", ".#."),
    "Z": ("###", "..#", ".#.", "#..", "###"),
    "0": ("###", "#.#", "#.#", "#.#", "###"),
    "1": (".#.", "##.", ".#.", ".#.", "###"),
    "2": ("##.", "..#", ".#.", "#..", "###"),
    "3": ("##.", "..#", ".#.", "..#", "##."),
    "4": ("#.#", "#.#", "###", "..#", "..#"),
    "5": ("###", "#..", "##.", "..#", "##."),
    "6": (".##", "#..", "###", "#.#", "###"),
    "7": ("###", "..#", ".#.", ".#.", ".#."),
    "8": ("###", "#.#", "###", "#.#", "###"),
    "9": ("###", "#.#", "###", "..#", "##."),
    ".": (".", ".", ".", ".", "#"),
    ",": ("..", "..", "..", ".#", "#."),
    "!": ("#", "#", "#", ".", "#"),
    "?": ("##.", "..#", ".#.", "...", ".#."),
    "'": ("#", "#", ".", ".", "."),
    "-": ("..", "..", "##", "..", ".."),
    " ": ("..", "..", "..", "..", ".."),
}
CHARSET = frozenset(GLYPHS)
TOP = 9  # first day row of the text band
ROWS = range(TOP, TOP + 10)  # day rows the text band covers
SCROLL = 6.0  # columns per second


def columns(text: str) -> list[int]:
    """Each column as a 5-bit mask, bit r = glyph row r, with a blank column after each glyph."""
    out = []
    for ch in text:
        rows = GLYPHS[ch]
        for c in range(len(rows[0])):
            out.append(sum(1 << r for r, row in enumerate(rows) if row[c] == "#"))
        out.append(0)
    return out


def draw(cols: list[int], left: int = 1, top: int = TOP) -> list[Pad]:
    """Pads lit by `cols`, the first at month `left`; each glyph row covers two days."""
    return [
        (left + i, top + 2 * r + k)
        for i, mask in enumerate(cols)
        if 1 <= left + i <= 12
        for r in range(5)
        if mask >> r & 1
        for k in (0, 1)
    ]


def glyph(ch: str) -> list[Pad]:
    """One character centered on the mirror."""
    cols = columns(ch)[:-1]
    return draw(cols, left=(12 - len(cols)) // 2 + 1)


class Marquee:
    """Text streamed in from the right; it waits for more rather than scrolling into a gap."""

    def __init__(self):
        self.cols = [0] * 12  # lead-in, so text enters from the right edge
        self.offset = 0.0
        self.closed = False

    def push(self, text: str) -> None:
        self.cols += columns(text)

    def close(self) -> None:
        self.closed = True

    def tick(self, dt: float) -> None:
        limit = len(self.cols) if self.closed else len(self.cols) - 12
        self.offset = min(self.offset + SCROLL * dt, max(limit, self.offset))

    @property
    def done(self) -> bool:
        return self.closed and self.offset >= len(self.cols)

    def pads(self) -> list[Pad]:
        start = int(self.offset)
        return draw(self.cols[start : start + 12])
