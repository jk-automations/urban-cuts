"""The beat-cut edit: cuts on beats, exact length, seamless loop, loudness, product mode, free draft."""
import json
import numpy as np
import pytest
from PIL import Image
import urban_core as core
from conftest import frame_at, loudness


def test_every_cut_lands_on_a_beat(motion_reel):
    r = motion_reel["receipt"]
    beats_in_reel = np.array(r["beat_times_in_reel"])
    assert len(r["cut_times"]) >= 8
    for c in r["cut_times"]:
        assert np.min(np.abs(beats_in_reel - c)) < 1e-3
        # and on the encoded frame grid: the cut frame is within one frame (33 ms at 30 fps) of the beat
        assert abs(round(c * r["fps"]) / r["fps"] - c) <= 0.5 / r["fps"] + 1e-6
    true_beats = np.arange(0, 14, 0.5) - r["music_start"]
    for c in r["cut_times"]:
        assert np.min(np.abs(true_beats - c)) < 0.020, "within 20 ms of the real click"


def test_duration_within_a_tenth(motion_reel):
    p = core.probe(motion_reel["path"])
    assert abs(p["dur"] - 10.0) <= 0.1 and p["audio"]
    assert (p["w"], p["h"]) == (720, 1280)


def test_first_and_last_frame_match_so_it_loops(motion_reel):
    a, b = frame_at(motion_reel["path"], "first"), frame_at(motion_reel["path"], "last")
    assert np.abs(a - b).mean() < 3.0   # identical before H.264; only codec noise left
    # before encoding the two frames are exactly equal (the loop blend ends on frame 0)
    raw = np.load(motion_reel["path"].parent / "work" / "first_last.npy")
    assert np.array_equal(raw[0], raw[1])


def test_loudness_minus_14_lufs_and_true_peak(tmp_path):
    """On real-sounding music (a bare click track is too peaky to reach -14 LUFS under -1 dBTP)."""
    y, sr = core.sample_beat()
    wav = core.write_wav(tmp_path / "beat.wav", y, sr)
    brief = core.make_brief(consent=True, length=8.0)
    looks = [{"still": Image.new("RGB", (720, 1280), c)} for c in [(200, 60, 60), (60, 90, 200)]]
    core.render(looks, core.detect_beats(y, sr), tmp_path / "l.mp4", tmp_path / "w", brief, music_path=wav)
    i, tp = loudness(tmp_path / "l.mp4")
    assert abs(i - (-14)) <= 1.0
    assert tp <= -1.0


def test_receipt_has_bpm_beats_and_cut_list(motion_reel):
    r = motion_reel["receipt"]
    assert abs(r["bpm"] - 120) < 1
    assert r["cuts"][0]["start"] == 0.0 and r["cuts"][-1]["end"] == 10.0
    assert {c["fx"] for c in r["cuts"]} <= {"punch", "flash", "whip"}
    assert r["label"] == "AI-generated"
    json.dumps({k: v for k, v in r.items() if k != "_thumbs"})


def test_product_mode_with_headline(tmp_path, clips, click_wav):
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(mode="products", vibe="boutique", length=8.0, aspect="4:5", headline="New arrivals", consent=True)
    assert brief["engine"] == "banana"                     # products always go through the Nano Banana 2 edit
    assert "presenting the product from Image 2" in core.look_prompt(brief, 1)
    assert "holding the product" in core.motion_prompt(brief, 2)
    r = core.render([{"clip": c} for c in clips[:3]], beats, tmp_path / "p.mp4", tmp_path / "w", brief, music_path=click_wav)
    p = core.probe(tmp_path / "p.mp4")
    assert abs(p["dur"] - 8.0) <= 0.1 and (p["w"], p["h"]) == (864, 1080)
    assert r["headline"] == "New arrivals" and max(c["look"] for c in r["cuts"]) == 3


def test_free_draft_stills_ken_burns(tmp_path, click_wav):
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, vibe="runway", length=6.0)
    looks = [{"still": Image.new("RGB", (720, 1280), c)} for c in [(200, 60, 60), (60, 160, 90), (60, 90, 200)]]
    r = core.render(looks, beats, tmp_path / "d.mp4", tmp_path / "w", brief, music_path=click_wav, labels={"label": "Free draft"})
    assert abs(core.probe(tmp_path / "d.mp4")["dur"] - 6.0) <= 0.1 and r["label"] == "Free draft"


def test_consent_is_required():
    with pytest.raises(ValueError, match="consent"):
        core.make_brief(consent=False)


def test_cost_estimate_matches_price_badges():
    b = core.make_brief(consent=True, music_source=core.MUSIC_SOURCES[1])
    c = core.cost_estimate(b, 4)
    assert c["total_usd"] == pytest.approx(4 * 0.16016 + 4 * 3 * 0.084 + 15 * 0.0025, abs=1e-3)
    assert core.cost_estimate(b, 4, generated_motion=False)["total_usd"] == 0.0
