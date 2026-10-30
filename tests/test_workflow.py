"""The shipped graphs: App Mode workflows (made by tools/make_app.mjs in the real ComfyUI frontend), the API graphs,
and a check against the live /object_info of the project's own ComfyUI (:8197). Nothing here queues a paid node."""
import json, os, subprocess, sys, urllib.request, uuid, time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / "workflows"
URL = os.environ.get("URBAN_COMFY_URL", "http://127.0.0.1:8197")
PAID = {"KlingTryOnNode", "GeminiNanoBanana2V2", "KlingVideoNode", "SoniloTextToMusic"}


def live():
    try:
        urllib.request.urlopen(f"{URL}/object_info/UrbanBeatCut", timeout=5)
        return True
    except Exception:
        return False


def load(name):
    wf = json.loads((WF / name).read_text())
    return wf, {n["id"]: n for n in wf["nodes"]}


@pytest.mark.parametrize("name", ["urban-cuts.json", "urban-cuts-draft.json"])
def test_opens_in_app_mode_with_the_form(name):
    wf, nodes = load(name)
    assert wf["extra"]["linearMode"] is True
    names = [(nodes[i]["type"], w) for i, w in wf["extra"]["linearData"]["inputs"]]
    for w in ("consent", "mode", "vibe", "length", "aspect", "headline"):
        assert ("UrbanBrief", w) in names
    assert sum(t == "LoadImage" for t, _ in names) >= 6   # person + 5 outfit/product slots
    outs = sorted(nodes[i]["title"] for i in wf["extra"]["linearData"]["outputs"])
    assert outs == ["Beats", "Contact sheet", "Receipt", "Your reel"]
    assert not any("randomize" in (n.get("widgets_values") or []) for n in wf["nodes"]), "a re-run must reuse paid steps"


def test_partner_graph_shape():
    g = json.loads((WF / "urban-cuts-api.json").read_text())
    types = [n["class_type"] for n in g.values()]
    for t, n in [("KlingTryOnNode", 5), ("GeminiNanoBanana2V2", 5), ("KlingVideoNode", 5), ("SoniloTextToMusic", 1)]:
        assert types.count(t) == n
    for n in g.values():
        if n["class_type"] == "KlingVideoNode":
            i = n["inputs"]
            assert i["model"] == "kling-v3" and i["model.resolution"] == "720p" and i["generate_audio"] is False
            assert i["multi_shot.duration"] == 3
        if n["class_type"] == "UrbanBrief":
            assert n["inputs"]["consent"] is False, "the user must tick consent themselves"
    # no paid node is an output (only lazy inputs of Beat Cut pull them)
    outputs = [n for n in g.values() if n["class_type"] in ("SaveVideo", "PreviewImage", "PreviewAny", "SaveImage", "SaveAudio")]
    assert all(n["inputs"].get("video", n["inputs"].get("images", n["inputs"].get("source")))[0] not in
               [k for k, v in g.items() if v["class_type"] in PAID] for n in outputs)


def test_draft_graph_is_free():
    g = json.loads((WF / "urban-cuts-draft-api.json").read_text())
    assert not {n["class_type"] for n in g.values()} & PAID


@pytest.mark.skipif(not live(), reason="project ComfyUI on :8197 is not running")
@pytest.mark.parametrize("name", ["urban-cuts-api.json", "urban-cuts-draft-api.json"])
def test_graph_against_live_object_info(name):
    r = subprocess.run([sys.executable, str(ROOT / "tools/check_graph.py"), str(WF / name), "--url", URL], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(not live(), reason="project ComfyUI on :8197 is not running")
def test_live_run_stops_at_the_consent_gate():
    g = json.loads((WF / "urban-cuts-draft-api.json").read_text())   # free graph, consent left off
    req = urllib.request.Request(f"{URL}/prompt", data=json.dumps({"prompt": g, "client_id": str(uuid.uuid4())}).encode(),
                                 headers={"Content-Type": "application/json"})
    pid = json.load(urllib.request.urlopen(req, timeout=30))["prompt_id"]
    for _ in range(120):
        h = json.load(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30))
        if pid in h and h[pid]["status"].get("completed") is not None:
            break
        time.sleep(1)
    st = h[pid]["status"]
    assert st["status_str"] == "error"
    err = [m[1] for m in st["messages"] if m[0] == "execution_error"][0]
    assert err["node_type"] == "UrbanBrief" and "consent" in err["exception_message"]
    assert not h[pid]["outputs"], "nothing was made"
