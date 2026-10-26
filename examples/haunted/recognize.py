"""Micro MLP letter recognizer: 16x16 raster -> 64 ReLU -> 26 letters, trained in numpy."""

from collections import Counter
from pathlib import Path

import numpy as np

from ink import SIZE, Stroke, augment, physical, rasterize

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
HIDDEN = 64

Sample = tuple[str, list[Stroke]]


class Model:
    def __init__(self, w1: np.ndarray, b1: np.ndarray, w2: np.ndarray, b2: np.ndarray):
        self.w1, self.b1, self.w2, self.b2 = w1, b1, w2, b2

    @classmethod
    def load(cls, path: Path) -> "Model":
        with np.load(path) as d:
            return cls(d["w1"], d["b1"], d["w2"], d["b2"])

    def save(self, path: Path) -> None:
        np.savez(path, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2)

    def probs(self, x: np.ndarray) -> np.ndarray:
        z = np.maximum(x @ self.w1 + self.b1, 0) @ self.w2 + self.b2
        e = np.exp(z - z.max(1, keepdims=True))
        return e / e.sum(1, keepdims=True)

    def predict(self, strokes: list[Stroke]) -> tuple[str, float]:
        p = self.probs(rasterize(physical(strokes))[None])[0]
        i = int(p.argmax())
        return LETTERS[i], float(p[i])


def dataset(samples: list[Sample], copies: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Each sample as drawn plus `copies - 1` augmented variants."""
    xs, ys = [], []
    for letter, strokes in samples:
        paths = physical(strokes)
        xs.append(rasterize(paths))
        xs += [rasterize(augment(paths, rng)) for _ in range(copies - 1)]
        ys += [LETTERS.index(letter)] * copies
    return np.array(xs), np.array(ys)


def train(
    samples: list[Sample],
    rng: np.random.Generator,
    copies: int = 40,
    epochs: int = 30,
    batch: int = 64,
    lr: float = 3e-3,
    decay: float = 1e-4,
) -> Model:
    x, y = dataset(samples, copies, rng)
    n_in = SIZE * SIZE
    params = [
        rng.normal(0, np.sqrt(2 / n_in), (n_in, HIDDEN)),
        np.zeros(HIDDEN),
        rng.normal(0, np.sqrt(2 / HIDDEN), (HIDDEN, len(LETTERS))),
        np.zeros(len(LETTERS)),
    ]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    t = 0
    for _ in range(epochs):
        order = rng.permutation(len(x))
        for i in range(0, len(x), batch):
            xb, yb = x[order[i : i + batch]], y[order[i : i + batch]]
            w1, b1, w2, b2 = params
            h = np.maximum(xb @ w1 + b1, 0)
            z = h @ w2 + b2
            p = np.exp(z - z.max(1, keepdims=True))
            p /= p.sum(1, keepdims=True)
            p[np.arange(len(yb)), yb] -= 1  # softmax cross-entropy gradient
            p /= len(yb)
            dh = (p @ w2.T) * (h > 0)
            grads = [xb.T @ dh + decay * w1, dh.sum(0), h.T @ p + decay * w2, p.sum(0)]
            t += 1
            for j, g in enumerate(grads):  # Adam
                m[j] = 0.9 * m[j] + 0.1 * g
                v[j] = 0.999 * v[j] + 0.001 * g * g
                params[j] -= lr * (m[j] / (1 - 0.9**t)) / (np.sqrt(v[j] / (1 - 0.999**t)) + 1e-8)
    return Model(*params)


def evaluate(samples: list[Sample], rng: np.random.Generator, folds: int = 4) -> tuple[float, Counter]:
    """k-fold accuracy on unaugmented held-out samples, and (true, predicted) miss counts."""
    order = rng.permutation(len(samples))
    misses: Counter = Counter()
    for k in range(folds):
        held = set(order[k::folds].tolist())
        model = train([s for i, s in enumerate(samples) if i not in held], rng)
        for i in held:
            letter, strokes = samples[i]
            guess, _ = model.predict(strokes)
            if guess != letter:
                misses[letter, guess] += 1
    return 1 - sum(misses.values()) / len(samples), misses
