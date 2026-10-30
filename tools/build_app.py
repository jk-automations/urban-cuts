"""Build the one-graph Urban Cuts app (ComfyUI API format).

python3 tools/build_app.py           # -> workflows/urban-cuts-api.json (partner nodes: Kling try-on, Nano Banana 2.1, Kling 3.0, Sonilo)
python3 tools/build_app.py --draft   # -> workflows/urban-cuts-draft-api.json (free: your look photos + a Ken Burns punch on each beat)
Defaults point at the sample files that tools/make_samples.py puts in ComfyUI/input."""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--draft", action="store_true")
ap.add_argument("--out")
ap.add_argument("--person", default="urban_sample_person.png")
ap.add_argument("--items", default=",".join([f"urban_sample_outfit_{k}.png" for k in range(1, 5)] + ["urban_blank.png"]))
ap.add_argument("--looks", default=",".join([f"urban_sample_look_{k}.png" for k in range(1, 5)] + ["urban_blank.png"]))
ap.add_argument("--music", default="urban_sample_beat.wav")
a = ap.parse_args()
out = Path(a.out or ROOT / "workflows" / ("urban-cuts-draft-api.json" if a.draft else "urban-cuts-api.json"))

g = {}
nid = iter(range(1, 1000))
def node(cls, title=None, **inputs):
    i = str(next(nid)); g[i] = {"class_type": cls, "inputs": inputs}
    if title: g[i]["_meta"] = {"title": title}
    return i
def o(i, k=0): return [i, k]

N = core.MAX_LOOKS
# ---------- user inputs ----------
person = node("LoadImage", "Person photo", image=a.person)
brief = node("UrbanBrief", "Your choices", person=o(person), consent=False, mode="outfits", vibe="street", length=15.0,
             aspect="9:16", look_engine=core.LOOK_ENGINES[0], music_source=core.MUSIC_SOURCES[1 if not a.draft else 0],
             music_prompt="", headline="", ai_label=True, hook=True, lineup=True, look_labels="", brand_name="", handle="",
             cta="", pulse=True, glowup=True, angles=True)
logo = node("LoadImage", "Logo (optional)", image="urban_blank.png")
items = [node("LoadImage", f"Outfit or product {k}", image=a.items.split(",")[k - 1]) for k in range(1, N + 1)]
upload = node("LoadAudio", "Your music", audio=a.music)
# ---------- 1. music: your track, or Sonilo (wired like Comfy's api_sonilo template; only the picked one runs) ----------
if a.draft:
    music = node("UrbanMusic", "Music", brief=o(brief, 1), uploaded=o(upload))
else:
    sonilo = node("SoniloTextToMusic", "Music (Sonilo)", prompt=o(brief, 3), duration=o(brief, 4), seed=7)
    music = node("UrbanMusic", "Music", brief=o(brief, 1), uploaded=o(upload), sonilo=o(sonilo))
beats = node("UrbanBeatDetect", "Beat detect", music=o(music))
node("PreviewAny", "Beats", source=o(beats, 1))
# ---------- 2. one look per outfit/product, 3. one motion clip per look ----------
cut_in = {}
for k in range(1, N + 1):
    cut_in[f"item_{k}"] = o(items[k - 1])
    if a.draft:
        cut_in[f"look_{k}"] = o(node("LoadImage", f"Look photo {k}", image=a.looks.split(",")[k - 1]))
        continue
    shot = node("UrbanShot", f"Look {k} prompts", brief=o(brief, 1), look=k)
    tryon = node("KlingTryOnNode", f"Try-on {k} (Kling)", person_image=o(brief, 0), garment_image=o(items[k - 1]), keep_pose=True,
                 seed=100 + k)
    edit = node("GeminiNanoBanana2V2", f"Edit {k} (Nano Banana 2.1)", prompt=o(shot, 0), seed=200 + k, response_modalities="IMAGE",
                model="Gemini Nano Banana 2.1", **{"model.aspect_ratio": "9:16", "model.resolution": "1K",
                                                   "model.thinking_level": "MINIMAL", "model.images.image_1": o(brief, 0),
                                                   "model.images.image_2": o(items[k - 1])})
    pick = node("UrbanPickLook", f"Look {k}", engine=o(brief, 2), kling=o(tryon), banana=o(edit))
    # one storyboard per look: a 3 s turnaround + a 2 s close-up from the same generation (face and outfit stay the same)
    clip = node("KlingVideoNode", f"Angles {k} (Kling 3.0)", multi_shot="2 storyboards", generate_audio=False, model="kling-v3",
                seed=300 + k, start_frame=o(pick),
                **{"multi_shot.storyboard_1_prompt": o(shot, 2), "multi_shot.storyboard_1_duration": core.ANGLE_SHOTS[0],
                   "multi_shot.storyboard_2_prompt": o(shot, 3), "multi_shot.storyboard_2_duration": core.ANGLE_SHOTS[1],
                   "model.resolution": "720p", "model.aspect_ratio": "9:16"})
    cut_in[f"look_{k}"] = o(pick)
    cut_in[f"clip_{k}"] = o(clip)
# ---------- 4. the edit ----------
cut = node("UrbanBeatCut", "Beat cut", brief=o(brief, 1), music=o(music), beats=o(beats), before=o(brief, 0), logo=o(logo), **cut_in)
node("SaveVideo", "Your reel", video=o(cut, 0), filename_prefix="urban-cuts/reel", format="mp4", **{"format.codec": "auto"})
node("PreviewImage", "Contact sheet", images=o(cut, 1))
node("PreviewAny", "Receipt", source=o(cut, 2))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(g, indent=1) + "\n")
print(f"{len(g)} nodes -> {out}")
