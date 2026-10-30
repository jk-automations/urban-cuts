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
MAX_LOOKS = 5
CLIP_SECONDS = 3                       # Kling 3.0 image-to-video, the shortest (cheapest) clip
PUNCH = {"street": 0.14, "runway": 0.10, "boutique": 0.07}

# Partner prices, copied from the nodes' own price badges (ComfyUI 0.42 comfy_api_nodes, read 2026-10-29).
PRICES = {"KlingTryOnNode": 0.16016, "GeminiNanoBanana2V2_1K_minimal": 0.048048, "KlingVideoNode_720p_per_s": 0.084,
          "SoniloTextToMusic_per_s": 0.0025}

TP_HEADROOM = -2.5
NEGATIVE = "logos, brand names, text, watermark, extra people, distorted hands, distorted face, blurry, cuts, shaky camera"


# ---------------------------------------------------------------- the brief and the prompts
def make_brief(mode="outfits", vibe="street", length=10.0, aspect="9:16", look_engine=LOOK_ENGINES[0],
               music_source=MUSIC_SOURCES[0], music_prompt="", headline="", consent=False, ai_label=True):
    if not consent:
        raise ValueError("Urban Cuts needs the person's consent: tick 'I have this person's consent to use their photo' "
                         "(you, or someone who agreed). Nothing was generated.")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if vibe not in VIBES:
        raise ValueError(f"vibe must be one of {list(VIBES)}")
    if aspect not in ASPECTS:
        raise ValueError(f"aspect must be one of {list(ASPECTS)}")
    if not 4.0 <= float(length) <= 20.0:
        raise ValueError("length must be 4 to 20 seconds")
    engine = "banana" if mode == "products" or look_engine.startswith("Nano") else "kling"
    music = "sonilo" if music_source.startswith("Sonilo") else "upload"
    mp = music_prompt.strip() or default_music_prompt(vibe)
    return {"mode": mode, "vibe": vibe, "length": float(length), "aspect": aspect, "engine": engine, "music": music,
            "music_prompt": mp, "music_seconds": int(np.ceil(float(length))) + 5, "headline": headline.strip(),
            "ai_label": bool(ai_label)}   # music_seconds: room to start on a downbeat, and Sonilo tracks tail off at the end


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


def motion_prompt(brief, k):
    """The Kling image-to-video prompt for look k: one short continuous move, no cuts (the edit makes the cuts)."""
    v = VIBES[brief["vibe"]]
    move = v["moves"][(k - 1) % len(v["moves"])]
    held = "holding the product toward the camera" if brief["mode"] == "products" else "the outfit stays exactly the same"
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
def plan_cuts(beats, n_looks, length=10.0, beats_per_look=2, start=None):
    """Where each look starts and ends on the music. The reel starts on a downbeat (music offset `start`), a new look
    lands every `beats_per_look` beats, and the looks cycle 1..n. Returns the music offset, the segments
    [{look, t0, t1}] on the reel timeline (t1 of the last = length) and the cut times (reel time) that land on beats."""
    bt = np.array(beats["beats"], dtype=float)
    if n_looks < 1:
        raise ValueError("need at least one look")
    if start is None:   # the first downbeat that still leaves `length` seconds of music after it
        ok = [d for d in beats["downbeats"] if d + length <= beats["duration"] + 1e-6]
        start = ok[0] if ok else (bt[0] if bt[0] + length <= beats["duration"] else 0.0)
    rel = bt[bt >= start - 1e-6] - start
    rel = rel[rel < length - 0.25]   # no cut in the final quarter second
    # Walk the tempo grid (every `beats_per_look` beats from the downbeat) and snap each cut to the detected beat
    # nearest to it. A tracker slip (an extra or missing beat) then cannot shift every later cut off the grid: when no
    # detected beat is within 15% of a beat period, the grid time is used and marked "grid" in `snapped`.
    period = 60.0 / beats["bpm"]
    cuts, snapped = [0.0], []
    while True:
        target = cuts[-1] + beats_per_look * period
        if target >= length - 0.25:
            break
        near = rel[np.argmin(np.abs(rel - target))] if len(rel) else None
        if near is not None and abs(near - target) <= 0.15 * period and near > cuts[-1] + 1e-3:
            cuts.append(float(near)); snapped.append("beat")
        else:
            cuts.append(float(target)); snapped.append("grid")
    if len(cuts) < 2:   # very slow music: fall back to an even grid so every look still shows
        cuts = list(np.linspace(0, length, n_looks + 1)[:-1])
    segs = []
    for k, t0 in enumerate(cuts):
        t1 = cuts[k + 1] if k + 1 < len(cuts) else length
        segs.append({"look": k % n_looks, "t0": round(t0, 4), "t1": round(t1, 4)})
    return {"music_start": round(float(start), 4), "segments": segs, "cuts": [round(c, 4) for c in cuts[1:]], "snapped": snapped,
            "beat_times": [round(float(t), 4) for t in rel], "length": float(length)}


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


