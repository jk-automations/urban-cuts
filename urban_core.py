"""Urban Cuts core: beat detection, the cut list and the beat-cut edit. An open clone of Higgsfield's Urban Cuts app:
one person photo + 3 to 5 outfits (or products) + music -> a short 9:16 reel that cuts on the beat and loops.
Pure Python + numpy + Pillow + ffmpeg, no ComfyUI imports, so it can be tested on its own. Apache-2.0.

The edit: the reel starts on a downbeat of the music, a new look lands every 2 beats (so every downbeat is a cut),
each cut hits with a punch-zoom, a flash or a whip pan, each shot speeds up into the next cut, and the last frame
blends back into the first so the reel loops. Sound is normalised to -14 LUFS, -1 dBTP."""
import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
FONT = ROOT / "fonts" / "Inter.ttf"

MODES = ["outfits", "products"]
VIBES = {
    "street": {"setting": "a sunny city street with clean concrete walls and soft shadows",
               "moves": ["confident walk toward the camera, then a quick turn of the head", "a half turn on the spot showing the "
                         "back of the outfit, then back to camera", "a relaxed stop-and-pose against a wall, one hand in a pocket",
                         "a slow walk past the camera, glancing at the lens", "a small jump step toward the camera, landing in a pose"],
               "fx": ["punch", "whip", "punch", "flash"]},
    "runway": {"setting": "a minimal white runway with bright even fashion-show light",
               "moves": ["a runway walk straight toward the camera, stopping in a pose", "a runway turn at the end of the catwalk",
                         "a model pose with a slow shoulder turn", "a strong runway walk, hands relaxed", "a final pose, chin up"],
               "fx": ["flash", "punch", "flash", "whip"]},
    "boutique": {"setting": "a bright small boutique with plants, a mirror and warm wood shelves",
                 "moves": ["stepping out from behind a curtain into frame", "a gentle twirl showing the outfit",
                           "a soft pose in front of a mirror", "a small walk toward the camera with a smile",
                           "adjusting a sleeve, then looking at the camera"],
                 "fx": ["punch", "punch", "flash", "punch"]},
}
ASPECTS = {"9:16": (720, 1280), "4:5": (864, 1080), "1:1": (1080, 1080)}
LOOK_ENGINES = ["Kling try-on", "Nano Banana 2 edit"]
MUSIC_SOURCES = ["my own track (upload)", "Sonilo (text to music)"]
STYLES = ["brand", "hype"]             # brand: how fashion brands post (hard cuts, warm grade, clean text); hype: flash/whip/punch
HOOKS = ["teaser", "before→after", "off"]
SETS = ["keep my photo's background", "white wall room"]
SPOT_MOVES = ["shifts their weight and turns slightly to the side, then back to face the camera with a confident look",
              "does a slow half turn on the spot to show the back of the outfit, then turns back to the camera",
              "puts one hand on the hip and turns the shoulders toward the camera with a small smile",
              "takes one small step forward and settles into a relaxed pose",
              "adjusts the collar or sleeve, then looks straight into the camera"]
for _v, _e in zip(VIBES.values(), ["cool, confident attitude", "poised model energy", "warm, playful charm"]):
    _v["energy"] = _e
MAX_LOOKS = 5
CLIP_SECONDS = 3                       # Kling 3.0 image-to-video, the shortest (cheapest) clip
ANGLE_SHOTS = [3, 2]                   # camera angles: one Kling 3.0 storyboard per look, a 3 s turnaround + a 2 s close-up
ANGLE_PATTERN = [4, 2]                 # ...shown as a 4-beat turnaround shot, then a 2-beat close-up
PUNCH = {"street": 0.14, "runway": 0.10, "boutique": 0.07}

# Partner prices, copied from the nodes' own price badges (ComfyUI 0.42 comfy_api_nodes, read 2026-10-29).
PRICES = {"KlingTryOnNode": 0.16016, "GeminiNanoBanana2V2_1K_minimal": 0.048048, "KlingVideoNode_720p_per_s": 0.084,
          "SoniloTextToMusic_per_s": 0.0025}

TP_HEADROOM = -2.5
NEGATIVE = ("logos, brand names, text, watermark, extra people, distorted hands, distorted face, blurry, cuts, shaky camera, "
            "background change, new location, scene change, walking out of frame")


# ---------------------------------------------------------------- the brief and the prompts
def make_brief(mode="outfits", vibe="street", length=10.0, aspect="9:16", look_engine=LOOK_ENGINES[0],
               music_source=MUSIC_SOURCES[0], music_prompt="", headline="", consent=False, ai_label=True, hook=True,
               lineup=True, look_labels="", brand_name="", handle="", cta="", pulse=True, glowup=True, angles=False,
               style="hype", set=SETS[0], prices=True):
    if not consent:
        raise ValueError("Urban Cuts needs the person's consent: tick 'I have this person's consent to use their photo' "
                         "(you, or someone who agreed). Nothing was generated.")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if vibe not in VIBES:
        raise ValueError(f"vibe must be one of {list(VIBES)}")
    if aspect not in ASPECTS:
        raise ValueError(f"aspect must be one of {list(ASPECTS)}")
    if style not in STYLES:
        raise ValueError(f"style must be one of {STYLES}")
    hook = {True: "before", False: None, "teaser": "teaser", "before→after": "before", "before": "before", "off": None}.get(hook, hook)
    if hook not in ("before", "teaser", None):
        raise ValueError(f"hook must be one of {HOOKS}")
    if not 4.0 <= float(length) <= 20.0:
        raise ValueError("length must be 4 to 20 seconds")
    engine = "banana" if mode == "products" or look_engine.startswith("Nano") else "kling"
    music = "sonilo" if music_source.startswith("Sonilo") else "upload"
    mp = music_prompt.strip() or default_music_prompt(vibe)
    return {"mode": mode, "vibe": vibe, "length": float(length), "aspect": aspect, "engine": engine, "music": music,
            "music_prompt": mp, "music_seconds": int(np.ceil(float(length))) + 5, "headline": headline.strip(),
            "ai_label": bool(ai_label), "hook": hook, "lineup": bool(lineup), "labels": parse_labels(look_labels),
            "style": style, "set": "room" if set.startswith("white") else "photo", "prices": bool(prices),
            "brand": {"name": brand_name.strip(), "handle": handle.strip(), "cta": cta.strip()},
            "pulse": bool(pulse), "glowup": bool(glowup), "angles": bool(angles),
            "shots": list(ANGLE_SHOTS) if angles else [CLIP_SECONDS], "pattern": list(ANGLE_PATTERN) if angles else None}   # music_seconds: room to start on a downbeat, and Sonilo tracks tail off at the end


def parse_labels(text):
    """One line per look: 'Rust bomber jacket | $89' (or just a name). Returns ['Rust bomber jacket · $89', ...]."""
    out = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|") if p.strip()]
        out.append(" · ".join(parts[:2]))
    while out and not out[-1]:
        out.pop()
    return out


def default_music_prompt(vibe):
    return {"street": "upbeat hip hop instrumental, punchy kick and snare, 120 BPM, confident, no vocals",
            "runway": "driving fashion house instrumental, four on the floor, 124 BPM, sleek, no vocals",
            "boutique": "bright funky pop instrumental, claps and bass, 112 BPM, warm and playful, no vocals"}[vibe]


def look_prompt(brief, k):
    """The Nano Banana 2 image-edit prompt for look k (1-based). Outfit wording borrowed from Comfy's template
    'template_eric_seedance_5_subject_and_outfit_combine' (Image 1 = identity, Image 2 = the outfit, exactly)."""
    v = VIBES[brief["vibe"]]
    if brief["mode"] == "products":
        body = ("Fashion-editorial photo of the person from Image 1 presenting the product from Image 2 toward the camera. "
                "Image 1 defines the person's identity, face and body proportions, which must match exactly. Image 2 defines "
                "only the product, which must match exactly: shape, colour, material and proportions.")
    else:
        body = ("Full-body fashion photo of the person from Image 1 wearing the exact outfit from Image 2. Image 1 defines "
                "the person's identity, face and body proportions, which must match exactly. Image 2 defines only the "
                "outfit, which must match exactly: cut, colour, fabric and fit.")
    return (f"{body} Setting: {v['setting']}. Vertical 9:16 frame, the whole person visible with space above the head, "
            f"natural light, sharp focus. Look {k}. No logos, no brand names, no text, no other people.")


