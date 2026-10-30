"""Run a graph WITH partner (paid) nodes on a running ComfyUI, under a hard spend cap. Only for a founder-approved demo.

The cost of the run is estimated from the nodes' own price badges before queueing. The run is refused if the estimate
plus everything already in the ledger (runs/paid/ledger.jsonl) would go over --cap. The Comfy API key is read from a
file and sent only in extra_data; it is never printed or written anywhere.

python3 tools/run_paid.py --graph workflows/urban-cuts-api.json --cap 3.0 --consent [--set ...] [--image ...] --out runs/paid/demo"""
import argparse, json, shutil, sys, time, urllib.error, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8197")
ap.add_argument("--comfy-base", default=str(ROOT / ".comfy-base"))
ap.add_argument("--graph", required=True)
ap.add_argument("--cap", type=float, required=True, help="founder-approved total cap in USD for all paid runs in the ledger")
ap.add_argument("--key-file", default=str(Path.home() / ".config/jk/comfy_api_key"))
ap.add_argument("--ledger", default=str(ROOT / "runs/paid/ledger.jsonl"))
ap.add_argument("--out", required=True)
ap.add_argument("--label", default="")
ap.add_argument("--consent", action="store_true")
ap.add_argument("--set", action="append", default=[])
ap.add_argument("--image", action="append", default=[])
ap.add_argument("--timeout", type=int, default=1800)
a = ap.parse_args()

g = json.loads(Path(a.graph).read_text())
for kv in a.set:
    k, v = kv.split("=", 1)
    b = next(n for n in g.values() if n["class_type"] == "UrbanBrief")["inputs"]
    old = b[k]
    b[k] = float(v) if isinstance(old, float) else (v.lower() == "true" if isinstance(old, bool) else v)
for kv in a.image:
    title, f = kv.split("=", 1)
    next(n for n in g.values() if n.get("_meta", {}).get("title") == title)["inputs"]["image"] = f
brief_node = next((n for n in g.values() if n["class_type"] == "UrbanBrief"), None)
if brief_node:
    brief_node["inputs"]["consent"] = bool(a.consent)

# ---- estimate (worst case: nothing cached)
types = [n["class_type"] for n in g.values()]
if brief_node:
    bi = brief_node["inputs"]
    b = core.make_brief(bi["mode"], bi["vibe"], bi["length"], bi["aspect"], bi["look_engine"], bi["music_source"],
                        bi["music_prompt"], bi["headline"], True, bi["ai_label"], bi.get("hook", True), bi.get("lineup", True),
                        bi.get("look_labels", ""), bi.get("brand_name", ""), bi.get("handle", ""), bi.get("cta", ""),
                        bi.get("pulse", True), bi.get("glowup", True), bi.get("angles", False),
                        bi.get("style", "hype"), bi.get("set", core.SETS[0]), bi.get("prices", True))
    used = sum(1 for n in g.values() if n.get("_meta", {}).get("title", "").startswith("Outfit or product")
               and n["inputs"]["image"] != "urban_blank.png")
    est = core.cost_estimate(b, used)["total_usd"]
else:
    unknown = {t for t in types if t not in ("GeminiNanoBanana2V2", "KlingVideoNode", "SoniloTextToMusic", "SaveImage", "SaveVideo",
                                             "SaveAudio", "PreviewImage", "LoadImage")}
    if unknown:
        sys.exit(f"refusing: no price rule for {unknown}")
    kling = [n["inputs"] for n in g.values() if n["class_type"] == "KlingVideoNode"]
    if any(i.get("model") != "kling-v3" or i.get("model.resolution") != "720p" or i.get("generate_audio") for i in kling):
        sys.exit("refusing: only kling-v3 720p without audio has a price rule here")
    est = round(types.count("GeminiNanoBanana2V2") * core.PRICES["GeminiNanoBanana2V2_1K_minimal"]
                + sum(core.PRICES["KlingVideoNode_720p_per_s"] * (i.get("multi_shot.duration") or sum(
                    v for kk, v in i.items() if kk.startswith("multi_shot.storyboard_") and kk.endswith("_duration"))) for i in kling)
                + sum(core.PRICES["SoniloTextToMusic_per_s"] * n["inputs"]["duration"] for n in g.values()
                      if n["class_type"] == "SoniloTextToMusic"), 4)
ledger = Path(a.ledger); ledger.parent.mkdir(parents=True, exist_ok=True)
spent = sum(json.loads(l)["estimate_usd"] for l in ledger.read_text().splitlines() if l.strip()) if ledger.exists() else 0.0
print(f"estimate ${est:.4f}; ledger so far ${spent:.4f}; cap ${a.cap:.2f}", flush=True)
if spent + est > a.cap + 1e-9:
    sys.exit("refusing: this run would go over the approved cap")

key = Path(a.key_file).expanduser().read_text().strip()
body = {"prompt": g, "client_id": str(uuid.uuid4()), "extra_data": {"api_key_comfy_org": key}}
try:
    pid = json.load(urllib.request.urlopen(urllib.request.Request(f"{a.url}/prompt", data=json.dumps(body).encode(),
                                                                 headers={"Content-Type": "application/json"}), timeout=60))["prompt_id"]
except urllib.error.HTTPError as e:
    sys.exit(f"rejected: {e.read().decode()[:2000]}")
del key, body
with ledger.open("a") as f:   # written at queue time: a failed run may still have billed some nodes
    f.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "prompt_id": pid, "graph": Path(a.graph).name,
                        "label": a.label, "estimate_usd": est}) + "\n")
print("queued", pid, flush=True)
t0 = time.time()
while True:
    h = json.load(urllib.request.urlopen(f"{a.url}/history/{pid}", timeout=60))
    if pid in h and h[pid].get("status", {}).get("completed") is not None:
        break
    if time.time() - t0 > a.timeout:
        sys.exit("timed out (still running on the server)")
    time.sleep(5)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
(out / "history.json").write_text(json.dumps(h[pid], indent=1))
st = h[pid]["status"]
cached = [m[1].get("nodes", []) for m in st.get("messages", []) if m[0] == "execution_cached"]
print("cached nodes:", cached[0] if cached else [])
if st.get("status_str") != "success":
    err = [m[1] for m in st.get("messages", []) if m[0] == "execution_error"]
    print(json.dumps([{"node": e.get("node_type"), "id": e.get("node_id"), "message": e.get("exception_message")} for e in err], indent=1))
    sys.exit("paid run failed")
base = Path(a.comfy_base)
for nid, o in h[pid]["outputs"].items():
    title = g[nid].get("_meta", {}).get("title", nid).replace(" ", "-").lower()
    for kind in ("images", "videos", "audio"):
        for k, f in enumerate(o.get(kind, [])):
            src = base / f.get("type", "output") / f.get("subfolder", "") / f["filename"]
            dst = out / f"{title}{'' if k == 0 else f'-{k}'}{Path(f['filename']).suffix}"
            shutil.copy(src, dst); print("saved", dst)
    if "text" in o:
        (out / f"{title}.txt").write_text("".join(map(str, o["text"])) + "\n"); print("saved", out / f"{title}.txt")
print(f"done in {time.time() - t0:.0f} s")
