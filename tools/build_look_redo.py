"""Regenerate one look's motion only, from its saved try-on still, with the current (background-locked) motion prompt.
-> workflows/look-redo-api.json   python3 tools/build_look_redo.py --look 3 --still urban_demo_look_3.png"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--look", type=int, required=True)
ap.add_argument("--still", required=True, help="the try-on still in ComfyUI/input")
ap.add_argument("--vibe", default="street")
a = ap.parse_args()
brief = core.make_brief(consent=True, vibe=a.vibe)
g = {"1": {"class_type": "LoadImage", "inputs": {"image": a.still}, "_meta": {"title": "Look still"}},
     "2": {"class_type": "KlingVideoNode", "_meta": {"title": f"Motion {a.look} (Kling 3.0)"},
           "inputs": {"multi_shot": "disabled", "generate_audio": False, "model": "kling-v3", "seed": 300 + a.look,
                      "start_frame": ["1", 0], "multi_shot.prompt": core.motion_prompt(brief, a.look),
                      "multi_shot.negative_prompt": core.NEGATIVE, "multi_shot.duration": core.CLIP_SECONDS,
                      "model.resolution": "720p", "model.aspect_ratio": "9:16"}},
     "3": {"class_type": "SaveVideo", "_meta": {"title": f"clip {a.look}"},
           "inputs": {"video": ["2", 0], "filename_prefix": f"urban-demo/clip_{a.look}_redo", "format": "mp4", "format.codec": "auto"}}}
out = ROOT / "workflows" / "look-redo-api.json"
out.write_text(json.dumps(g, indent=1) + "\n")
print(g["2"]["inputs"]["multi_shot.prompt"])
print(f"-> {out}")
