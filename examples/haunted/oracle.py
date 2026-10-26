"""A demon in a local LLM, streamed word by word into a queue."""

import json
import queue
import re
import threading
import urllib.request

from font import CHARSET

URL = "http://localhost:11434/v1/chat/completions"  # Ollama's OpenAI-compatible endpoint
MODEL = "llama3.2:3b"
SYSTEM = (
    "You are a demon trapped in a haunted mirror on Halloween night. A mortal writes to you on the glass "
    "with a finger, in capitals, maybe with missing spaces or a wrong letter. Reply directly to what they wrote, "
    "the way someone in a conversation would: answer their question or react to what they said, "
    "with a sinister, playful twist. One sentence, at most twelve words. No emoji, lists or quotation marks."
)
# Example exchanges; small models follow these far better than the instructions alone
SHOTS = [
    ("HI", "Hello there. Come closer to the glass, I won't bite."),
    ("HOWAREYOU", "Starving, thanks for asking. Are you offering?"),
    ("DO YOU LIKE DOGS", "Love them. They always bark when I stand behind you."),
]
CAP = 80  # characters shown, cut at a word boundary
FALLBACK = "THE MIRROR IS SILENT..."
TIMEOUT = 20.0


def clean(text: str) -> str:
    """Uppercase, keep only characters the font can draw, collapse whitespace."""
    text = text.upper().replace("’", "'")
    return re.sub(r"\s+", " ", "".join(c if c in CHARSET else " " for c in text.replace("\n", " ")))


def deltas(message: str, model: str, url: str):
    """Yield content fragments from a streamed chat completion."""
    body = {
        "model": model,
        "stream": True,
        "max_tokens": 48,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": SYSTEM},
            *({"role": r, "content": c} for u, a in SHOTS for r, c in (("user", u), ("assistant", a))),
            {"role": "user", "content": message},
        ],
    }
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            choices = json.loads(data).get("choices") or [{}]
            if fragment := choices[0].get("delta", {}).get("content"):
                yield fragment


def ask(message: str, out: queue.Queue, model: str = MODEL, url: str = URL) -> threading.Thread:
    """Stream the demon's reply into `out` a word at a time, then None."""

    def run() -> None:
        sent = 0
        pending = ""
        try:
            for fragment in deltas(message, model, url):
                pending += clean(fragment)
                *words, pending = pending.split(" ")
                for word in words:
                    if not word:
                        continue
                    if sent + len(word) + 3 > CAP:
                        out.put("...")
                        return
                    out.put(("" if not sent else " ") + word)
                    sent += len(word) + 1
            if pending and sent + len(pending) <= CAP:
                out.put(("" if not sent else " ") + pending)
                sent += len(pending)
        except (OSError, ValueError) as e:
            print(f"oracle: {e}")
        finally:
            if not sent:
                out.put(FALLBACK)
            out.put(None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
