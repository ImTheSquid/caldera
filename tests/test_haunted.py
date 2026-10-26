import random

from demons import Horde
from scene import VALID


def test_imps_stay_on_pads():
    horde = Horde(8, random.Random(1))
    for i in range(3000):
        now = i / 50
        horde.step(now, 1 / 50)
        if i % 300 == 0:
            horde.band = (1, 5) if horde.band != (1, 5) else (1, 26)
        assert set(horde.pads(now)) <= VALID


def test_poke_bursts_imp_and_respawns():
    horde = Horde(1, random.Random(2))
    imp = horde.imps[0]
    assert horde.poke(imp.head, 0.0)
    assert imp.respawn_at is not None and horde.bursts
    horde.step(5.0, 0.02)
    assert horde.imps[0].respawn_at is None
    assert not horde.bursts


def test_poke_miss_scatters():
    horde = Horde(1, random.Random(3))
    imp = horde.imps[0]
    m, d = imp.head
    pad = (m, d - 4) if d > 5 else (m, d + 6)
    assert not horde.poke(pad, 0.0)
    assert imp.flee_until > 0