def angle_prompts(brief, k):
    """Camera angles for look k: two storyboard shots from ONE Kling 3.0 generation, so face and outfit stay the same
    across the angles. Shot 1: a full 360-degree turnaround, full body. Shot 2: a close-up on the fabric and details.
    The flat-lay shows only the front, so the back of the outfit is the video model's best guess."""
    v = VIBES[brief["vibe"]]
    lock = ("Same background and light as the first frame." if brief["engine"] == "kling" or brief.get("set") == "room"
            else f"{v['setting'].capitalize()}.")
    if brief["mode"] == "products":
        turn = (f"The person slowly turns the product in their hands to show every side of it, then holds it toward the "
                f"camera. {lock} Steady camera, the person and the product fully in frame.")
        detail = (f"Close-up: the camera slowly pushes in on the product in the person's hands, showing its material, "
                  f"shape and details. {lock} The product stays exactly the same.")
    else:
        turn = (f"The person turns slowly on the spot through one full 360-degree turn, showing the front, the side and the "
                f"back of the outfit, and ends facing the camera, {v['energy']}. Full body in frame from head to shoes. "
                f"{lock} Locked-off camera. The outfit stays exactly the same: colours, fabric and fit.")
        detail = (f"Close-up: the camera slowly pushes in on the outfit from the chest to the waist, showing the fabric, "
                  f"stitching and details, while the person stands still. {lock} Same outfit, same colours.")
    return turn, detail


def shot_prompts(brief, k):
    """The two storyboard prompts for look k: brand style films a pose sequence, hype style a 360 turnaround."""
    return pose_prompts(brief, k) if brief.get("style") == "brand" else angle_prompts(brief, k)


def restage_prompt(brief, k):
    """Nano Banana 2.1 edit that moves a finished look into the 'room' set (the white wall + wooden floor that brand
    try-on posts use) without touching the person or the outfit. Image 1 = the look still."""
    return ("Place the person from Image 1 in a bright, simple room: a plain warm-white wall and a herringbone wooden "
            "parquet floor, soft natural daylight from the side. Keep the person exactly the same: face, hair, body, pose "
            "and the outfit, which must match exactly: cut, colour, fabric and fit. Same full-body framing with space above "
            "the head, vertical 9:16, sharp focus. No logos, no brand names, no text, no other people, no furniture.")


def pose_prompts(brief, k):
    """Brand style: two storyboard shots from one Kling 3.0 generation, the way brand try-on posts are filmed. Shot 1:
    a locked-off full-body pose sequence where the MODEL moves (hand on hip, turn to the back, a look over the shoulder),
    not a camera orbit. Shot 2: a handheld close-up on the fabric."""
    v = VIBES[brief["vibe"]]
    lock = ("Same background and light as the first frame." if brief["engine"] == "kling" or brief.get("set") == "room"
            else f"{v['setting'].capitalize()}.")
    if brief["mode"] == "products":
        return angle_prompts(brief, k)
    pose = (f"Fashion try-on video, locked-off camera, full body from head to shoes. The person puts one hand on the hip, "
            f"then turns around to show the back of the outfit, looks back over the shoulder at the camera, and turns to "
            f"face the camera again in a relaxed pose, {v['energy']}. {lock} The outfit stays exactly the same: colours, "
            f"fabric and fit.")
    detail = (f"Close-up, slight handheld movement: the camera glides down the outfit from the chest to the waist while the "
              f"person's hand brushes the fabric, showing texture, stitching and fit. {lock} Same outfit, same colours.")
    return pose, detail


def motion_prompt(brief, k):
    """The Kling image-to-video prompt for look k: one short continuous move, no cuts (the edit makes the cuts).
    Kling try-on keeps the person photo's own background, so that path must not name a new setting: a setting in the
    prompt made Kling walk the person out of the studio onto a street (paid demo, look 3). It gets moves made on the
    spot and an explicit background lock. The Nano Banana path already restaged the person in the vibe's setting."""
    v = VIBES[brief["vibe"]]
    held = "holding the product toward the camera" if brief["mode"] == "products" else "the outfit stays exactly the same"
    if brief["engine"] == "kling":
        move = SPOT_MOVES[(k - 1) % len(SPOT_MOVES)]
        return (f"The person {move}, {held}. Same background, same light and same framing as the first frame; the person "
                f"stays in place. Locked-off steady camera, {v['energy']}, one continuous shot, no cuts, face and outfit "
                f"unchanged.")
    move = v["moves"][(k - 1) % len(v["moves"])]
    return (f"The person {move}, {held}. {v['setting'].capitalize()}. Smooth steady camera, fashion reel energy, "
            f"one continuous shot, no cuts, face and outfit unchanged.")


# ---------------------------------------------------------------- beat detection
def to_mono(samples):
    a = np.asarray(samples, dtype=np.float64)
    return a.mean(axis=0) if a.ndim == 2 else a


def onset_envelope(y, sr, hop=256, n_fft=1024):
    """Spectral flux: the log magnitude spectrum's positive change, frame by frame (frame centre = frame * hop)."""
    pad = np.pad(y, n_fft // 2)
    n = 1 + (len(pad) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(pad[idx] * np.hanning(n_fft), axis=1))
    logm = np.log1p(100.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    env = np.concatenate([[0.0], flux])
    env = env - np.convolve(env, np.ones(16) / 16, mode="same")   # remove the slow level so only hits stay
    return np.maximum(env, 0.0)


def _tempo(env, fps, lo=70, hi=180):
    ac = np.correlate(env - env.mean(), env - env.mean(), mode="full")[len(env) - 1:]
    lags = np.arange(int(fps * 60 / hi), int(fps * 60 / lo) + 1)
    bpm = 60.0 * fps / lags
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)   # prefer ~120 BPM between octave candidates
    score = ac[lags] * prior
    k = int(np.argmax(score))
    lag = float(lags[k])
    if 0 < k < len(lags) - 1:   # parabolic refinement of the peak lag
        a, b, c = score[k - 1], score[k], score[k + 1]
        den = a - 2 * b + c
        if den != 0:
            lag = lags[k] + 0.5 * (a - c) / den
    return 60.0 * fps / lag


def detect_beats_numpy(y, sr, hop=256):
    env = onset_envelope(y, sr, hop=hop)
    fps = sr / hop
    bpm = _tempo(env, fps)
    period = fps * 60.0 / bpm
    # dynamic programming beat tracker (Ellis 2007): reward onsets, penalise gaps far from the beat period
    n = len(env)
    score = env.copy()
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period * 0.5)), int(round(period * 2))
    for i in range(lo, n):
        prev = np.arange(max(0, i - hi), i - lo + 1)
        if len(prev) == 0:
            continue
        pen = -100.0 * (np.log((i - prev) / period)) ** 2
        cand = score[prev] + pen * env.max() * 0.01
        j = int(np.argmax(cand))
        score[i] = env[i] + cand[j]
        back[i] = prev[j]
    tail = np.arange(max(0, n - int(period * 1.5)), n)
    i = int(tail[np.argmax(score[tail])])
    frames = []
    while i >= 0:
        frames.append(i)
        i = back[i]
    frames = np.array(frames[::-1])
    # sub-frame refinement: parabolic peak of the onset envelope around each beat frame
    times = []
    for f in frames:
        t = float(f)
        if 0 < f < n - 1 and env[f] >= env[f - 1] and env[f] >= env[f + 1]:
            a, b, c = env[f - 1], env[f], env[f + 1]
            den = a - 2 * b + c
            if den != 0:
                t = f + 0.5 * (a - c) / den
        times.append(t * hop / sr)
    times = [t for t in times if t >= 0]
    strength = [float(env[int(round(t * sr / hop))]) if int(round(t * sr / hop)) < n else 0.0 for t in times]
    return bpm, np.array(times), np.array(strength)


