"""The demo's inputs, made with Nano Banana 2.1 text-to-image (no reference photos): one fictional model (not a real
person, no lookalike) and four plain outfits with no logos. -> workflows/demo-inputs-api.json (5 images, ~$0.24)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAIL = " No text, no letters, no logos, no brand names, no labels, no watermark."
MODEL = ("Full-body fashion catalogue photo of a fictional adult model, an invented person who does not resemble any real "
         "person or celebrity. Standing straight, facing the camera, arms relaxed, calm friendly expression. Wearing a plain "
         "fitted light grey t-shirt, plain light grey slim trousers and plain white sneakers. Plain light grey studio wall, "
         "soft even light, sharp focus, the whole body visible from head to shoes with space above the head, vertical frame." + TAIL)
OUTFITS = [
    "a rust-orange cotton bomber jacket over a plain white t-shirt, with straight dark charcoal trousers",
    "a chunky cream knit jumper with relaxed sage-green linen trousers",
    "a navy blue two-piece suit, single-breasted jacket and matching trousers, with a plain white shirt",
    "a mustard-yellow fitted short-sleeve top with a black pleated midi skirt",
]
g = {}
def node(i, cls, title, **inputs):
    g[str(i)] = {"class_type": cls, "inputs": inputs, "_meta": {"title": title}}
def banana(i, prompt, aspect, seed, title):
    node(i, "GeminiNanoBanana2V2", title, prompt=prompt, seed=seed, response_modalities="IMAGE", model="Gemini Nano Banana 2.1",
         **{"model.aspect_ratio": aspect, "model.resolution": "1K", "model.thinking_level": "MINIMAL"})
    node(i + 1, "SaveImage", f"Save {title}", images=[str(i), 0], filename_prefix=f"urban-demo/{title.split()[0].lower()}")
banana(1, MODEL, "9:16", 501, "model")
for k, o in enumerate(OUTFITS, 1):
    banana(1 + 2 * k, f"Flat-lay product photo of a complete outfit laid out on a plain white background, seen from above: {o}. "
           f"Clean e-commerce style, even light, the whole outfit visible, nothing else in frame." + TAIL, "3:4", 510 + k, f"outfit{k}")
out = ROOT / "workflows" / "demo-inputs-api.json"
out.write_text(json.dumps(g, indent=1) + "\n")
print(f"{len(g)} nodes -> {out}")
