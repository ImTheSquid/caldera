import animate
from animate import Editor, load, save
from caldera import Frame


def drag(editor, *pads):
    for pad in pads:
        editor.contact(pad)
    editor.release()


def test_tap_toggles_and_drag_paints_with_first_pad_value():
    ed = Editor([])
    drag(ed, (3, 3))
    assert ed.work.lit() == [(3, 3)]
    drag(ed, (1, 1), (1, 4))  # gap filled
    assert ed.work.lit() == [(1, 1), (1, 2), (1, 3), (1, 4), (3, 3)]
    drag(ed, (1, 2), (1, 4))  # starts on a lit pad, so erases
    assert ed.work.lit() == [(1, 1), (3, 3)]


def test_drag_skips_missing_pads():
    ed = Editor([])
    drag(ed, (2, 27), (2, 31))  # Feb has no 29-31
    assert ed.work.lit() == [(2, 27), (2, 28)]


def test_store_continues_on_a_copy():
    ed = Editor([])
    drag(ed, (5, 5))
    ed.store()
    drag(ed, (6, 6))
    assert [f.lit() for f in ed.result()] == [[(5, 5)], [(5, 5), (6, 6)]]


def test_undo_strokes_then_frames():
    ed = Editor([])
    drag(ed, (5, 5))
    ed.store()
    drag(ed, (6, 6))
    assert ed.undo() == "undid stroke"
    assert [f.lit() for f in ed.result()] == [[(5, 5)]]  # nothing unstored
    assert ed.undo() == "editing frame 1"
    assert ed.frames == [] and ed.result()[0].lit() == [(5, 5)]  # taken back, not lost
    assert ed.undo() == "nothing to undo"


def test_save_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(animate, "DIR", tmp_path)
    frames = [Frame([1 << m for m in range(12)]), Frame()]
    save("spooky", frames, 12.0)
    assert load("spooky") == (frames, 12.0)
    assert load("missing") == ([], None)