def detect_beats(samples, sr, prefer_librosa=True):
    """BPM, beat times and downbeat times (seconds). librosa when it is installed, else the numpy tracker above.
    Downbeats: every 4th beat, the phase whose beats are loudest (bar accents)."""
    y = to_mono(samples)
    if len(y) < sr:
        raise ValueError("the music is shorter than 1 second")
    method = "numpy onset envelope + DP tracker"
    times = None
    if prefer_librosa:
        try:
            import librosa
            tempo, fr = librosa.beat.beat_track(y=y.astype(np.float32), sr=sr, hop_length=256, units="frames")
            env = librosa.onset.onset_strength(y=y.astype(np.float32), sr=sr, hop_length=256)
            times = librosa.frames_to_time(fr, sr=sr, hop_length=256)
            strength = env[np.clip(fr, 0, len(env) - 1)]
            bpm = float(np.atleast_1d(tempo)[0])
            method = f"librosa {librosa.__version__}"
        except ImportError:
            pass
    if times is None:
        bpm, times, strength = detect_beats_numpy(y, sr)
    if len(times) < 4:
        raise ValueError("found fewer than 4 beats: use a track with a clear beat")
    if len(times) > 3:   # tempo from the tracked beats themselves (more exact than the autocorrelation peak)
        bpm = 60.0 / float(np.median(np.diff(times)))
    # bar accents: the raw loudness right after each beat (the log onset envelope hides how hard a hit is)
    w0, w1 = int(0.01 * sr), int(0.08 * sr)
    strength = np.array([np.sqrt(np.mean(y[max(0, int(t * sr) - w0):int(t * sr) + w1] ** 2) + 1e-12) for t in times])
    phase = int(np.argmax([np.mean(strength[p::4]) for p in range(4)]))
    down = times[phase::4]
    return {"bpm": round(float(bpm), 2), "beats": [round(float(t), 4) for t in times],
            "downbeats": [round(float(t), 4) for t in down], "method": method, "duration": round(len(y) / sr, 3)}


