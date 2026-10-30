"""Redo one look in the brand style: move its try-on still into the 'room' set (Nano Banana 2.1 edit), then film a
locked-off pose sequence + a handheld close-up from it (Kling 3.0, 2 storyboards). -> workflows/room-redo-api.json
python3 tools/build_room_redo.py --look 1 --still urban_demo_look_1.png      (~$0.47 per look)"""
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
brief = core.make_brief(consent=True, vibe=a.vibe, angles=True)
brief["set"] = "room"
pose, close = core.pose_prompts(brief, a.look)
g = {"1": {"class_type": "LoadImage", "inputs": {"image": a.still}, "_meta": {"title": "Look still"}},
     "2": {"class_type": "GeminiNanoBanana2V2", "_meta": {"title": f"Room {a.look} (Nano Banana 2.1)"},
           "inputs": {"prompt": core.restage_prompt(brief, a.look), "seed": 400 + a.look, "response_modalities": "IMAGE",
                      "model": "Gemini Nano Banana 2.1", "model.aspect_ratio": "9:16", "model.resolution": "1K",
                      "model.thinking_level": "MINIMAL", "model.images.image_1": ["1", 0]}},
     "3": {"class_type": "SaveImage", "_meta": {"title": f"room still {a.look}"},
           "inputs": {"images": ["2", 0], "filename_prefix": f"urban-demo/room_{a.look}"}},
     "4": {"class_type": "KlingVideoNode", "_meta": {"title": f"Poses {a.look} (Kling 3.0)"},
           "inputs": {"generate_audio": False, "model": "kling-v3", "seed": 500 + a.look, "start_frame": ["2", 0],
                      "model.resolution": "720p", "model.aspect_ratio": "9:16", "multi_shot": "2 storyboards",
                      "multi_shot.storyboard_1_prompt": pose, "multi_shot.storyboard_1_duration": core.ANGLE_SHOTS[0],
                      "multi_shot.storyboard_2_prompt": close, "multi_shot.storyboard_2_duration": core.ANGLE_SHOTS[1]}},
     "5": {"class_type": "SaveVideo", "_meta": {"title": f"clip {a.look}"},
           "inputs": {"video": ["4", 0], "filename_prefix": f"urban-demo/clip_{a.look}_room", "format": "mp4", "format.codec": "auto"}}}
out = ROOT / "workflows" / "room-redo-api.json"
out.write_text(json.dumps(g, indent=1) + "\n")
print(f"-> {out}")
