"""Assemble the demo video (under 2 min, 1920x1080) from real screenshots of the app (tools/record_demo.mjs), the
demo reel, its contact sheet and receipt, and the free product draft. Captions are burned in; no voice-over.

python3 tools/make_demo_video.py --shots runs/demo-video --out docs/demo/urban-cuts-demo.mp4"""
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import urban_core as core  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--shots", default=str(ROOT / "runs/demo-video"))
ap.add_argument("--inputs", default=str(ROOT / "runs/paid/inputs/inputs-sheet.jpg"))
ap.add_argument("--music", default=str(ROOT / "runs/paid/demo/assets/music20.wav"))
ap.add_argument("--out", default=str(ROOT / "docs/demo/urban-cuts-demo.mp4"))
ap.add_argument("--repo", default="github.com/jk-automations/urban-cuts")
a = ap.parse_args()
FF, _ = core._ff()
W, H, FPS = 1920, 1080, 30
BG, FG, ACC = (24, 21, 18), (245, 236, 222), (226, 140, 92)
S = Path(a.shots); EX = ROOT / "docs/examples"
work = Path(tempfile.mkdtemp(prefix="uc_demo_"))


def canvas():
    return Image.new("RGB", (W, H), BG)


def text(d, xy, s, size, fill=FG, width=None):
    f = core._font(size)
    if width is None:
        d.text(xy, s, font=f, fill=fill); return xy[1] + size * 1.3
    words, line, y = s.split(), "", xy[1]
    for w in words:
        if d.textlength((line + " " + w).strip(), font=f) > width and line:
            d.text((xy[0], y), line, font=f, fill=fill); y += size * 1.3; line = w
        else:
            line = (line + " " + w).strip()
    d.text((xy[0], y), line, font=f, fill=fill)
    return y + size * 1.3


def fit(img, w, h):
    img = img.convert("RGB"); img.thumbnail((w, h), Image.LANCZOS); return img


