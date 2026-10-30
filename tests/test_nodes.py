"""The ComfyUI nodes, with the partner nodes mocked (nothing is generated, nothing is billed)."""
import json
import shutil
import numpy as np
import pytest
import torch
import urban_core as core


@pytest.fixture(scope="module")
def nodes(comfy_path):
    import urban_nodes
    return urban_nodes


class FakeVideo:
    """Stands in for a Kling 3.0 VIDEO output."""
    def __init__(self, path):
        self.path = path

    def save_to(self, dst):
        shutil.copy(self.path, dst)


def img(color, w=72, h=128):
    return torch.tensor(np.full((1, h, w, 3), np.array(color) / 255.0, dtype=np.float32))


def textured(seed, w=72, h=128):
    return torch.rand((1, h, w, 3), generator=torch.Generator().manual_seed(seed))


BLANK = img((255, 255, 255), 64, 64)


def audio_of(wav):
    a, sr = core.read_wav(wav)
    return {"waveform": torch.from_numpy(a)[None], "sample_rate": sr}


def brief_json(nodes, **kw):
    args = dict(person=textured(0), consent=True, mode="outfits", vibe="street", length=10.0, aspect="9:16",
                look_engine=core.LOOK_ENGINES[0], music_source=core.MUSIC_SOURCES[1], music_prompt="", headline="", ai_label=True)
    args.update(kw)
    return nodes.UrbanBrief().run(**args)


def test_unticked_consent_stops_the_run(nodes):
    with pytest.raises(ValueError, match="consent"):
        brief_json(nodes, consent=False)


def test_brief_outputs(nodes):
    person, brief, engine, mp, secs = brief_json(nodes)
    assert engine == "kling" and secs == 15 and "no vocals" in mp and person.shape == (1, 128, 72, 3)
    assert brief_json(nodes, mode="products")[2] == "banana"
    assert brief_json(nodes, look_engine=core.LOOK_ENGINES[1])[2] == "banana"


def test_only_the_picked_look_engine_runs(nodes):
    p = nodes.UrbanPickLook()
    assert p.check_lazy_status("kling", kling=None, banana=None) == ["kling"]
    assert p.check_lazy_status("banana", kling=None, banana=None) == ["banana"]
    a = textured(1)
    assert p.check_lazy_status("kling", kling=a, banana=None) == []
    assert p.run("kling", kling=a)[0] is a


def test_sonilo_only_runs_when_picked(nodes):
    m = nodes.UrbanMusic()
    up = json.dumps({"music": "upload"}); so = json.dumps({"music": "sonilo"})
    assert m.check_lazy_status(up, uploaded=None, sonilo=None) == ["uploaded"]
    assert m.check_lazy_status(so, uploaded=None, sonilo=None) == ["sonilo"]


def test_blank_slots_never_request_paid_nodes(nodes):
    cut = nodes.UrbanBeatCut()
    kw = {}
    for k in range(1, 6):
        kw[f"item_{k}"] = textured(k) if k <= 3 else BLANK
        kw[f"look_{k}"] = None
        kw[f"clip_{k}"] = None
    need = cut.check_lazy_status("{}", None, "{}", **kw)
    assert sorted(need) == sorted([f"look_{k}" for k in (1, 2, 3)] + [f"clip_{k}" for k in (1, 2, 3)])


def test_beat_detect_node(nodes, click_wav):
    beats, txt = nodes.UrbanBeatDetect().run(audio_of(click_wav))
    assert abs(json.loads(beats)["bpm"] - 120) < 1 and "BPM" in txt


def test_mocked_partner_pipeline(nodes, clips, click_wav, tmp_path):
    """Kling try-on / video replaced by test images and test-pattern clips: the full node chain cuts the reel."""
    _, brief, engine, _, _ = brief_json(nodes)
    music = audio_of(click_wav)
    beats, _ = nodes.UrbanBeatDetect().run(music)
    kw = {}
    for k in range(1, 6):
        kw[f"item_{k}"] = textured(10 + k) if k <= 4 else BLANK
        if k <= 4:
            kw[f"look_{k}"] = nodes.UrbanPickLook().run(engine, kling=textured(20 + k))[0]
            kw[f"clip_{k}"] = FakeVideo(clips[k - 1])
    video, sheet, receipt = nodes.UrbanBeatCut().run(brief, music, beats, **kw)
    r = json.loads(receipt)
    assert r["looks_used"] == [1, 2, 3, 4] and r["label"] == "AI-generated"
    assert len(r["partner_calls"]) == 5 and "Sonilo" in r["partner_calls"][-1]
    assert r["cost_estimate"]["total_usd"] == pytest.approx(4 * 0.16016 + 4 * 3 * 0.084 + 15 * 0.0025, abs=1e-3)
    assert sheet.ndim == 4 and sheet.shape[-1] == 3
    video.save_to(str(tmp_path / "reel.mp4"))
    assert abs(core.probe(tmp_path / "reel.mp4")["dur"] - 10) < 0.1


def test_free_draft_node_run(nodes, click_wav):
    _, brief, _, _, _ = brief_json(nodes, music_source=core.MUSIC_SOURCES[0], length=6.0)
    music = audio_of(click_wav)
    beats, _ = nodes.UrbanBeatDetect().run(music)
    kw = {f"item_{k}": textured(k) for k in (1, 2, 3)}
    kw.update({f"look_{k}": textured(30 + k) for k in (1, 2, 3)})
    _, _, receipt = nodes.UrbanBeatCut().run(brief, music, beats, **kw)
    r = json.loads(receipt)
    assert r["partner_calls"] == ["none (free draft)"] and r["cost_estimate"]["total_usd"] == 0.0 and r["label"] == "Free draft"


def test_no_looks_is_refused(nodes, click_wav):
    _, brief, _, _, _ = brief_json(nodes)
    music = audio_of(click_wav)
    beats, _ = nodes.UrbanBeatDetect().run(music)
    with pytest.raises(ValueError, match="at least one"):
        nodes.UrbanBeatCut().run(brief, music, beats, item_1=BLANK)
