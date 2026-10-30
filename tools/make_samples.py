"""Code-drawn sample inputs for the free draft and the tests: a faceless figure (no real person), 4 plain outfits with no
logos, the figure wearing each outfit, 3 plain products, and an original code-made beat. All Apache-2.0, made here.

python3 tools/make_samples.py [--input-dir <ComfyUI>/input]   # writes presets/sample/ and copies into input/"""
import argparse, shutil, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

OUT = ROOT / "presets" / "sample"
W, H = 720, 1280
OUTFITS = [  # (top, bottom, shoes, name)
    ((212, 92, 60), (40, 44, 58), (240, 240, 235), "rust jacket, dark trousers"),
    ((236, 228, 210), (122, 140, 110), (60, 50, 45), "cream knit, sage trousers"),
    ((44, 84, 140), (44, 84, 140), (230, 230, 230), "blue suit"),
    ((250, 200, 70), (30, 30, 30), (30, 30, 30), "yellow top, black skirt"),
]
BACKS = [((206, 196, 182), (150, 140, 128)), ((190, 205, 214), (120, 135, 150)), ((222, 206, 190), (170, 150, 130)),
         ((200, 200, 196), (140, 140, 136))]
PRODUCTS = [((160, 110, 70), "tote"), ((70, 110, 90), "bottle"), ((220, 220, 215), "sneaker")]


def backdrop(top, bottom):
    im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):
        a = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] * (1 - a) + bottom[i] * a) for i in range(3)))
    d.rectangle([0, int(H * 0.82), W, H], fill=tuple(int(c * 0.8) for c in bottom))
    return im


def figure(im, outfit=None, pose=0):
    """A faceless mannequin-style figure. outfit None = neutral grey base layer (the 'person' photo)."""
    d = ImageDraw.Draw(im)
    skin = (196, 160, 132)
    top, bottom, shoes = outfit[:3] if outfit else ((150, 150, 150), (120, 120, 120), (80, 80, 80))
    cx = W // 2 + (pose - 1) * 30
    d.ellipse([cx - 52, 170, cx + 52, 290], fill=skin)                       # head (no face)
    d.ellipse([cx - 56, 160, cx + 56, 230], fill=(50, 38, 30))               # hair
    d.rectangle([cx - 18, 280, cx + 18, 320], fill=skin)                     # neck
    d.polygon([(cx - 120, 330), (cx + 120, 330), (cx + 100, 720), (cx - 100, 720)], fill=top)   # torso
    d.polygon([(cx - 120, 330), (cx - 160, 640), (cx - 125, 650), (cx - 90, 420)], fill=top)    # arms
    d.polygon([(cx + 120, 330), (cx + 160, 640), (cx + 125, 650), (cx + 90, 420)], fill=top)
    d.ellipse([cx - 165, 630, cx - 120, 680], fill=skin); d.ellipse([cx + 120, 630, cx + 165, 680], fill=skin)
    if outfit and "skirt" in outfit[3]:
        d.polygon([(cx - 100, 700), (cx + 100, 700), (cx + 140, 900), (cx - 140, 900)], fill=bottom)
        d.rectangle([cx - 70, 900, cx - 30, 1040], fill=skin); d.rectangle([cx + 30, 900, cx + 70, 1040], fill=skin)
    else:
        d.polygon([(cx - 100, 700), (cx + 100, 700), (cx + 85, 1040), (cx + 15, 1040), (cx, 800), (cx - 15, 1040),
                   (cx - 85, 1040)], fill=bottom)
    d.rounded_rectangle([cx - 95, 1030, cx - 15, 1065], 12, fill=shoes); d.rounded_rectangle([cx + 15, 1030, cx + 95, 1065], 12, fill=shoes)
    return im


def garment(outfit):
    """A flat-lay of the outfit on white, the way a shop photographs it."""
    im = Image.new("RGB", (W, H), (246, 244, 240)); d = ImageDraw.Draw(im)
    top, bottom, shoes, name = outfit
    d.polygon([(200, 160), (520, 160), (600, 420), (540, 440), (500, 300), (500, 600), (220, 600), (220, 300), (180, 440),
               (120, 420)], fill=top)
    if "skirt" in name:
        d.polygon([(250, 660), (470, 660), (530, 900), (190, 900)], fill=bottom)
    else:
        d.polygon([(240, 660), (480, 660), (470, 1080), (380, 1080), (360, 760), (340, 1080), (250, 1080)], fill=bottom)
    d.rounded_rectangle([200, 1120, 320, 1170], 16, fill=shoes); d.rounded_rectangle([400, 1120, 520, 1170], 16, fill=shoes)
    return im


def product(color, kind):
    im = Image.new("RGB", (W, H), (246, 244, 240)); d = ImageDraw.Draw(im)
    if kind == "tote":
        d.rectangle([200, 520, 520, 900], fill=color); d.arc([270, 380, 450, 640], 180, 360, fill=color, width=22)
    elif kind == "bottle":
        d.rounded_rectangle([280, 420, 440, 960], 40, fill=color); d.rectangle([325, 340, 395, 430], fill=(40, 40, 40))
    else:
        d.polygon([(160, 820), (420, 700), (560, 820), (560, 900), (160, 900)], fill=color)
        d.rectangle([160, 890, 560, 920], fill=(60, 60, 60))
    return im


def soft(im):
    return im.filter(ImageFilter.GaussianBlur(1.2))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--input-dir")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}
    files["urban_sample_person.png"] = soft(figure(backdrop((236, 234, 230), (200, 198, 194))))
    for k, of in enumerate(OUTFITS, 1):
        files[f"urban_sample_outfit_{k}.png"] = garment(of)
        files[f"urban_sample_look_{k}.png"] = soft(figure(backdrop(*BACKS[k - 1]), of, pose=k % 3))
    for k, (c, kind) in enumerate(PRODUCTS, 1):
        files[f"urban_sample_product_{k}.png"] = product(c, kind)
    for name, im in files.items():
        im.save(OUT / name)
    y, sr = core.sample_beat()
    core.write_wav(OUT / "urban_sample_beat.wav", y, sr)
    names = list(files) + ["urban_sample_beat.wav"]
    if a.input_dir:
        dst = Path(a.input_dir); dst.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copy(OUT / n, dst / n)
        from PIL import Image as I
        if not (dst / "urban_blank.png").exists():
            I.new("RGB", (64, 64), (255, 255, 255)).save(dst / "urban_blank.png")
    print(f"{len(names)} sample files -> {OUT}" + (f" and {a.input_dir}" if a.input_dir else ""))


if __name__ == "__main__":
    main()
