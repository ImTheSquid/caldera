"""In-memory stand-in for the firmware, speaking the same line protocol."""

import queue


class FakeDevice:
    def __init__(self, banner: str = "READY EDC 2"):
        self.out: queue.Queue[bytes] = queue.Queue()
        self.leds = [0] * 12
        self.saved = [0] * 12
        self.brightness = 128
        self.mode = "L"
        self.received: list[str] = []
        self.mute = False
        self.stall = 0  # hold replies to this many writes until the next one
        self.held: list[str] = []
        self.emit("# setup started", banner)

    def emit(self, *lines: str) -> None:
        for line in lines:
            self.out.put(line.encode() + b"\r\n")

    def read(self, size: int = 1) -> bytes:
        try:
            return self.out.get(timeout=0.01)
        except queue.Empty:
            return b""

    def write(self, data: bytes) -> int:
        line = data.decode().strip()
        self.received.append(line)
        reply = self.handle(line.split())
        if self.mute:
            return len(data)
        if self.stall:
            self.stall -= 1
            self.held.append(reply)
            return len(data)
        self.emit(*self.held, reply)
        self.held.clear()
        return len(data)

    def close(self) -> None:
        pass

    def handle(self, args: list[str]) -> str:
        match args:
            case ["PING"]:
                return "OK EDC 2"
            case ["PING", token]:
                return f"OK {token}"
            case [op] if op.startswith("F") and len(op) == 73:
                chars = [ord(c) - 0x30 for c in op[1:]]
                self.leds = [sum(v << (6 * (5 - i)) for i, v in enumerate(chars[6 * m : 6 * m + 6])) for m in range(12)]
                return "OK"
            case ["GET"]:
                return "OK " + " ".join(f"{w:X}" for w in self.leds)
            case ["SET", m, d, on]:
                bit = 1 << int(d)
                self.leds[int(m)] = self.leds[int(m)] | bit if on == "1" else self.leds[int(m)] & ~bit
                return "OK"
            case ["W", start, *words] if 1 <= len(words) <= 12 - int(start):
                for i, w in enumerate(words):
                    self.leds[int(start) + i] = int(w, 16)
                return "OK"
            case ["CLR"]:
                self.leds = [0] * 12
                return "OK"
            case ["BRI", *level]:
                if level:
                    self.brightness = int(level[0])
                return f"OK {self.brightness}"
            case ["SAVE"]:
                self.saved = list(self.leds)
                return "OK"
            case ["LOAD"]:
                self.leds = list(self.saved)
                return "OK"
            case ["MODE", *mode]:
                if mode:
                    self.mode = mode[0]
                return f"OK {self.mode}"
        return "ERR unknown command"
