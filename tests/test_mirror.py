import numpy as np
import pytest

pytest.importorskip("cv2")

import mirror
from mirror import ASPECT, COLS, ROWS, binarize, crop_box, dither, field, pick_camera, to_frame


def test_crop_box_has_panel_aspect_and_stays_inside():
    for zoom, cx, cy in [(1, 0.5, 0.5), (2, 0.0, 1.0), (4, 1.0, 0.0)]:
        x, y, w, h = crop_box(1280, 720, zoom, cx, cy)
        assert 0 <= x and x + w <= 1280 and 0 <= y and y + h <= 720
        assert w / h == pytest.approx(ASPECT, rel=0.02)


def test_crop_box_zoom_shrinks_and_centres():
    _, _, w1, h1 = crop_box(1280, 720, 1, 0.5, 0.5)
    x, y, w2, h2 = crop_box(1280, 720, 2, 0.5, 0.5)
    assert h1 == 720 and h2 == 360
    assert (x + w2 / 2, y + h2 / 2) == pytest.approx((640, 360), abs=1)


def test_to_frame_maps_row_to_day_and_column_to_month():
    lit = np.zeros((ROWS, COLS), bool)
    lit[0, 0] = lit[30, 11] = lit[29, 1] = True  # Feb has no day 30
    assert to_frame(lit).lit() == [(1, 1), (12, 31)]


def test_binarize_level_lights_more():
    values = np.linspace(0, 1, ROWS * COLS).reshape(ROWS, COLS)
    assert binarize(values, "edge", 0.8).sum() > binarize(values, "edge", 0.2).sum()
    flat = np.full((ROWS, COLS), 0.5)
    assert binarize(flat, "dither", 1.0).all() and not binarize(flat, "dither", 0.0).any()


def test_dither_preserves_mean_brightness():
    out = dither(np.full((ROWS, COLS), 0.25))
    assert out.mean() == pytest.approx(0.25, abs=0.03)


def test_fields_have_pad_shape_and_range():
    crop = np.random.default_rng(0).integers(0, 255, (310, 275), dtype=np.uint8)
    for mode in mirror.MODES:
        f = field(crop, mode)
        assert f.shape == (ROWS, COLS) and f.min() >= 0 and f.max() <= 1


def test_flat_frame_lights_no_edges():
    assert not binarize(field(np.full((310, 275), 90, np.uint8), "edge"), "edge", 0.5).any()


def test_pick_camera_by_name_and_default_skips_virtual():
    names = ["OBS Virtual Camera", "MacBook Pro Camera", "iPhone Camera"]
    assert pick_camera(None, names) == 1
    assert pick_camera("iphone", names) == 2
    assert pick_camera("2", names) == 2
    with pytest.raises(SystemExit):
        pick_camera("nope", names)
