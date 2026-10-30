import json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def make_clip(path, secs=3.0, w=720, h=1280, hue=0):
    """A dummy 'generated' look clip: an ffmpeg test pattern (no AI generation)."""
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate=24:duration={secs}",
                    "-vf", f"hue=h={hue}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return Path(path)


def frame_at(path, which):
    """First or last decoded frame of an MP4 as float array."""
    p = core.probe(path)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, p["h"], p["w"], 3)
    return fr[0 if which == "first" else -1].astype(np.float32)


def loudness(path):
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    s = err[err.rindex("Summary:"):]
    i = float(s.split("I:")[1].split("LUFS")[0])
    tp = float(s.split("Peak:")[1].split("dBFS")[0])
    return i, tp


@pytest.fixture(scope="session")
def click_wav(tmp_path_factory):
    y, sr = core.click_track(120, 14)
    return core.write_wav(tmp_path_factory.mktemp("music") / "click120.wav", y, sr)


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    return [make_clip(d / f"c{k}.mp4", 3.0, hue=k * 70) for k in range(4)]


@pytest.fixture(scope="session")
def motion_reel(tmp_path_factory, clips, click_wav):
    """A full edit with generated-motion looks (test-pattern clips stand in for Kling) on a 120 BPM click track."""
    d = tmp_path_factory.mktemp("reel")
    a, sr = core.read_wav(click_wav)
    beats = core.detect_beats(a, sr)
    brief = core.make_brief(consent=True, vibe="street", length=10.0)
    r = core.render([{"clip": c} for c in clips], beats, d / "reel.mp4", d / "work", brief, music_path=click_wav)
    return {"path": d / "reel.mp4", "receipt": r, "beats": beats}


@pytest.fixture(scope="session")
def comfy_path():
    p = Path(os.environ.get("COMFYUI_DIR", Path.home() / "ComfyUI"))
    if not (p / "comfy_api").exists():
        pytest.skip("ComfyUI not found (set COMFYUI_DIR)")
    sys.path.insert(0, str(p))
    return p
