"""Before->after hook, lineup finale, background-locked motion prompts and colour match."""
import numpy as np
import pytest
from PIL import Image
import urban_core as core
from conftest import frame_at


@pytest.fixture(scope="module")
def beats120():
    y, sr = core.click_track(120, 14)
    return core.detect_beats(y, sr, prefer_librosa=False)


def test_plan_with_hook_and_lineup(beats120):
    p = core.plan_cuts(beats120, 4, 10.0, start=0.0, hook=True, lineup=True)
    kinds = [s["kind"] for s in p["segments"]]
    assert kinds[0] == "before" and kinds[-1] == "lineup" and kinds.count("look") >= 4
    assert p["segments"][0]["t1"] == pytest.approx(1.0, abs=0.02)            # the hook lasts 2 beats
    lu = p["segments"][-1]
    assert abs(lu["t0"] / 2.0 - round(lu["t0"] / 2.0)) * 2.0 < 0.02           # starts on a bar line (4 beats = 2 s)
    assert np.allclose(np.diff(lu["pops"]), 0.5, atol=0.02)                  # one tile per beat
    looks = [s["look"] for s in p["segments"] if s["kind"] == "look"]
    assert looks[:4] == [0, 1, 2, 3] and not p["skipped"]


def test_short_reel_skips_lineup_with_a_note(beats120):
    p = core.plan_cuts(beats120, 5, 5.0, start=0.0, hook=True, lineup=True)
    assert p["segments"][-1]["kind"] != "lineup" and any("lineup" in x for x in p["skipped"])
    assert {s["look"] for s in p["segments"] if s["kind"] == "look"} == set(range(5))


def test_lineup_layouts_fit_the_frame():
    for n in (2, 3, 4, 5):
        for W, H in core.ASPECTS.values():
            for x, y, w, h in core.lineup_boxes(n, W, H):
                assert x >= 0 and y >= 0 and x + w <= W and y + h <= H


def test_render_hook_and_lineup(tmp_path, clips, click_wav):
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, length=10.0)
    before = Image.new("RGB", (720, 1280), (90, 90, 90))
    r = core.render([{"clip": c} for c in clips], beats, tmp_path / "h.mp4", tmp_path / "w", brief, music_path=click_wav, before=before)
    assert r["hook"] and r["lineup"] and r["cuts"][0]["kind"] == "before"
    lu = r["cuts"][-1]
    for t in lu["pops"]:                                                     # every pop on a detected beat (±1 frame)
        assert np.min(np.abs(np.array(r["beat_times_in_reel"]) - t)) <= 1 / 30 + 1e-6
    first = frame_at(tmp_path / "h.mp4", "first")
    assert abs(first.mean() - 90) < 6                                        # the reel opens on the before photo
    assert np.abs(first - frame_at(tmp_path / "h.mp4", "last")).mean() < 3   # and loops back to it
    assert abs(core.probe(tmp_path / "h.mp4")["dur"] - 10.0) <= 0.1


def test_kling_motion_prompt_locks_the_background():
    b = core.make_brief(consent=True)                                       # Kling try-on
    for k in range(1, 6):
        mp = core.motion_prompt(b, k)
        assert "street" not in mp and "Same background" in mp
    nb = core.make_brief(consent=True, look_engine=core.LOOK_ENGINES[1])    # Nano Banana restages in the vibe's setting
    assert "city street" in core.motion_prompt(nb, 1)
    assert "background change" in core.NEGATIVE


def test_colour_match_pulls_toward_reference():
    rng = np.random.default_rng(0)
    ref = rng.integers(60, 120, (4, 32, 18, 3)).astype(np.uint8)
    off = np.clip(ref.astype(int) + [70, 20, -30], 0, 255).astype(np.uint8)
    m = core.match_colour(off, ref, strength=0.6)
    for c in range(3):
        assert abs(m[..., c].mean() - ref[..., c].mean()) < abs(off[..., c].mean() - ref[..., c].mean())


def test_drift_guard_cuts_a_clip_where_the_background_changes():
    rng = np.random.default_rng(1)
    studio = np.full((90, 128, 72 * 3, 3), 180, np.uint8)   # wide enough for the side strips
    studio[:, 30:100, 100:130] = rng.integers(0, 255, (90, 70, 30, 3))   # the person moving in the middle
    walked = studio.copy()
    walked[55:] = rng.integers(0, 255, walked[55:].shape)                      # new place from frame 55
    assert core.drift_cut(studio) == 90
    assert 50 <= core.drift_cut(walked) <= 56