# ---------------------------------------------------------------- the cut list
def plan_cuts(beats, n_looks, length=10.0, beats_per_look=2, start=None, hook=False, lineup=False, pattern=None, card=False):
    """Where each look starts and ends on the music. The reel starts on a downbeat (music offset `start`); then the
    looks cycle 1..n. Each look is a run of shots whose lengths in beats are `pattern` (default: one shot of
    `beats_per_look` beats; with camera angles [4, 2]: a 4-beat turnaround, then a 2-beat close-up). Returns the music
    offset, the segments [{kind, look, shot, t0, t1}] on the reel timeline (t1 of the last = length) and the cut times.
    hook: True/'before' = the first 2 beats are the plain 'before' photo; 'teaser' = one beat of every look first, the
    way brand posts show the whole range up front. lineup: from the last bar line that leaves most of a bar, every
    look in a grid, one tile popping in per beat ('pops'). card (when no lineup): the last 2 beats are a handle card.
    Each is dropped (see 'skipped') when there is too little time for every look to show at least once."""
    bt = np.array(beats["beats"], dtype=float)
    if n_looks < 1:
        raise ValueError("need at least one look")
    if start is None:   # the first downbeat that still leaves `length` seconds of music after it
        ok = [d for d in beats["downbeats"] if d + length <= beats["duration"] + 1e-6]
        start = ok[0] if ok else (bt[0] if bt[0] + length <= beats["duration"] else 0.0)
    rel = bt[bt >= start - 1e-6] - start
    rel = rel[rel < length - 0.25]   # no cut in the final quarter second
    period = 60.0 / beats["bpm"]
    pattern = list(pattern or [beats_per_look])
    per_look = sum(pattern)
    beats_avail = length / period
    skipped = []
    hook = "before" if hook is True else (hook or None)
    hook_beats = {"before": 2, "teaser": n_looks}.get(hook, 0)
    end_kind = "lineup" if (lineup and n_looks >= 2) else ("card" if card else None)
    need = lambda hb: hb + (n_looks - 1) * per_look + pattern[0]   # beats until every look has shown its first shot
    lineup_b = None
    if end_kind:
        # where a shot starts (the ending must start on a cut): most of a bar before the end for the lineup, 2 beats for the card
        starts = list(np.cumsum([hook_beats] + pattern * (n_looks * 8)))
        starts = [b for b in starts if length - b * period >= (3.6 if end_kind == "lineup" else 1.6) * period]
        full = hook_beats + n_looks * per_look     # every shot of every look shown
        pick = ([b for b in starts if b >= full and b % 4 == 0] or [b for b in starts if b >= full]
                or [b for b in starts if b >= need(hook_beats)])
        if pick:
            lineup_b = pick[-1]
        else:
            skipped.append(f"{end_kind}: reel too short for it after every look")
    end_b = lineup_b if lineup_b is not None else beats_avail
    if hook and need(hook_beats) > end_b + 1e-6:
        hook, hook_beats = None, 0
        skipped.append("hook: reel too short to show every look after it")
    slots = ([("before", None, None, 0)] if hook == "before" else
             [("teaser", j, 0, j) for j in range(n_looks)] if hook == "teaser" else [])
    b, k = hook_beats, 0
    while b < end_b - 0.5 and b * period < length - 0.25:
        j = k % len(pattern)
        slots.append(("look", (k // len(pattern)) % n_looks, j, b)); b += pattern[j]; k += 1
    if lineup_b is not None:
        slots.append((end_kind, None, None, lineup_b))
    # Walk the tempo grid and snap each cut to the detected beat nearest to it. A tracker slip (an extra or missing
    # beat) then cannot shift every later cut off the grid: when no detected beat is within 15% of a beat period, the
    # grid time is used and marked "grid" in `snapped`.
    def snap(target):
        near = rel[np.argmin(np.abs(rel - target))] if len(rel) else None
        if near is not None and abs(near - target) <= 0.15 * period:
            return float(near), "beat"
        return float(target), "grid"
    times, snapped = [0.0], []
    for i in range(1, len(slots)):
        t, how = snap(times[-1] + (slots[i][3] - slots[i - 1][3]) * period)
        times.append(max(t, times[-1] + 1e-3)); snapped.append(how)
    segs = []
    for i, (kind, look, shot, _) in enumerate(slots):
        t0, t1 = times[i], (times[i + 1] if i + 1 < len(times) else length)
        seg = {"kind": kind, "look": look, "shot": shot, "t0": round(t0, 4), "t1": round(t1, 4)}
        if kind == "lineup":
            pops = [snap(t0 + j * period)[0] if j else t0 for j in range(min(n_looks, 4))]   # one tile per beat
            pops += [pops[-1]] * (n_looks - len(pops))                                        # a 5th shares the 4th
            seg["pops"] = [round(p, 4) for p in pops]
            seg["t1"] = float(length)
        segs.append(seg)
    used_cuts = [s["t0"] for s in segs[1:]]
    return {"hook": hook, "music_start": round(float(start), 4), "segments": segs, "cuts": used_cuts, "snapped": snapped,
            "beat_times": [round(float(t), 4) for t in rel], "length": float(length), "skipped": skipped,
            "pattern": pattern}


# ---------------------------------------------------------------- media helpers
def _ff():
    return shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg", shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"


def probe(path):
    _, fp = _ff()
    out = json.loads(subprocess.check_output([fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    v = next((s for s in out["streams"] if s["codec_type"] == "video"), None)
    dur = float((v or {}).get("duration") or out["format"]["duration"])
    r = {"dur": dur, "audio": any(s["codec_type"] == "audio" for s in out["streams"])}
    if v:
        r.update(w=int(v["width"]), h=int(v["height"]), frames=int(v.get("nb_frames") or 0))
    return r


def _font(size):
    try:
        return ImageFont.truetype(str(FONT), size)
    except OSError:
        return ImageFont.load_default(size)


def cover(img, W, H):
    """Scale and centre-crop a PIL image to fill W x H."""
    img = img.convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((max(W, round(img.width * s)), max(H, round(img.height * s))), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def label_png(txt, W):
    """Small 'AI-generated' style label, semi-transparent dark box (same look as Honest Downgrade)."""
    size = max(16, W // 34)
    f = _font(size)
    tw = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(txt, font=f))
    lab = Image.new("RGBA", (tw + 24, size + 18), (0, 0, 0, 120))
    ImageDraw.Draw(lab).text((12, 7), txt, font=f, fill="white")
    return lab


def text_png(txt, size, w, pad=48):
    """Classic caption: bold white, dark stroke, centred, wrapped (Honest Downgrade's W13 style)."""
    f = _font(size)
    d = ImageDraw.Draw(Image.new("RGBA", (w, 10)))
    lines, cur = [], ""
    for wd in txt.split():
        trial = (cur + " " + wd).strip()
        if d.textlength(trial, font=f) > w - 2 * pad and cur:
            lines.append(cur); cur = wd
        else:
            cur = trial
    lines.append(cur)
    img = Image.new("RGBA", (w, int(size * 1.25 * len(lines)) + 16), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    for k, ln in enumerate(lines):
        d.text(((w - d.textlength(ln, font=f)) / 2, 4 + k * size * 1.25), ln, font=f, fill="white",
               stroke_width=max(3, size // 10), stroke_fill=(10, 10, 10))
    return img


ACCENT = (226, 140, 92)


def look_tag_png(num, txt, W):
    """The shoppable tag on a look: '01' in the accent colour, then the name and price, on a dark rounded card."""
    size = max(18, W // 24)
    fb, f = _font(int(size * 1.15)), _font(size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    num_s = f"{num:02d}"
    nw, tw = d.textlength(num_s, font=fb), d.textlength(txt, font=f)
    pad = size // 2
    w = int(np.ceil(min(W * 0.78, nw + tw + 4 * pad))) + 2
    while d.textlength(txt, font=f) > w - nw - 4 * pad + 2 and len(txt) > 4:   # only very long names are shortened
        txt = txt[:-2].rstrip() + "…"
    card = Image.new("RGBA", (w, int(size * 1.9)), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle([0, 0, w - 1, card.height - 1], radius=size // 2, fill=(18, 16, 14, 190))
    cd.text((pad, (card.height - size * 1.15) / 2 - 2), num_s, font=fb, fill=ACCENT)
    cd.text((pad * 2 + nw, (card.height - size) / 2 - 2), txt, font=f, fill="white")
    return card


def read_frames(path, W, H, fps, max_secs=8.0):
    """Decode a clip to uint8 frames (n, H, W, 3), scaled to cover W x H at `fps`."""
    ffmpeg, _ = _ff()
    vf = f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=rgb24"
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-t", f"{max_secs}", "-vf", vf, "-f", "rawvideo", "-"],
                         check=True, capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8)
    n = len(fr) // (W * H * 3)
    if n == 0:
        raise ValueError(f"no frames decoded from {path}")
    return fr[: n * W * H * 3].reshape(n, H, W, 3)


def measure_loudness(path):
    """Integrated loudness (LUFS) and true peak (dBTP) with ffmpeg's EBU R128 meter."""
    ffmpeg, _ = _ff()
    err = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    s = err[err.rindex("Summary:"):]
    return {"I": float(s.split("I:")[1].split("LUFS")[0]), "TP": float(s.split("Peak:")[1].split("dBFS")[0])}


def write_wav(path, samples, sr):
    """Float samples (channels, n) or (n,) -> 16-bit PCM wav."""
    a = np.asarray(samples, dtype=np.float32)
    if a.ndim == 1:
        a = a[None]
    a = np.clip(a, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(a.shape[0]); w.setsampwidth(2); w.setframerate(int(sr))
        w.writeframes((a.T * 32767).astype("<i2").tobytes())
    return Path(path)


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        n, ch, sr, sw = w.getnframes(), w.getnchannels(), w.getframerate(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("only 16-bit wav")
    a = np.frombuffer(raw, "<i2").astype(np.float32).reshape(-1, ch).T / 32768.0
    return a, sr


def decode_audio(path, sr=44100):
    """Any audio file -> float32 (2, n) at sr, via ffmpeg."""
    ffmpeg, _ = _ff()
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, "<f4").reshape(-1, 2).T.copy(), sr


# ---------------------------------------------------------------- per-frame effects (numpy, so they are exact and testable)
def _zoom(fr, z):
    if z <= 1.0001:
        return fr
    H, W = fr.shape[:2]
    h, w = int(round(H / z)), int(round(W / z))
    y, x = int((H - h) * 0.3), (W - w) // 2   # lean to the top: keep the head in frame
    return np.asarray(Image.fromarray(fr[y:y + h, x:x + w]).resize((W, H), Image.BILINEAR))


def _whip(fr, amount, direction=1):
    """Horizontal whip pan: shift + motion blur, amount 0..1."""
    if amount <= 0.01:
        return fr
    W = fr.shape[1]
    shift = int(direction * amount * W * 0.35)
    taps = max(2, int(amount * 9))
    acc = np.zeros_like(fr, dtype=np.float32)
    for t in range(taps):
        acc += np.roll(fr, shift + int(direction * t * amount * W * 0.04), axis=1)
    return (acc / taps).astype(np.uint8)


def _flash(fr, amount):
    if amount <= 0.01:
        return fr
    return (fr.astype(np.float32) * (1 - amount) + 255 * amount).astype(np.uint8)


def kenburns(still, n, W, H, k, punch):
    """Free draft motion for a still: a slow push-in or pull-out with a small drift, so drafts are not frozen frames.
    The crop leans to the top of the frame so a full-body photo keeps the head in."""
    base = cover(Image.fromarray(still) if isinstance(still, np.ndarray) else still, W, H)
    frames = []
    for i in range(n):
        p = i / max(1, n - 1)
        z = 1.03 + 0.07 * (p if k % 2 == 0 else 1 - p)
        cw, ch = W / z, H / z
        x = (W - cw) * (0.5 + (0.3 if k % 3 == 0 else -0.3) * (p - 0.5))
        y = (H - ch) * 0.3
        frames.append(np.asarray(base.resize((W, H), Image.BILINEAR, box=(x, y, x + cw, y + ch))))
    return np.stack(frames)


def background_drift(frames):
    """How far each frame's background (top band and side strips, where the person rarely is) has moved from frame 0,
    as mean absolute difference in 0..255. Kling sometimes walks the person into a new place mid-clip."""
    def band(x):
        return np.concatenate([x[:60].reshape(-1, 3), x[:, :70].reshape(-1, 3), x[:, -70:].reshape(-1, 3)]).astype(np.float32)
    b0 = band(frames[0])
    return np.array([np.abs(band(f) - b0).mean() for f in frames])


def drift_cut(frames, limit=45.0, hold=4, min_frames=30):
    """Frames to keep: everything before the background drifts past `limit` and stays there for `hold` frames.
    Calibrated on the paid demo clips: clips that stay in the studio peak near 36, clips that walk onto a street jump
    past 55 and stay. At least `min_frames` are kept."""
    d = background_drift(frames)
    over = d > limit
    for i in range(len(d) - hold + 1):
        if over[i:i + hold].all():
            return max(min_frames, i)
    return len(frames)


def _band(x):
    """Background pixels: the top band and the side strips of a frame (or a stack of frames)."""
    x = x if x.ndim == 4 else x[None]
    return np.concatenate([x[:, :60].reshape(-1, 3), x[:, :, :70].reshape(-1, 3), x[:, :, -70:].reshape(-1, 3)]).astype(np.float32)


def match_colour(frames, ref, strength=0.6, stats_from=None):
    """Even out exposure between looks so cuts don't flicker, WITHOUT changing the garments' own colours: one brightness
    gain for all three channels (so every hue ratio is kept exactly; a per-channel white-balance shift turned a navy
    suit charcoal), measured on the background (top band and side strips) of `stats_from` (default: all frames)
    against the reference look's background. strength 0 = untouched."""
    a, r = _band(frames if stats_from is None else stats_from), _band(ref)
    gain = np.clip((r.mean() / max(a.mean(), 1e-3)) ** strength, 0.8, 1.25)
    return np.clip(frames.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def detail_kenburns(still, n, W, H):
    """Free draft stand-in for the close-up angle: a slow push into the chest-to-waist area of the look photo."""
    base = cover(Image.fromarray(still) if isinstance(still, np.ndarray) else still, W, H)
    frames = []
    for i in range(n):
        z = 2.0 + 0.25 * i / max(1, n - 1)
        cw, ch = W / z, H / z
        x, y = (W - cw) / 2, H * 0.42 - ch / 2
        frames.append(np.asarray(base.resize((W, H), Image.BILINEAR, box=(x, y, x + cw, y + ch))))
    return np.stack(frames)


def lineup_boxes(n, W, H, gap=12, top=0, bottom=0):
    """Grid boxes (x, y, w, h) for n tiles of the reel's own aspect: 2 in a row, 3 in a row, 2x2, 3+2. top/bottom:
    pixels kept free for the brand bands."""
    cols = {1: 1, 2: 2, 3: 3, 4: 2, 5: 3}.get(n, 3)
    rows = -(-n // cols)
    avail = H - top - bottom
    w = min((W - (cols + 1) * gap) / cols, (avail - (rows + 1) * gap) / rows * W / H)
    h = w * H / W
    y0 = top + (avail - rows * h - (rows - 1) * gap) / 2
    boxes = []
    for k in range(n):
        r, c = divmod(k, cols)
        in_row = min(cols, n - r * cols)
        x0 = (W - in_row * w - (in_row - 1) * gap) / 2
        boxes.append((int(x0 + c * (w + gap)), int(y0 + r * (h + gap)), int(w), int(h)))
    return boxes


def brand_bands(W, H, brand, logo=None, numbered=False):
    """Top band: logo and shop name. Bottom band: the call to action and the handle. Returns (top_img, bottom_img)
    as RGBA, or (None, None) when there is nothing to show."""
    name, handle, cta = brand.get("name", ""), brand.get("handle", ""), brand.get("cta", "")
    if numbered and not cta:
        cta = "Comment a number to shop"
    if not (name or handle or cta or logo is not None):
        return None, None
    th, bh = int(H * 0.15), int(H * 0.17)
    top = Image.new("RGBA", (W, th), (0, 0, 0, 0)); d = ImageDraw.Draw(top)
    y = th * 0.18
    if logo is not None:
        lg = logo.convert("RGBA"); lg.thumbnail((int(W * 0.5), int(th * 0.42)), Image.LANCZOS)
        top.paste(lg, ((W - lg.width) // 2, int(y)), lg); y += lg.height + th * 0.06
    if name:
        f = _font(max(28, W // 15))
        while d.textlength(name, font=f) > W * 0.9 and f.size > 16:
            f = _font(f.size - 2)
        d.text(((W - d.textlength(name, font=f)) / 2, y), name, font=f, fill=(245, 236, 222))
    bot = Image.new("RGBA", (W, bh), (0, 0, 0, 0)); d = ImageDraw.Draw(bot)
    y = bh * 0.12
    if cta:
        f = _font(max(26, W // 18))
        while d.textlength(cta, font=f) > W * 0.9 and f.size > 14:
            f = _font(f.size - 2)
        d.text(((W - d.textlength(cta, font=f)) / 2, y), cta, font=f, fill=ACCENT); y += f.size * 1.45
    if handle:
        f = _font(max(20, W // 26))
        d.text(((W - d.textlength(handle, font=f)) / 2, y), handle, font=f, fill=(245, 236, 222))
    return top, bot


def lineup_frames(stills, n, W, H, pop_frames, bg=(24, 21, 18), brand=None, logo=None, numbered=False):
    """The finale: every look in a grid, each tile popping in on its beat (scale-in plus a short flash). With a brand,
    numbered tiles sit between the shop name (top) and the call to action and handle (bottom)."""
    top_b, bot_b = brand_bands(W, H, brand or {}, logo, numbered)
    boxes = lineup_boxes(len(stills), W, H, top=top_b.height if top_b else 0, bottom=bot_b.height if bot_b else 0)
    tiles = [Image.fromarray(st).resize((b[2], b[3]), Image.LANCZOS) for st, b in zip(stills, boxes)]
    if numbered:
        for k, t in enumerate(tiles):
            badge = look_tag_png(k + 1, "", t.width * 3)
            badge = badge.crop((0, 0, int(badge.height * 1.5), badge.height))
            t.paste(badge, (10, 10), badge)
    out = np.zeros((n, H, W, 3), np.uint8)
    for i in range(n):
        im = Image.new("RGB", (W, H), bg)
        flash = 0.0
        for t, b, pf in zip(tiles, boxes, pop_frames):
            if i < pf:
                continue
            a = max(0.0, 1 - (i - pf) / 5)
            sc = 1 + 0.22 * a
            tw, th = int(b[2] * sc), int(b[3] * sc)
            tt = t.resize((tw, th), Image.BILINEAR) if a > 0 else t
            if a > 0:   # the tile itself flashes as it lands; the rest of the frame stays put
                tt = Image.fromarray(_flash(np.asarray(tt), 0.45 * a * a))
            im.paste(tt, (b[0] - (tw - b[2]) // 2, b[1] - (th - b[3]) // 2))
        if top_b is not None and i >= pop_frames[0]:
            fade = min(1.0, (i - pop_frames[0] + 1) / 6)
            for band, y in ((top_b, 0), (bot_b, H - bot_b.height)):
                b2 = band.copy(); b2.putalpha(b2.getchannel("A").point(lambda v: int(v * fade)))
                im.paste(b2, (0, y), b2)
        out[i] = _flash(np.asarray(im), flash)
    return out


def warm_grade(frames, seed=0):
    """Brand style grade: a little warmer, soft lifted blacks and a light film grain (the warm, natural look of brand
    try-on posts instead of a flat grey). In place, chunked to keep memory flat."""
    rng = np.random.default_rng(seed)
    gain = np.array([1.04, 1.0, 0.94], np.float32)
    for i in range(0, len(frames), 16):
        f = frames[i:i + 16].astype(np.float32)
        f = 10 + f * gain * (235 / 255)
        f += rng.normal(0, 3.2, f.shape[:3])[..., None].astype(np.float32)
        frames[i:i + 16] = np.clip(f, 0, 255).astype(np.uint8)
    return frames


def _soft_text(txt, f, fill=(255, 255, 255)):
    """Text with a soft shadow, no box (brand posts' small type). Dark ink gets a light glow instead of a shadow."""
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = int(np.ceil(d.textlength(txt, font=f))) + 12
    h = int(f.size * 1.4) + 8
    sh = Image.new("RGBA", (tw, h), (0, 0, 0, 0))
    glow = (255, 255, 255, 110) if sum(fill[:3]) < 300 else (0, 0, 0, 150)
    ImageDraw.Draw(sh).text((6, 5), txt, font=f, fill=glow)
    sh = sh.filter(ImageFilter.GaussianBlur(3))
    ImageDraw.Draw(sh).text((6, 4), txt, font=f, fill=fill)
    return sh


INK_DARK = (34, 30, 27)


def ink_for(region):
    """White text on a dark or busy area, dark text on a light wall (white-on-white is what kills brand text)."""
    return INK_DARK if float(np.median(np.asarray(region, np.float32).mean(axis=-1))) > 165 else (255, 255, 255)


def small_tag_png(txt, W, fill=(255, 255, 255)):
    """Brand style item tag: just the name (and the price when prices are on), small, top right."""
    return _soft_text(txt, _font(max(18, W // 28)), fill)


def headline_png(txt, W, fill=(255, 255, 255)):
    """Brand style headline: one short line for the whole reel, top third, medium weight, soft shadow."""
    f = _font(max(28, W // 15))
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    while d.textlength(txt, font=f) > W * 0.86 and f.size > 20:
        f = _font(f.size - 2)
    return _soft_text(txt, f, fill)


def card_frames(n, W, H, brand, bg):
    """Brand style ending: a plain card in the set's own wall colour with the handle (and shop name / call to action
    when given). Dark text on a light wall, light text on a dark one."""
    bg = tuple(int(c) for c in bg)
    ink = (34, 30, 27) if sum(bg) / 3 > 140 else (245, 238, 228)
    im = Image.new("RGB", (W, H), bg); d = ImageDraw.Draw(im)
    rows = [(brand.get("name", ""), max(30, W // 14)), (brand.get("handle", ""), max(22, W // 22)), (brand.get("cta", ""), max(18, W // 30))]
    rows = [(t, z) for t, z in rows if t]
    y = H * 0.46 - sum(z * 1.5 for _, z in rows) / 2
    for t, z in rows:
        f = _font(z)
        d.text(((W - d.textlength(t, font=f)) / 2, y), t, font=f, fill=ink); y += z * 1.5
    still = np.asarray(im)
    return np.repeat(still[None], max(n, 1), axis=0)


def _rgb_split(fr, px):
    if px < 1:
        return fr
    out = fr.copy()
    out[..., 0] = np.roll(fr[..., 0], px, axis=1)
    out[..., 2] = np.roll(fr[..., 2], -px, axis=1)
    return out


# ---------------------------------------------------------------- the edit
def render(looks, beats, out, work, brief, fps=30, music_path=None, sr=44100, labels=None, before=None, logo=None):
    """Cut the looks to the beat. looks: list of dicts {"clip": path} (generated motion) or {"still": PIL/ndarray}
    (free draft: Ken Burns), each optionally with "tile" (the still used in the lineup finale). before: the plain
    person photo for the before->after hook. beats: detect_beats() output for the music in music_path."""
    ffmpeg, _ = _ff()
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    W, H = ASPECTS[brief["aspect"]]
    L = float(brief["length"])
    brand = brief.get("style") == "brand"
    hook = "before" if brief.get("hook") is True else brief.get("hook")
    plan = plan_cuts(beats, len(looks), L, hook=None if (hook == "before" and before is None) else hook,
                     lineup=brief.get("lineup", False), pattern=brief.get("pattern"),
                     card=brand and bool((brief.get("brand") or {}).get("handle")))
    if hook == "before" and before is None:
        plan["skipped"].append("hook: no person photo given")
    n_total = int(round(L * fps))
    vibe = brief["vibe"]
    fx_cycle = [None] if brand else VIBES[vibe]["fx"]   # brand style: plain hard cuts
    punch = PUNCH[vibe]
    # source frames for each look
    src, trimmed = [], {}
    angles = bool(brief.get("angles")) and len(brief.get("shots") or []) > 1
    win = []   # per look: the usable frame windows of each storyboard shot (drift-guarded per shot)
    for k, lk in enumerate(looks):
        if lk.get("clip"):
            fr = read_frames(lk["clip"], W, H, fps, max_secs=sum(brief.get("shots") or [8]) + 1)
            bounds = np.cumsum([0] + list(brief["shots"])) * fps if angles else [0, len(fr)]
            ws = []
            for j in range(len(bounds) - 1):
                a, b = int(round(bounds[j])), min(len(fr), int(round(bounds[j + 1])))
                if b - a < 4:
                    continue
                keep = drift_cut(fr[a:b], min_frames=min(30, b - a))
                if keep < b - a:
                    trimmed[f"{k + 1}.{j + 1}" if angles else k + 1] = [keep, b - a]
                ws.append((a, a + keep))
            src.append(fr); win.append(ws)
        else:
            n_need = sum(int(round((s["t1"] - s["t0"]) * fps)) + 8 for s in plan["segments"] if s["look"] == k)
            src.append(kenburns(lk["still"], max(n_need, 8), W, H, k, punch)); win.append([(0, len(src[-1]))])
    for k in range(1, len(src)):   # even out exposure and white balance against look 1, measured on the background
        a, b = win[k][0]; ra, rb = win[0][0]
        src[k] = match_colour(src[k], src[0][ra:rb], stats_from=src[k][a:b])
    tiles = []
    for k, lk in enumerate(looks):
        t = lk.get("tile")
        tiles.append(match_colour(np.asarray(cover(t if isinstance(t, Image.Image) else Image.fromarray(t), W, H))[None],
                                  src[0][:1])[0] if t is not None else src[k][win[k][0][0]])
    seg_src = {}
    for si, s in enumerate(plan["segments"]):
        n = min(int(round(s["t1"] * fps)), n_total) - int(round(s["t0"] * fps))
        if s["kind"] == "before":
            seg_src[si] = kenburns(before, n + 10, W, H, 0, punch)
        elif s["kind"] == "look" and s.get("shot") == 1 and not looks[s["look"]].get("clip"):
            seg_src[si] = detail_kenburns(looks[s["look"]]["still"], n + 10, W, H)   # draft stand-in for the close-up
        elif s["kind"] == "card":
            fr0 = src[0][win[0][0][0]]
            seg_src[si] = card_frames(n, W, H, brief.get("brand") or {}, np.median(fr0[: H // 6].reshape(-1, 3), axis=0))
        elif s["kind"] == "lineup":
            f0 = int(round(s["t0"] * fps))
            seg_src[si] = lineup_frames(tiles, n, W, H, [int(round(p * fps)) - f0 for p in s["pops"]],
                                        brand=brief.get("brand"), logo=logo, numbered=bool(brief.get("labels")))
    cursor = [0] * len(looks)
    frames = np.zeros((n_total, H, W, 3), np.uint8)
    cut_frames = []
    fx_used = []
    for si, s in enumerate(plan["segments"]):
        f0, f1 = int(round(s["t0"] * fps)), int(round(s["t1"] * fps))
        f1 = min(f1, n_total)
        n = f1 - f0
        if n <= 0:
            continue
        cut_frames.append(f0)
        if s["kind"] in ("lineup", "card"):
            frames[f0:f1] = seg_src[si][:n]
            fx_used.append("pop" if s["kind"] == "lineup" else None)
            continue
        S = seg_src[si] if si in seg_src else src[s["look"]]
        ramp = min(max(2, n // 4), 8) if si + 1 < len(plan["segments"]) and not brand else 0   # speed up into the next cut
        idx = np.arange(n, dtype=float)
        if ramp:
            j = idx[n - ramp:] - (n - ramp)
            idx[n - ramp:] = (n - ramp) + j + j * (j + 1) / (2 * ramp) * 2   # accelerates to ~2x at the cut
        need = int(idx[-1]) + 1
        ck = s["look"] if (s["kind"] in ("look", "teaser") and si not in seg_src) else None
        if ck is not None and s["kind"] == "teaser":
            # teaser: a beat of the look's first shot, from a third of the way in (the model is already moving)
            a, b = win[ck][0]
            src_idx = np.clip((a + (b - a) // 3 + idx).astype(int), a, b - 1)
        elif ck is not None and angles and looks[ck].get("clip") and s.get("shot") is not None and s["shot"] < len(win[ck]):
            # camera angles: play this storyboard shot's whole window in the slot (up to 1.6x, centred when longer)
            a, b = win[ck][s["shot"]]
            speed = min(1.6, max(1.0, (b - a) / max(need, 1)))
            off = a + max(0.0, ((b - a) - need * speed) / 2)
            src_idx = np.clip((off + idx * speed).astype(int), a, b - 1)
        elif ck is not None:
            a, b = win[ck][0]
            if cursor[ck] + need > b - a:   # used up: start the look's motion again
                cursor[ck] = 0
            src_idx = np.clip((a + cursor[ck] + idx).astype(int), a, b - 1)
            cursor[ck] += need
        else:
            src_idx = np.clip(idx.astype(int), 0, len(S) - 1)
        fx = fx_cycle[si % len(fx_cycle)] if s["kind"] == "look" else None
        glow = (not brand and brief.get("glowup", False) and s["kind"] == "look" and si > 0 and plan["segments"][si - 1]["kind"] == "before")
        if glow:
            fx = "glow-up"
        fx_used.append(fx)
        # beat pulse: a small zoom breath on every beat that falls inside the shot (cuts already have their hit)
        pulse_at = ([int(round((b - s["t0"]) * fps)) for b in plan["beat_times"] if s["t0"] + 0.1 < b < s["t1"] - 0.1]
                    if brief.get("pulse", False) and s["kind"] == "look" and not brand else [])
        prev = frames[f0 - 1].copy() if f0 > 0 else None
        for i in range(n):
            fr = S[src_idx[i]]
            if glow and prev is not None:   # the glow-up: stutter between before and after, then flash + RGB split
                if i < 4:
                    frames[f0 + i] = prev if i % 2 else _flash(fr, 0.5)
                    continue
                a = max(0.0, 1 - (i - 4) / 7)
                fr = _rgb_split(_flash(_zoom(fr, 1 + punch * a), 0.45 * a * a), int(16 * a))
                frames[f0 + i] = fr
                continue
            for pf in pulse_at:
                if 0 <= i - pf < 5:
                    fr = _zoom(fr, 1 + 0.035 * (1 - (i - pf) / 5))
            if i < 5:   # the hit, on the beat
                a = 1 - i / 5
                if fx == "punch":
                    fr = _zoom(fr, 1 + punch * a)
                elif fx == "flash":
                    fr = _flash(_zoom(fr, 1 + punch * 0.5 * a), 0.85 * a * a)
                elif fx == "whip":
                    fr = _whip(fr, a, direction=-1)
            nxt = plan["segments"][si + 1] if si + 1 < len(plan["segments"]) else None
            glow_next = brief.get("glowup", False) and s["kind"] == "before" and not brand
            if ramp and i >= n - 3 and nxt and nxt["kind"] == "look" and not glow_next and fx_cycle[(si + 1) % len(fx_cycle)] == "whip":
                fr = _whip(fr, (i - (n - 4)) / 3, direction=1)
            frames[f0 + i] = fr
    # loop: blend the last frames into the first so frame[-1] == frame[0]
    nb = min(int(round(fps * 60 / max(beats["bpm"], 1) / 2)), max(2, n_total // 10))
    first = frames[0].astype(np.float32)
    for i in range(nb):
        a = (i + 1) / nb
        k = n_total - nb + i
        frames[k] = (frames[k].astype(np.float32) * (1 - a) + first * a).round().astype(np.uint8)
    if brand:
        warm_grade(frames)
        frames[-1] = frames[0]   # the grain is random per frame: keep the loop seam exact
    # overlays: headline (brand: the whole reel; hype: the first look), item tags, AI label throughout
    over = []
    tags = brief.get("labels") or []
    if not brief.get("prices", True):
        tags = [t.split(" · ")[0] for t in tags]
    end_f = next((cut_frames[k] for k, s in enumerate(plan["segments"]) if s["kind"] in ("lineup", "card")), n_total - nb)
    if brand:
        if brief.get("headline"):
            cap = headline_png(brief["headline"], W)
            y = int(H * 0.14)
            cap = headline_png(brief["headline"], W, ink_for(frames[:end_f:15, y:y + cap.height, (W - cap.width) // 2:(W + cap.width) // 2]))
            over.append((cap, ((W - cap.width) // 2, int(H * 0.14)), 0, end_f))
        for k, s in enumerate(plan["segments"]):
            if s["kind"] == "look" and s["look"] < len(tags) and tags[s["look"]]:
                tag = small_tag_png(tags[s["look"]], W)
                a1 = cut_frames[k + 1] if k + 1 < len(cut_frames) else end_f
                x, y = W - tag.width - int(W * 0.04), int(H * 0.055)
                tag = small_tag_png(tags[s["look"]], W, ink_for(frames[cut_frames[k]:a1:5, y:y + tag.height, x:x + tag.width]))
                over.append((tag, (x, y), cut_frames[k], a1))
    elif brief.get("headline"):
        cap = text_png(brief["headline"], max(36, W // 12), W)
        first_look = next(k for k, s in enumerate(plan["segments"]) if s["kind"] == "look")
        a0 = cut_frames[first_look]
        a1 = cut_frames[first_look + 1] if first_look + 1 < len(cut_frames) else n_total
        over.append((cap, ((W - cap.width) // 2, int(H * 0.12)), a0, a1))
    for k, s in enumerate(plan["segments"] if not brand else []):
        if s["kind"] == "look" and s["look"] < len(tags) and tags[s["look"]]:
            tag = look_tag_png(s["look"] + 1, tags[s["look"]], W)
            a0 = cut_frames[k] + (5 if fx_used[k] == "glow-up" else 2)   # after the glow-up stutter
            a1 = cut_frames[k + 1] if k + 1 < len(cut_frames) else n_total - nb
            over.append((tag, (int(W * 0.05), int(H * 0.72)), a0, a1))   # clear of the Reels/TikTok caption and buttons
    lab_txt = (labels or {}).get("label", "AI-generated" if brief.get("ai_label", True) else "")
    if lab_txt:
        over.append((label_png(lab_txt, W), (24, 24), 0, n_total))
    if over:
        for i in range(n_total):
            act = [o for o in over if o[2] <= i < o[3]]
            if not act:
                continue
            im = Image.fromarray(frames[i])
            for ov, pos, _, _ in act:
                im.paste(ov, pos, ov)
            frames[i] = np.asarray(im)
    # sound: the music from the first downbeat, trimmed to L, normalised to -14 LUFS / -1 dBTP (gain + limiter, re-measured; the
    # limiter aims 1 dB lower because the AAC encode adds a few tenths of overshoot)
    audio_in = work / "music_cut.wav"
    a, asr = decode_audio(music_path, sr)
    s0 = int(round(plan["music_start"] * asr))
    seg = a[:, s0:s0 + int(round(L * asr))]
    if seg.shape[1] < int(round(L * asr)):
        seg = np.pad(seg, ((0, 0), (0, int(round(L * asr)) - seg.shape[1])))
    fade = int(0.008 * asr)
    seg[:, :fade] *= np.linspace(0, 1, fade)
    seg[:, -fade:] *= np.linspace(1, 0, fade)
    write_wav(audio_in, seg, asr)
    audio_norm = work / "music_norm.wav"
    m0 = measure_loudness(audio_in)
    gain = -14.0 - m0["I"]
    for _ in range(4):   # gain + sample-peak limiter, re-measured until it lands on -14 LUFS
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(audio_in), "-af",
                        f"volume={gain:.3f}dB,alimiter=limit={10 ** (TP_HEADROOM / 20):.4f}:attack=1:release=60:level=false",
                        "-t", f"{L:.3f}", str(audio_norm)], check=True)
        m = measure_loudness(audio_norm)
        if abs(m["I"] + 14.0) < 0.3:
            break
        gain += -14.0 - m["I"]
    # encode: raw frames in, H.264 + AAC out, exact length
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(audio_norm), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{L:.3f}", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    p.stdin.write(frames.tobytes()); p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")
    cut_list = [{"kind": s["kind"], "look": s["look"] + 1 if s["look"] is not None else None, "start": s["t0"], "end": s["t1"],
                 "fx": fx_used[k] if k < len(fx_used) else None, **({"pops": s["pops"]} if "pops" in s else {})}
                for k, s in enumerate(plan["segments"])]
    receipt = {"length": L, "fps": fps, "size": [W, H], "bpm": beats["bpm"], "beat_method": beats["method"],
               "music_start": plan["music_start"],
               "beat_times_in_reel": [b for b in plan["beat_times"]],
               "cut_times": plan["cuts"], "cut_snapped_to": plan["snapped"], "cuts": cut_list, "loop_blend_frames": nb,
               "loudness": {"target_I": -14, "target_TP": -1, "music_I": m0["I"], "out_I": m["I"], "out_TP": m["TP"],
                            "gain_db": round(gain, 2)},
               "label": lab_txt or None, "headline": brief.get("headline") or None,
               "style": brief.get("style", "hype"), "set": brief.get("set", "photo"),
               "hook": plan["hook"], "lineup": plan["segments"][-1]["kind"] == "lineup",
               "card": plan["segments"][-1]["kind"] == "card", "prices": bool(brief.get("prices", True)),
               "look_labels": brief.get("labels") or [], "brand": brief.get("brand") or {}, "logo": logo is not None,
               "pulse": bool(brief.get("pulse")), "glowup": any(f == "glow-up" for f in fx_used),
               "skipped": plan["skipped"], "drift_trimmed": {k: f"kept {a} of {b} frames" for k, (a, b) in trimmed.items()}}
    (work / "receipt.json").write_text(json.dumps(receipt, indent=1))
    np.save(work / "first_last.npy", np.stack([frames[0], frames[-1]]))
    receipt["_thumbs"] = [frames[min(f + 2, n_total - 1)] if s["kind"] not in ("lineup", "card") else frames[n_total - nb - 1]
                          for f, s in zip(cut_frames, plan["segments"])]
    return receipt


def contact_sheet(looks, thumbs, cuts, out=None, tw=180, th=320):
    """Top row: the looks. Below: one frame per cut with its time and effect. Approve this before paying for motion."""
    cols = max(len(looks), min(len(thumbs), 6))
    rows_t = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, th + 40 + rows_t * (th + 40)), (24, 21, 18)); d = ImageDraw.Draw(sheet)
    f = _font(15)
    for k, im in enumerate(looks):
        im = cover(im if isinstance(im, Image.Image) else Image.fromarray(im), tw, th)
        sheet.paste(im, (k * tw, 0)); d.text((k * tw + 8, th + 10), f"look {k + 1}", font=f, fill=(240, 232, 220))
    for k, (fr, c) in enumerate(zip(thumbs, cuts)):
        x, y = (k % cols) * tw, th + 40 + (k // cols) * (th + 40)
        sheet.paste(cover(Image.fromarray(fr), tw, th), (x, y))
        d.text((x + 8, y + th + 10), f"{c['start']:.2f}s  " + (f"look {c['look']}  {c['fx'] or ''}" if c.get("kind", "look") == "look" else c["kind"]), font=f, fill=(240, 232, 220))
    if out:
        sheet.save(out)
    return sheet


def cost_estimate(brief, n_looks, clip_seconds=None, generated_motion=True):
    """What a full partner run costs, from the nodes' own price badges. A draft run costs $0."""
    rows = []
    if not generated_motion:
        return {"total_usd": 0.0, "rows": [["free draft (no partner nodes)", 0, 0.0]]}
    if brief["engine"] == "kling":
        rows.append(["Kling Virtual Try-On", n_looks, round(PRICES["KlingTryOnNode"] * n_looks, 4)])
    else:
        rows.append(["Nano Banana 2.1 edit (1K, minimal thinking)", n_looks, round(PRICES["GeminiNanoBanana2V2_1K_minimal"] * n_looks, 4)])
    if clip_seconds is None:
        clip_seconds = sum(brief.get("shots") or [CLIP_SECONDS])
    if brief.get("set") == "room":
        rows.append(["Nano Banana 2.1 edit: move the look into the white wall room", n_looks,
                     round(PRICES["GeminiNanoBanana2V2_1K_minimal"] * n_looks, 4)])
    what = (("pose sequence" if brief.get("style") == "brand" else "turnaround") + " + close-up storyboard"
            if brief.get("angles") else "image-to-video")
    rows.append([f"Kling 3.0 {what}, 720p, {clip_seconds} s, no audio", n_looks,
                 round(PRICES["KlingVideoNode_720p_per_s"] * clip_seconds * n_looks, 4)])
    if brief["music"] == "sonilo":
        rows.append([f"Sonilo text to music, {brief['music_seconds']} s", 1, round(PRICES["SoniloTextToMusic_per_s"] * brief["music_seconds"], 4)])
    return {"total_usd": round(sum(r[2] for r in rows), 4), "rows": rows}


# ---------------------------------------------------------------- free sample assets (original, no licence needed)
def click_track(bpm=120.0, secs=12.0, sr=44100, accent=True):
    """A synthetic click track: a short 1.5 kHz click on every beat, louder on the downbeat. For tests."""
    y = np.zeros(int(secs * sr), np.float32)
    n = int(0.01 * sr)
    click = np.sin(2 * np.pi * 1500 * np.arange(n) / sr) * np.exp(-np.arange(n) / (0.002 * sr))
    k = 0
    while True:
        t = k * 60.0 / bpm
        i = int(round(t * sr))
        if i + n > len(y):
            break
        y[i:i + n] += (0.9 if (accent and k % 4 == 0) else 0.5) * click
        k += 1
    return np.stack([y, y]), sr


def sample_beat(bpm=112.0, secs=16.0, sr=44100, seed=7):
    """An original, code-made instrumental (kick, snare, hats, bass, chord stabs) so the free draft has music with
    no licence question. Not a substitute for real music in a posted reel."""
    rng = np.random.default_rng(seed)
    n = int(secs * sr)
    t = np.arange(n) / sr
    y = np.zeros(n)
    beat = 60.0 / bpm
    def add(at, sig):
        i = int(at * sr); j = min(n, i + len(sig))
        if i < n:
            y[i:j] += sig[: j - i]
    kl = int(0.25 * sr); tk = np.arange(kl) / sr
    kick = np.sin(2 * np.pi * (45 + 90 * np.exp(-tk * 40)) * tk) * np.exp(-tk * 9) * 0.9
    sl = int(0.18 * sr); ts = np.arange(sl) / sr
    snare = (rng.standard_normal(sl) * 0.5 + np.sin(2 * np.pi * 190 * ts) * 0.4) * np.exp(-ts * 22) * 0.55
    hl = int(0.05 * sr); th = np.arange(hl) / sr
    hat = rng.standard_normal(hl) * np.exp(-th * 90) * 0.12
    chords = [(220.0, 277.18, 329.63), (196.0, 246.94, 293.66), (174.61, 220.0, 261.63), (196.0, 246.94, 311.13)]
    nb = int(secs / beat)
    for b in range(nb):
        at = b * beat
        if b % 4 in (0, 2) or (b % 8 == 7):
            add(at, kick)
        if b % 4 in (1, 3):
            add(at, snare)
        add(at + beat / 2, hat); add(at, hat * 0.6)
        bar = (b // 4) % 4
        root = chords[bar][0] / 2
        bl = int(beat * 0.9 * sr); tb = np.arange(bl) / sr
        add(at, np.sin(2 * np.pi * root * tb) * np.exp(-tb * 3) * 0.35)
        if b % 4 == 0 or b % 4 == 2.5:
            cl = int(beat * 0.6 * sr); tc = np.arange(cl) / sr
            add(at, sum(np.sign(np.sin(2 * np.pi * f * tc)) * 0.04 for f in chords[bar]) * np.exp(-tc * 6))
    y = y / max(1e-6, np.abs(y).max()) * 0.8
    return np.stack([y, y]).astype(np.float32), sr
