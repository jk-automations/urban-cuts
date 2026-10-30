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
ap.add_argument("--angles", action="store_true", help="a 3 s turnaround + 2 s close-up storyboard instead of one move")
a = ap.parse_args()
brief = core.make_brief(consent=True, vibe=a.vibe, angles=a.angles)
turn, close = core.angle_prompts(brief, a.look)
g = {"1": {"class_type": "LoadImage", "inputs": {"image": a.still}, "_meta": {"title": "Look still"}},
     "2": {"class_type": "KlingVideoNode", "_meta": {"title": f"Motion {a.look} (Kling 3.0)"},
           "inputs": {"generate_audio": False, "model": "kling-v3", "seed": 300 + a.look, "start_frame": ["1", 0],
                      "model.resolution": "720p", "model.aspect_ratio": "9:16",
                      **({"multi_shot": "2 storyboards", "multi_shot.storyboard_1_prompt": turn,
                          "multi_shot.storyboard_1_duration": core.ANGLE_SHOTS[0], "multi_shot.storyboard_2_prompt": close,
                          "multi_shot.storyboard_2_duration": core.ANGLE_SHOTS[1]} if a.angles else
                         {"multi_shot": "disabled", "multi_shot.prompt": core.motion_prompt(brief, a.look),
                          "multi_shot.negative_prompt": core.NEGATIVE, "multi_shot.duration": core.CLIP_SECONDS})}},
     "3": {"class_type": "SaveVideo", "_meta": {"title": f"clip {a.look}"},
           "inputs": {"video": ["2", 0], "filename_prefix": f"urban-demo/clip_{a.look}_redo", "format": "mp4", "format.codec": "auto"}}}
out = ROOT / "workflows" / "look-redo-api.json"
out.write_text(json.dumps(g, indent=1) + "\n")
print({k: v for k, v in g["2"]["inputs"].items() if "prompt" in k})
print(f"-> {out}")