def side(img_path, title, body, img_w=1180):
    """Screenshot on the right, caption on the left."""
    c = canvas(); d = ImageDraw.Draw(c)
    im = fit(img_path if isinstance(img_path, Image.Image) else Image.open(img_path), img_w, H - 80)
    c.paste(im, (W - im.width - 40, (H - im.height) // 2))
    y = text(d, (60, 300), title, 54, ACC, width=W - im.width - 140)
    text(d, (60, y + 20), body, 34, FG, width=W - im.width - 140)
    return c


def bottom(img_path, title, body):
    """Full-width picture with a caption band at the bottom."""
    c = canvas(); d = ImageDraw.Draw(c)
    im = fit(Image.open(img_path), W - 80, H - 250)
    c.paste(im, ((W - im.width) // 2, 30))
    y = text(d, (60, H - 200), title, 46, ACC)
    text(d, (60, y + 4), body, 30, FG, width=W - 120)
    return c


def card(lines):
    c = canvas(); d = ImageDraw.Draw(c); y = 330
    for s, size, col in lines:
        f = core._font(size); d.text(((W - d.textlength(s, font=f)) / 2, y), s, font=f, fill=col); y += size * 1.6
    return c


segs = []   # (kind, payload, seconds)


def still(img, secs):
    p = work / f"s{len(segs):02d}.png"; img.save(p); segs.append(("still", p, secs))


def form_panel(path):
    """The App Mode form (right-hand panel) split into two readable columns."""
    im = Image.open(path).convert("RGB")
    a, b = im.crop((1128, 80, 1440, 840)), im.crop((1128, 840, 1440, 1600))
    two = Image.new("RGB", (a.width * 2 + 20, a.height), BG)
    two.paste(a, (0, 0)); two.paste(b, (a.width + 20, 0))
    return two


def reel(path, title, body, secs=None, loops=1):
    p = work / f"r{len(segs):02d}.png"
    c = canvas(); d = ImageDraw.Draw(c)
    y = text(d, (60, 340), title, 54, ACC, width=W - 720 - 280)
    text(d, (60, y + 20), body, 34, FG, width=W - 720 - 280)
    c.save(p)
    segs.append(("reel", (p, Path(path), loops), secs or core.probe(path)["dur"] * loops))


rec = json.loads((EX / "demo-receipt.json").read_text())
still(card([("Urban Cuts", 110, FG), ("an open-source clone of Higgsfield's Urban Cuts, for ComfyUI App Mode", 40, ACC),
            ("one photo + 3 to 5 outfits or products + music  ->  a beat-cut reel that loops", 34, FG)]), 5)
reel(EX / "demo-reel-street.mp4", "The result", "A shop's new-arrivals reel. A one-beat teaser of every look, then each "
     "look in a bright white wall room: the model poses, turns to show the back, looks over the shoulder, then a close-up "
     "on the fabric. Plain cuts on the beat, a warm grade, an opening title, and a card with the shop's handle. Then it loops.")
still(card([("Edited like brand posts", 64, ACC),
            ("We watched 15 recent outfit Shorts from top fashion brands.", 34, FG),
            ("None used flashes, whip pans, punch-zooms, prices or lineup grids.", 34, FG),
            ("They hold a locked camera, let the model pose in a real-looking room,", 34, FG),
            ("show the whole range up front, and cut plainly.", 34, FG),
            ("Urban Cuts' default 'brand' style does the same. 'Hype' keeps the loud edit.", 34, ACC)]), 7)
still(bottom(a.inputs, "The inputs", "A fictional model made with Nano Banana 2.1 (not a real person) and four plain outfits "
             "with no logos. Music is generated by Sonilo, so there is no licence question."), 7)
still(side(form_panel(S / "app.png"), "App Mode", "Pick the person, the outfits (or products), the vibe, length and music. The run is "
           "blocked until you tick 'I have this person's consent'.", 1000), 8)
still(bottom(S / "graph.png", "Under the hood", "Kling Virtual Try-On (or a Nano Banana 2.1 edit) dresses the person, Kling 3.0 "
             "films each look as a pose sequence plus a close-up (after an optional Nano Banana room edit), Sonilo writes the music. Our nodes find the beat and cut the reel on the CPU. Unused branches "
             "are lazy inputs: they never run and never bill."), 9)
still(bottom(EX / "demo-contact-sheet-street.png", "Cut on the beat",
             f"{rec['bpm']} BPM. A teaser beat of each look, then each look: a 4-beat pose sequence and a 2-beat fabric close-up "
             "(one Kling 3.0 generation with 2 storyboards, so face and clothes match), then the handle card. Brightness is "
             "evened out across looks without touching garment colour, and a drift guard drops frames where the background changes."), 9)
lines = [("The receipt", 64, ACC), (f"BPM {rec['bpm']}  ·  {len(rec['cut_times'])} cuts  ·  loop blend {rec['loop_blend_frames']} frames", 36, FG)]
lines += [(p, 30, FG) for p in ["4 x Kling Virtual Try-On", "4 x Nano Banana 2.1 room edit",
                                 "4 x Kling 3.0, 2 storyboards: 3 s pose sequence + 2 s close-up, 720p",
                                 "1 x Sonilo text to music, 20 s"]]
lines += [(f"cost: ${rec['cost_estimate']['total_usd']:.2f} for a 15 s reel (from the nodes' own price badges)", 36, ACC)]
still(card(lines), 8)
still(side(Image.open(S / "draft-sheet.png").crop((56, 240, 1126, 1360)), "Free Draft, $0", "The same edit with no partner nodes: your own photos with a Ken Burns "
           "push on each beat. Try the music, vibe and length before you pay for motion.", 1100), 8)
reel(EX / "demo-reel-street.mp4", "It loops", "Post it and it plays round and round, on the beat.")
reel(EX / "demo-reel-swim.mp4", "Second proof: swimwear", "One paid run of the real app with 3 swimsuit flat-lays and the "
     "same fictional model: try-on, white wall room, poses, close-ups and a Sonilo track, all from the app's own graph.")
still(card([("Urban Cuts for ComfyUI", 80, FG), (a.repo, 44, ACC), ("outfits or products  ·  free draft  ·  App Mode  ·  Apache-2.0", 34, FG)]), 6)

# ---- render each segment to 1920x1080 30 fps with stereo audio, then concatenate
parts = []
t_music = 0.0
for k, (kind, pay, secs) in enumerate(segs):
    out = work / f"p{k:02d}.mp4"
    if kind == "still":
        fade = f"fade=t=in:d=0.3,fade=t=out:st={secs - 0.3}:d=0.3"
        cmd = [FF, "-v", "error", "-y", "-loop", "1", "-t", str(secs), "-i", str(pay), "-ss", f"{t_music % 9:.2f}", "-t", str(secs),
               "-i", a.music, "-vf", f"scale={W}:{H},format=yuv420p,{fade}", "-af",
               f"volume=-10dB,afade=t=in:d=0.4,afade=t=out:st={secs - 0.5}:d=0.5,aresample=48000",
               "-ac", "2", "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-shortest", str(out)]
        t_music += secs
    else:
        bg, clip, loops = pay
        loop_in = ["-stream_loop", str(loops - 1)] if loops > 1 else []
        cmd = [FF, "-v", "error", "-y", "-loop", "1", "-t", str(secs), "-i", str(bg)] + loop_in + ["-i", str(clip),
               "-filter_complex", f"[1:v]scale=720:1000:force_original_aspect_ratio=decrease,setsar=1[v];[0:v][v]overlay=W-w-120:(H-h)/2,format=yuv420p[o]",
               "-map", "[o]", "-map", "1:a", "-t", str(secs), "-af", "aresample=48000", "-ac", "2", "-r", str(FPS),
               "-c:v", "libx264", "-crf", "20", "-c:a", "aac", str(out)]
    subprocess.run(cmd, check=True)
    parts.append(out)
lst = work / "list.txt"; lst.write_text("".join(f"file '{p}'\n" for p in parts))
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-af", "loudnorm=I=-16:TP=-1.5",
                "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", a.out], check=True)
p = core.probe(a.out)
print(f"{a.out}: {p['dur']:.1f} s, {p['w']}x{p['h']}, {len(segs)} segments")
