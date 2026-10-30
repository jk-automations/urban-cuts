"""What a fashion shop needs: shoppable look tags, a branded numbered lineup, and the glow-up and beat pulse."""
import json
import numpy as np
import pytest
from PIL import Image
import urban_core as core
from conftest import frame_at


def test_parse_labels():
    assert core.parse_labels("Rust bomber | $89\nCream knit\n\n") == ["Rust bomber · $89", "Cream knit"]
    assert core.parse_labels("") == []


@pytest.mark.parametrize("aspect", list(core.ASPECTS))
def test_tag_and_bands_fit_the_frame(aspect):
    W, H = core.ASPECTS[aspect]
    tag = core.look_tag_png(3, "A very long product name that keeps going and going | $1,299", W)
    assert int(W * 0.05) + tag.width <= W and int(H * 0.72) + tag.height <= H * 0.85   # clear of the bottom UI
    top, bot = core.brand_bands(W, H, {"name": "Sample Shop", "handle": "@yourshop", "cta": ""}, None, numbered=True)
    boxes = core.lineup_boxes(4, W, H, top=top.height, bottom=bot.height)
    assert all(y >= top.height and y + h <= H - bot.height for _, y, _, h in boxes)


@pytest.fixture(scope="module")
def shop_reel(tmp_path_factory, clips, click_wav):
    d = tmp_path_factory.mktemp("shop")
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, look_labels="Rust bomber | $89\nCream knit | $64\nNavy suit | $210\nPleat skirt | $58",
                            brand_name="Sample Shop", handle="@yourshop")
    before = Image.new("RGB", (720, 1280), (90, 90, 90))
    logo = Image.new("RGB", (300, 120), (226, 140, 92))
    r = core.render([{"clip": c} for c in clips], beats, d / "s.mp4", d / "w", brief, music_path=click_wav, before=before, logo=logo)
    return d / "s.mp4", r


def test_shop_receipt_and_timing(shop_reel):
    path, r = shop_reel
    assert r["look_labels"][0] == "Rust bomber · $89" and r["brand"]["name"] == "Sample Shop" and r["logo"]
    assert r["glowup"] and r["pulse"] and r["cuts"][1]["fx"] == "glow-up"
    p = core.probe(path)
    assert abs(p["dur"] - 10.0) <= 0.1
    assert np.abs(frame_at(path, "first") - frame_at(path, "last")).mean() < 3   # still loops


def test_tag_is_on_screen_during_a_look(shop_reel):
    path, r = shop_reel
    look = next(c for c in r["cuts"] if c["kind"] == "look" and c["look"] == 2)
    fr = core.read_frames(path, 720, 1280, 30, 12)
    i = int(round((look["start"] + 0.2) * 30))
    box = fr[i][int(1280 * 0.72):int(1280 * 0.72) + 40, 36:120].astype(float)
    assert np.abs(box - np.array([18, 16, 14])).mean() < 60   # the dark tag card sits there


def test_glow_up_stutters_back_to_before(shop_reel):
    path, r = shop_reel
    fr = core.read_frames(path, 720, 1280, 30, 12)
    f0 = int(round(r["cuts"][1]["start"] * 30))
    assert abs(fr[f0 + 1].mean() - 90) < 8      # 2nd frame of the hit flips back to the before photo
    assert abs(fr[f0 + 2].mean() - 90) > 8      # 3rd is the look again
