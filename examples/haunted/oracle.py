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
    "You are a demon trapped in a haunted mirror on Halloween night. "
    "A mortal has written to you on the glass. Reply with one short, menacing, playful sentence "
    "of at most ten words. Plain words only: no emoji, no lists, no quotation marks."
)
CAP = 60  # characters shown, cut at a word boundary
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
        "temperature": 0.9,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": message}],
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
                    if sent + len(word) > CAP:
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
