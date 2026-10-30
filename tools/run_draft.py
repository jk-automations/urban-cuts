"""Run the FREE draft graph on a running ComfyUI and copy the results out. It refuses any graph that contains a
partner (paid API) node, so it can never spend money. Consent stays off unless you pass --consent (then the run is
yours to vouch for); without it the run must stop at the consent gate.

python3 tools/run_draft.py --url http://127.0.0.1:8197 --consent [--graph workflows/urban-cuts-draft-api.json] [--out runs/draft]
                           [--set mode=products] [--set vibe=runway] [--set headline="New arrivals"]"""
import argparse, json, shutil, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8197")
ap.add_argument("--comfy-base", default=str(ROOT / ".comfy-base"))
ap.add_argument("--graph", default=str(ROOT / "workflows/urban-cuts-draft-api.json"))
ap.add_argument("--out", default=str(ROOT / "runs/draft"))
ap.add_argument("--prefix", default="urban-cuts-draft")
ap.add_argument("--consent", action="store_true")
ap.add_argument("--set", action="append", default=[], help="brief field=value, e.g. mode=products")
ap.add_argument("--image", action="append", default=[], help="node title=input file, e.g. 'Look photo 2=x.png'")
ap.add_argument("--timeout", type=int, default=900)
a = ap.parse_args()

g = json.loads(Path(a.graph).read_text())
info = json.load(urllib.request.urlopen(f"{a.url}/object_info", timeout=60))
paid = sorted({n["class_type"] for n in g.values() if info.get(n["class_type"], {}).get("api_node")})
if paid:
    sys.exit(f"refusing: this graph has partner (paid) nodes {paid}; run_draft.py only runs the free draft")
brief = next(n for n in g.values() if n["class_type"] == "UrbanBrief")
brief["inputs"]["consent"] = bool(a.consent)
for kv in a.set:
    k, v = kv.split("=", 1)
    old = brief["inputs"][k]
    brief["inputs"][k] = float(v) if isinstance(old, float) else (v.lower() == "true" if isinstance(old, bool) else v)
for kv in a.image:
    title, f = kv.split("=", 1)
    next(n for n in g.values() if n.get("_meta", {}).get("title") == title)["inputs"]["image"] = f
try:
    pid = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{a.url}/prompt", data=json.dumps({"prompt": g, "client_id": str(uuid.uuid4())}).encode(),
        headers={"Content-Type": "application/json"}), timeout=60))["prompt_id"]
except urllib.error.HTTPError as e:
    sys.exit(f"rejected: {e.read().decode()[:2000]}")
print("queued", pid, flush=True)
t0 = time.time()
while True:
    h = json.load(urllib.request.urlopen(f"{a.url}/history/{pid}", timeout=60))
    if pid in h and h[pid].get("status", {}).get("completed") is not None:
        break
    if time.time() - t0 > a.timeout:
        sys.exit("timed out")
    time.sleep(2)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
(out / f"{a.prefix}-history.json").write_text(json.dumps(h[pid], indent=1))
st = h[pid]["status"]
if st.get("status_str") != "success":
    err = [m[1] for m in st.get("messages", []) if m[0] == "execution_error"]
    print(json.dumps([{"node": e.get("node_type"), "message": e.get("exception_message")} for e in err], indent=1))
    sys.exit("draft run failed")
base = Path(a.comfy_base)
copied = []
for nid, o in h[pid]["outputs"].items():
    title = g[nid].get("_meta", {}).get("title", nid)
    for kind in ("images", "videos", "gifs"):
        for f in o.get(kind, []):
            src = base / f.get("type", "output") / f.get("subfolder", "") / f["filename"]
            dst = {"Your reel": out / f"{a.prefix}-reel.mp4", "Contact sheet": out / f"{a.prefix}-contact-sheet.png"}.get(title)
            if dst:
                shutil.copy(src, dst); copied.append(dst)
    if "text" in o and title in ("Receipt", "Beats"):
        ext = "json" if title == "Receipt" else "txt"
        (out / f"{a.prefix}-{title.lower()}.{ext}").write_text("".join(map(str, o["text"])) + "\n")
print(f"done in {time.time() - t0:.0f} s")
print("\n".join(map(str, copied)))
