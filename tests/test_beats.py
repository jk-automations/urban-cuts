"""Beat Detect on synthetic click tracks with known beat times."""
import numpy as np
import pytest
import urban_core as core


@pytest.mark.parametrize("bpm", [120, 97, 128, 140])
def test_click_track_beats_within_20ms(bpm):
    y, sr = core.click_track(bpm, 12)
    b = core.detect_beats(y, sr, prefer_librosa=False)
    truth = np.arange(0, 12 - 0.02, 60 / bpm)
    got = np.array(b["beats"])
    assert abs(b["bpm"] - bpm) < 1.0
    assert max(np.min(np.abs(truth - t)) for t in got) < 0.020, "every detected beat is a real click"
    assert max(np.min(np.abs(got - t)) for t in truth[1:-1]) < 0.020, "every click is found"


def test_downbeats_follow_the_bar_accent():
    y, sr = core.click_track(120, 12)   # the louder click is on beat 1 of every bar: 0, 2, 4, ... s
    b = core.detect_beats(y, sr, prefer_librosa=False)
    assert np.allclose(b["downbeats"][:4], [0, 2, 4, 6], atol=0.02)


def test_sample_beat_is_found():
    y, sr = core.sample_beat(bpm=112)
    b = core.detect_beats(y, sr, prefer_librosa=False)
    assert abs(b["bpm"] - 112) < 1.5


def test_too_short_or_beatless_music_is_refused():
    with pytest.raises(ValueError):
        core.detect_beats(np.zeros((2, 1000)), 44100)


def test_plan_cuts_every_two_beats_from_a_downbeat():
    y, sr = core.click_track(120, 14)
    b = core.detect_beats(y, sr, prefer_librosa=False)
    p = core.plan_cuts(b, 4, 10.0)
    assert p["music_start"] in b["downbeats"]
    assert np.allclose(np.diff([0.0] + p["cuts"]), 1.0, atol=0.02)   # 2 beats at 120 BPM = 1 s
    assert [s["look"] for s in p["segments"][:5]] == [0, 1, 2, 3, 0]
    assert p["segments"][-1]["t1"] == 10.0


def test_a_tracker_slip_does_not_shift_later_cuts():
    """Seen on the paid demo's Sonilo track: the tracker added a half-beat near the end. Cuts must stay on the grid."""
    y, sr = core.click_track(120, 14)
    b = core.detect_beats(y, sr, prefer_librosa=False)
    bad = dict(b, beats=sorted(b["beats"] + [8.25]))
    bad["beats"] = [t for t in bad["beats"] if abs(t - 9.0) > 0.05]   # and a missed beat
    p = core.plan_cuts(bad, 4, 10.0, start=0.0)
    assert np.allclose(p["cuts"], np.arange(1, 10), atol=0.03)
    assert p["snapped"].count("grid") == 1