# ---------------------------------------------------------------- the edit
def render(looks, beats, out, work, brief, fps=30, music_path=None, sr=44100, labels=None):
    """Cut the looks to the beat. looks: list of dicts {"clip": path} (generated motion) or {"still": PIL/ndarray}
    (free draft: Ken Burns). beats: detect_beats() output for the music in music_path. Returns the receipt."""
    ffmpeg, _ = _ff()
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    W, H = ASPECTS[brief["aspect"]]
    L = float(brief["length"])
    plan = plan_cuts(beats, len(looks), L)
    n_total = int(round(L * fps))
    vibe = brief["vibe"]
    fx_cycle = VIBES[vibe]["fx"]
    punch = PUNCH[vibe]
    # source frames for each look
    src = []
    for k, lk in enumerate(looks):
        if lk.get("clip"):
            src.append(read_frames(lk["clip"], W, H, fps))
        else:
            n_need = sum(int(round((s["t1"] - s["t0"]) * fps)) + 8 for s in plan["segments"] if s["look"] == k)
            src.append(kenburns(lk["still"], max(n_need, 8), W, H, k, punch))
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
        S = src[s["look"]]
        ramp = min(max(2, n // 4), 8) if si + 1 < len(plan["segments"]) else 0   # speed up into the next cut
        idx = np.arange(n, dtype=float)
        if ramp:
            j = idx[n - ramp:] - (n - ramp)
            idx[n - ramp:] = (n - ramp) + j + j * (j + 1) / (2 * ramp) * 2   # accelerates to ~2x at the cut
        need = int(idx[-1]) + 1
        if cursor[s["look"]] + need > len(S):   # used up: start the look's motion again
            cursor[s["look"]] = 0
        src_idx = np.clip((cursor[s["look"]] + idx).astype(int), 0, len(S) - 1)
        cursor[s["look"]] += need
        fx = fx_cycle[si % len(fx_cycle)]
        fx_used.append(fx)
        for i in range(n):
            fr = S[src_idx[i]]
            if i < 5:   # the hit, on the beat
                a = 1 - i / 5
                if fx == "punch":
                    fr = _zoom(fr, 1 + punch * a)
                elif fx == "flash":
                    fr = _flash(_zoom(fr, 1 + punch * 0.5 * a), 0.85 * a * a)
                elif fx == "whip":
                    fr = _whip(fr, a, direction=-1)
            if ramp and i >= n - 3 and fx_cycle[(si + 1) % len(fx_cycle)] == "whip":   # whip out of the shot
                fr = _whip(fr, (i - (n - 4)) / 3, direction=1)
            frames[f0 + i] = fr
    # loop: blend the last frames into the first so frame[-1] == frame[0]
    nb = min(int(round(fps * 60 / max(beats["bpm"], 1) / 2)), max(2, n_total // 10))
    first = frames[0].astype(np.float32)
    for i in range(nb):
        a = (i + 1) / nb
        k = n_total - nb + i
        frames[k] = (frames[k].astype(np.float32) * (1 - a) + first * a).round().astype(np.uint8)
    # overlays: headline on the first look, AI label throughout
    over = []
    if brief.get("headline"):
        cap = text_png(brief["headline"], max(36, W // 12), W)
        over.append((cap, ((W - cap.width) // 2, int(H * 0.12)), 0, min(n_total, cut_frames[1] if len(cut_frames) > 1 else n_total)))
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
    cut_list = [{"look": s["look"] + 1, "start": s["t0"], "end": s["t1"], "fx": fx_used[k] if k < len(fx_used) else None}
                for k, s in enumerate(plan["segments"])]
    receipt = {"length": L, "fps": fps, "size": [W, H], "bpm": beats["bpm"], "beat_method": beats["method"],
               "music_start": plan["music_start"],
               "beat_times_in_reel": [b for b in plan["beat_times"]],
               "cut_times": plan["cuts"], "cut_snapped_to": plan["snapped"], "cuts": cut_list, "loop_blend_frames": nb,
               "loudness": {"target_I": -14, "target_TP": -1, "music_I": m0["I"], "out_I": m["I"], "out_TP": m["TP"],
                            "gain_db": round(gain, 2)},
               "label": lab_txt or None, "headline": brief.get("headline") or None}
    (work / "receipt.json").write_text(json.dumps(receipt, indent=1))
    np.save(work / "first_last.npy", np.stack([frames[0], frames[-1]]))
    receipt["_thumbs"] = [frames[min(f + 2, n_total - 1)] for f in cut_frames]
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
        d.text((x + 8, y + th + 10), f"{c['start']:.2f}s  look {c['look']}  {c['fx'] or ''}", font=f, fill=(240, 232, 220))
    if out:
        sheet.save(out)
    return sheet


def cost_estimate(brief, n_looks, clip_seconds=CLIP_SECONDS, generated_motion=True):
    """What a full partner run costs, from the nodes' own price badges. A draft run costs $0."""
    rows = []
    if not generated_motion:
        return {"total_usd": 0.0, "rows": [["free draft (no partner nodes)", 0, 0.0]]}
    if brief["engine"] == "kling":
        rows.append(["Kling Virtual Try-On", n_looks, round(PRICES["KlingTryOnNode"] * n_looks, 4)])
    else:
        rows.append(["Nano Banana 2.1 edit (1K, minimal thinking)", n_looks, round(PRICES["GeminiNanoBanana2V2_1K_minimal"] * n_looks, 4)])
    rows.append([f"Kling 3.0 image-to-video, 720p, {clip_seconds} s, no audio", n_looks,
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
