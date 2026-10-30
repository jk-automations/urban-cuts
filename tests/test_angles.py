"""Camera angles: one Kling storyboard per look (3 s turnaround + 2 s close-up), cut on the beat."""
import subprocess
import numpy as np
import pytest
from PIL import Image
import urban_core as core
from conftest import FFMPEG


def storyboard_clip(path, body, fps=24):
    """A stand-in for a Kling storyboard: 3 s full body (grey studio, a 'person' block that turns) + 2 s close-up."""
    W, H = 360, 640
    frames = []
    for i in range(3 * fps):
        f = np.full((H, W, 3), 175, np.uint8)
        w = int(60 + 40 * abs(np.cos(np.pi * i / (3 * fps))))          # the block narrows and widens as it turns
        f[150:560, W // 2 - w:W // 2 + w] = body
        frames.append(f)
    for i in range(2 * fps):
        f = np.zeros((H, W, 3), np.uint8); f[:] = body                  # close-up: the fabric fills the frame
        f[::8] = np.clip(np.array(body) + 30, 0, 255)                   # a little texture
        frames.append(f)
    p = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
                          "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    p.stdin.write(np.stack(frames).tobytes()); p.stdin.close(); p.wait()
    return path


@pytest.fixture(scope="module")
def angle_reel(tmp_path_factory, click_wav):
    d = tmp_path_factory.mktemp("angles")
    bodies = [(200, 90, 50), (230, 220, 200), (40, 60, 120), (240, 190, 60)]
    clips = [storyboard_clip(d / f"a{k}.mp4", b) for k, b in enumerate(bodies)]
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, length=15.0, angles=True)
    before = Image.new("RGB", (720, 1280), (90, 90, 90))
    r = core.render([{"clip": c} for c in clips], beats, d / "r.mp4", d / "w", brief, music_path=click_wav, before=before)
    return d / "r.mp4", r


def test_plan_turnaround_then_closeup(click_wav):
    a, sr = core.read_wav(click_wav)
    b = core.detect_beats(a, sr)
    p = core.plan_cuts(b, 4, 15.0, start=0.0, hook=True, lineup=True, pattern=core.ANGLE_PATTERN)
    looks = [s for s in p["segments"] if s["kind"] == "look"]
    assert [(s["look"], s["shot"]) for s in looks[:8]] == [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)]
    turn = looks[0]
    assert turn["t1"] - turn["t0"] == pytest.approx(2.0, abs=0.03)   # 4 beats at 120 BPM
    assert p["segments"][-1]["kind"] == "lineup" and not p["skipped"]


def test_angle_reel(angle_reel):
    path, r = angle_reel
    assert abs(core.probe(path)["dur"] - 15.0) <= 0.1
    shots = [(c["look"], c["kind"]) for c in r["cuts"] if c["kind"] == "look"]
    assert len(shots) == 8
    assert not any(str(k).endswith(".2") for k in r["drift_trimmed"]), "the close-up is a new camera, not drift"


def test_angle_prompts():
    b = core.make_brief(consent=True, angles=True)
    turn, close = core.angle_prompts(b, 1)
    assert "360" in turn and "back of the outfit" in turn and "street" not in turn
    assert "Close-up" in close and len(turn) <= 512 and len(close) <= 512
    p = core.make_brief(consent=True, angles=True, mode="products")
    assert "product" in core.angle_prompts(p, 1)[0]


def test_angles_cost():
    b = core.make_brief(consent=True, angles=True, music_source=core.MUSIC_SOURCES[1], length=15.0)
    c = core.cost_estimate(b, 4)
    assert c["total_usd"] == pytest.approx(4 * 0.16016 + 4 * 5 * 0.084 + 20 * 0.0025, abs=1e-3)


def test_colour_match_keeps_garment_colour():
    ref = np.full((2, 640, 360, 3), 180, np.uint8)
    look = np.full((2, 640, 360, 3), 150, np.uint8)            # darker, same white balance
    look[:, 200:500, 120:240] = (200, 60, 40)                   # a red jacket in the middle
    m = core.match_colour(look, ref).astype(float)
    assert m[0, 10, 10].mean() > 165                             # the background brightens toward the reference
    red = m[0, 300, 180]
    assert red[0] > 2.5 * red[1] and red[0] > 3 * red[2]         # the jacket stays red (hue kept, not pulled to grey)
