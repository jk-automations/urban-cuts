"""Brand style: how fashion brands post (teaser of every look, plain hard cuts, warm grade, small clean text, a handle
card), the white wall room set and the pose-sequence prompts."""
import json
import numpy as np
import pytest
import urban_core as core
from conftest import frame_at
from test_angles import storyboard_clip


@pytest.fixture(scope="module")
def brand_reel(tmp_path_factory, click_wav):
    d = tmp_path_factory.mktemp("brand")
    bodies = [(200, 90, 50), (230, 220, 200), (40, 60, 120), (240, 190, 60)]
    clips = [storyboard_clip(d / f"a{k}.mp4", b) for k, b in enumerate(bodies)]
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, length=15.0, angles=True, style="brand", hook="teaser", lineup=False,
                            look_labels="Rust bomber | $89\nCable knit | $124\nNavy suit | $210\nMustard tee | $76",
                            headline="4 fits, 1 weekend", handle="@yourshop", prices=False)
    r = core.render([{"clip": c} for c in clips], beats, d / "r.mp4", d / "w", brief, music_path=click_wav)
    return d / "r.mp4", r


def test_plan_teaser_then_looks_then_card(click_wav):
    a, sr = core.read_wav(click_wav)
    b = core.detect_beats(a, sr)
    p = core.plan_cuts(b, 4, 15.0, start=0.0, hook="teaser", pattern=core.ANGLE_PATTERN, card=True)
    kinds = [(s["kind"], s["look"]) for s in p["segments"]]
    assert kinds[:4] == [("teaser", 0), ("teaser", 1), ("teaser", 2), ("teaser", 3)]
    assert all(s["t1"] - s["t0"] == pytest.approx(0.5, abs=0.03) for s in p["segments"][:4])   # one beat each at 120 BPM
    assert kinds[4] == ("look", 0) and kinds[-1] == ("card", None)
    assert len([k for k in kinds if k[0] == "look"]) == 8 and p["hook"] == "teaser" and not p["skipped"]


def test_brand_reel_is_clean(brand_reel):
    path, r = brand_reel
    assert abs(core.probe(path)["dur"] - 15.0) <= 0.1
    assert r["style"] == "brand" and r["hook"] == "teaser" and r["card"] and not r["lineup"]
    assert all(c["fx"] is None for c in r["cuts"]), "brand style: plain hard cuts, no flash/whip/punch"
    assert not r["glowup"]
    first, last = frame_at(path, "first"), frame_at(path, "last")
    assert np.abs(first - last).mean() < 6, "still loops"


def test_brand_reel_ends_on_handle_card(brand_reel):
    path, r = brand_reel
    card = next(c for c in r["cuts"] if c["kind"] == "card")
    assert card["end"] == 15.0 and 0.8 <= card["end"] - card["start"] <= 1.6


def test_prices_off_strips_the_price():
    b = core.make_brief(consent=True, look_labels="Rust bomber | $89", prices=False)
    assert b["labels"] == ["Rust bomber · $89"] and b["prices"] is False   # stored; the render drops the price


def test_warm_grade_warms_and_keeps_shape():
    f = np.full((4, 64, 36, 3), 128, np.uint8)
    g = core.warm_grade(f.copy()).astype(float)
    assert g[..., 0].mean() > g[..., 2].mean() + 5 and g.std() > 1   # warmer, with grain


def test_pose_prompts_are_model_driven():
    b = core.make_brief(consent=True, style="brand", angles=True)
    pose, close = core.shot_prompts(b, 1)
    assert "hand on the hip" in pose and "back over the shoulder" in pose and "locked-off camera" in pose
    assert "360" not in pose and "Close-up" in close
    hype = core.shot_prompts(core.make_brief(consent=True, style="hype", angles=True), 1)[0]
    assert "360" in hype


def test_room_set_costs_and_prompt():
    b = core.make_brief(consent=True, angles=True, set=core.SETS[1], music_source=core.MUSIC_SOURCES[1], length=15.0)
    assert b["set"] == "room"
    c = core.cost_estimate(b, 4)
    assert c["total_usd"] == pytest.approx(4 * 0.16016 + 4 * 0.048048 + 4 * 5 * 0.084 + 20 * 0.0025, abs=1e-3)
    p = core.restage_prompt(b, 1)
    assert "white wall" in p and "parquet" in p and "match exactly" in p


def test_bad_style_or_hook_refused():
    with pytest.raises(ValueError):
        core.make_brief(consent=True, style="loud")
    with pytest.raises(ValueError):
        core.make_brief(consent=True, hook="sideways")


def test_text_ink_adapts_to_the_wall():
    assert core.ink_for(np.full((4, 10, 10, 3), 230, np.uint8)) == core.INK_DARK      # light wall: dark text
    assert core.ink_for(np.full((4, 10, 10, 3), 60, np.uint8)) == (255, 255, 255)      # dark area: white text


def test_headline_avoids_the_head():
    H, W = 640, 360
    fr = np.full((3, H, W, 3), 225, np.uint8)
    rng = np.random.default_rng(0)
    fr[:, int(H * 0.10):int(H * 0.22), 120:240] = rng.integers(40, 120, (3, int(H * 0.22) - int(H * 0.10), 120, 3))  # hair/head
    y = core.clear_band(fr, 30, W, H)
    assert y >= int(H * 0.22) and y >= int(H * 0.095)   # below the head, and below the item tag
