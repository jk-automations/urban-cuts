"""Urban Cuts ComfyUI nodes. Paid generation is done by ComfyUI's own partner nodes (Kling Virtual Try-On, Nano Banana
2.1, Kling 3.0 video, Sonilo text to music); these nodes gate on consent, write the prompts, pick the branch that
runs, find the beat and cut the reel. Unused branches are lazy inputs, so ComfyUI never runs (or bills) them."""
import json
import tempfile
from pathlib import Path

import numpy as np
import torch
from PIL import Image

try:
    from . import urban_core as core
except ImportError:  # imported directly (tests)
    import urban_core as core

try:
    from comfy_api.input_impl import VideoFromFile
except ImportError:  # older ComfyUI
    from comfy_api.latest._input_impl import VideoFromFile

CAT = "Urban Cuts"
N = core.MAX_LOOKS


def _pil(img):
    return Image.fromarray((img[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)).convert("RGB")


def _tensor(pil):
    return torch.from_numpy(np.asarray(pil.convert("RGB"), dtype=np.float32) / 255.0)[None]


def _is_blank(img):
    """An unused look slot holds the flat placeholder image."""
    return img is None or float(img[0].float().std()) < 0.01


def _out_dir():
    try:
        import folder_paths
        d = Path(folder_paths.get_temp_directory())
    except ImportError:
        d = Path(tempfile.gettempdir())
    d.mkdir(parents=True, exist_ok=True)
    return d


class UrbanBrief:
    """Your choices, and the consent gate. Every other node (paid ones included) takes its input through this node, so
    an unticked consent box stops the run before anything is generated."""
    CATEGORY = CAT
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("person", "brief", "engine", "music_prompt", "music_seconds")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "person": ("IMAGE", {"tooltip": "One clear full-body photo, 9:16, plain background is best."}),
            "consent": ("BOOLEAN", {"default": False, "tooltip": "I have this person's consent to use their photo (or it is me). "
                                    "The run stops here when this is off."}),
            "mode": (core.MODES, {"default": "outfits", "tooltip": "outfits: the person wears each outfit. products: the "
                                  "person presents each product (a 'new arrivals' reel for a shop)."}),
            "vibe": (list(core.VIBES), {"default": "street", "tooltip": "Sets the scene, the moves and the cut effects."}),
            "length": ("FLOAT", {"default": 10.0, "min": 4.0, "max": 20.0, "step": 0.5}),
            "aspect": (list(core.ASPECTS), {"default": "9:16"}),
            "look_engine": (core.LOOK_ENGINES, {"default": core.LOOK_ENGINES[0], "tooltip": "Kling try-on keeps the pose; "
                            "Nano Banana 2 restages the photo in the vibe's setting. Products always use Nano Banana 2."}),
            "music_source": (core.MUSIC_SOURCES, {"default": core.MUSIC_SOURCES[0]}),
            "music_prompt": ("STRING", {"default": "", "multiline": True, "tooltip": "For Sonilo. Empty = the vibe's default."}),
            "headline": ("STRING", {"default": "", "tooltip": "Optional one short line, e.g. '4 fits, 1 weekend'. Brand "
                         "style: an opening title over plain wall for the first ~4 s. Hype style: big, on the first look."}),
            "ai_label": ("BOOLEAN", {"default": True, "tooltip": "Keep this on when you post."}),
            "hook": (core.HOOKS, {"default": "teaser", "tooltip": "teaser: one beat of every look first (show the range "
                     "up front, like brand posts). before→after: the plain photo for 2 beats, then look 1. off: start on look 1."}),
            "lineup": ("BOOLEAN", {"default": False, "tooltip": "End on a grid of every look, one popping in per beat "
                       "(for 'comment a number to shop' posts). Off + a handle = a plain handle card in brand style."}),
            "look_labels": ("STRING", {"default": "", "multiline": True, "tooltip": "One line per look, in order: "
                            "'Rust bomber jacket | $89'. Shown as a numbered tag on each look; the lineup tiles get the numbers."}),
            "brand_name": ("STRING", {"default": "", "tooltip": "Your shop's name, shown over the lineup."}),
            "handle": ("STRING", {"default": "", "tooltip": "Where to shop: @handle or website, under the lineup."}),
            "cta": ("STRING", {"default": "", "tooltip": "Call to action under the lineup, e.g. 'New in store Friday'. "
                    "Empty with labels = 'Comment a number to shop'."}),
            "pulse": ("BOOLEAN", {"default": True, "tooltip": "A small zoom breath on every beat inside a shot."}),
            "glowup": ("BOOLEAN", {"default": True, "tooltip": "The before->look 1 cut stutters, flashes and splits colour."}),
            "angles": ("BOOLEAN", {"default": True, "tooltip": "Two shots per look from one Kling storyboard (5 s, so face "
                       "and outfit stay the same): brand style = a pose sequence (hand on hip, turn to the back, look over the "
                       "shoulder), hype style = a 360 turnaround; then a close-up on the fabric. Off = one 3 s move."}),
            "style": (core.STYLES, {"default": "brand", "tooltip": "brand: how fashion brands post (plain hard cuts, warm "
                      "grade, small clean text). hype: punch/flash/whip on every beat, glow-up and beat pulse."}),
            "set": (core.SETS, {"default": core.SETS[1], "tooltip": "white wall room: each look is moved into a bright room "
                    "with a white wall and a wooden floor (Nano Banana 2.1 edit, ~$0.05 per look). Or keep your photo's background."}),
            "prices": ("BOOLEAN", {"default": False, "tooltip": "Show the price from 'Look names + prices' on each look."}),
        }}

    def run(self, person, consent, mode, vibe, length, aspect, look_engine, music_source, music_prompt, headline, ai_label,
            hook="teaser", lineup=False, look_labels="", brand_name="", handle="", cta="", pulse=True, glowup=True, angles=True,
            style="brand", set=core.SETS[1], prices=False):
        b = core.make_brief(mode, vibe, length, aspect, look_engine, music_source, music_prompt, headline, consent, ai_label,
                            hook, lineup, look_labels, brand_name, handle, cta, pulse, glowup, angles, style, set, prices)
        return (person, json.dumps(b), b["engine"], b["music_prompt"], b["music_seconds"])


class UrbanShot:
    """Look k: the Nano Banana 2 edit prompt, the Kling motion prompt, the two storyboard prompts (brand: pose sequence,
    hype: turnaround; then the close-up) and the room restage prompt."""
    CATEGORY = CAT
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("look_prompt", "motion_prompt", "shot1_prompt", "closeup_prompt", "room_prompt")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"brief": ("STRING", {"forceInput": True}), "look": ("INT", {"default": 1, "min": 1, "max": N})}}

    def run(self, brief, look):
        b = json.loads(brief)
        return (core.look_prompt(b, look), core.motion_prompt(b, look), *core.shot_prompts(b, look), core.restage_prompt(b, look))


class UrbanPickLook:
    """Use the Kling try-on or the Nano Banana 2 edit for this look. Only the picked one runs (lazy inputs)."""
    CATEGORY = CAT
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("look",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"engine": ("STRING", {"forceInput": True})},
                "optional": {"kling": ("IMAGE", {"lazy": True}), "banana": ("IMAGE", {"lazy": True})}}

    def check_lazy_status(self, engine, kling=None, banana=None):
        want = "kling" if engine == "kling" else "banana"
        return [want] if (kling if want == "kling" else banana) is None else []

    def run(self, engine, kling=None, banana=None):
        img = kling if engine == "kling" else banana
        if img is None:
            raise ValueError(f"no image from the {engine} branch")
        return (img,)


class UrbanSet:
    """Keep the look as it is, or use its 'white wall room' version. The room edit only runs when picked (lazy)."""
    CATEGORY = CAT
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("look",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"brief": ("STRING", {"forceInput": True}), "look": ("IMAGE",)},
                "optional": {"room": ("IMAGE", {"lazy": True})}}

    def check_lazy_status(self, brief, look, room=None):
        return ["room"] if json.loads(brief).get("set") == "room" and room is None and not _is_blank(look) else []

    def run(self, brief, look, room=None):
        if json.loads(brief).get("set") == "room" and not _is_blank(look):
            if room is None:
                raise ValueError("no image from the room edit")
            return (room,)
        return (look,)


class UrbanMusic:
    """Your uploaded track or the Sonilo track. Only the picked one runs (Sonilo is never billed unless picked)."""
    CATEGORY = CAT
    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("music",)
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"brief": ("STRING", {"forceInput": True})},
                "optional": {"uploaded": ("AUDIO", {"lazy": True}), "sonilo": ("AUDIO", {"lazy": True})}}

    def check_lazy_status(self, brief, uploaded=None, sonilo=None):
        want = "sonilo" if json.loads(brief)["music"] == "sonilo" else "uploaded"
        return [want] if (sonilo if want == "sonilo" else uploaded) is None else []

    def run(self, brief, uploaded=None, sonilo=None):
        a = sonilo if json.loads(brief)["music"] == "sonilo" else uploaded
        if a is None:
            raise ValueError("no music")
        return (a,)


def audio_to_numpy(audio):
    w = audio["waveform"]
    w = w[0] if w.ndim == 3 else w
    return w.float().cpu().numpy(), int(audio["sample_rate"])


class UrbanBeatDetect:
    """BPM, beats and downbeats of the music (librosa if installed, else a numpy onset tracker). CPU only, free."""
    CATEGORY = CAT
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("beats", "beats_text")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"music": ("AUDIO",)}}

    def run(self, music):
        y, sr = audio_to_numpy(music)
        b = core.detect_beats(y, sr)
        txt = (f"{b['bpm']} BPM, {len(b['beats'])} beats, {len(b['downbeats'])} downbeats ({b['method']}). "
               f"First beats: {', '.join(f'{t:.2f}s' for t in b['beats'][:8])}")
        return (json.dumps(b), txt)


class UrbanBeatCut:
    """The edit: a new look on every 2nd beat starting on a downbeat, punch-zoom / flash / whip on each hit, a speed
    ramp into every cut, the last frame blends into the first so it loops, -14 LUFS sound, 'AI-generated' label.
    Gives the reel, a contact sheet and a JSON receipt (BPM, beat times, cut list, partner calls, cost).
    Slots whose outfit/product image is the blank placeholder are skipped, and their paid nodes never run."""
    CATEGORY = CAT
    RETURN_TYPES = ("VIDEO", "IMAGE", "STRING")
    RETURN_NAMES = ("reel", "contact_sheet", "receipt")
    FUNCTION = "run"

    @classmethod
    def INPUT_TYPES(cls):
        opt = {}
        for k in range(1, N + 1):
            opt[f"item_{k}"] = ("IMAGE", {"tooltip": f"Outfit or product {k} (the blank placeholder = slot not used)."})
            opt[f"look_{k}"] = ("IMAGE", {"lazy": True, "tooltip": f"The still for look {k} (try-on, edit, or your own photo)."})
            opt[f"clip_{k}"] = ("VIDEO", {"lazy": True, "tooltip": f"Generated motion for look {k}. Empty = free Ken Burns draft."})
        opt["before"] = ("IMAGE", {"tooltip": "The plain person photo for the before->after hook (from Your Choices)."})
        opt["logo"] = ("IMAGE", {"tooltip": "Your logo for the lineup (the blank placeholder = no logo)."})
        return {"required": {"brief": ("STRING", {"forceInput": True}), "music": ("AUDIO",),
                             "beats": ("STRING", {"forceInput": True})}, "optional": opt}

    @staticmethod
    def _used(kw):
        return [k for k in range(1, N + 1) if f"item_{k}" in kw and not _is_blank(kw[f"item_{k}"])]

    def check_lazy_status(self, brief, music, beats, **kw):
        need = []
        for k in self._used(kw):
            for name in (f"look_{k}", f"clip_{k}"):
                if name in kw and kw[name] is None:
                    need.append(name)
        return need

    def run(self, brief, music, beats, **kw):
        b = json.loads(brief)
        used = self._used(kw)
        if len(used) < 1:
            raise ValueError("Add at least one outfit or product image (3 to 5 look best).")
        tmp = Path(tempfile.mkdtemp(prefix="urban_"))
        looks, stills, calls = [], [], []
        for k in used:
            still = kw.get(f"look_{k}")
            still = _pil(still) if still is not None else _pil(kw[f"item_{k}"])
            stills.append(still)
            clip = kw.get(f"clip_{k}")
            if clip is not None:
                p = tmp / f"clip_{k}.mp4"; clip.save_to(str(p))
                looks.append({"clip": p, "tile": still})
            else:
                looks.append({"still": still})
        motion = any("clip" in lk for lk in looks)
        if motion:
            first = "pose sequence" if b.get("style") == "brand" else "turnaround"
            vid = (f"Kling 3.0 storyboard (3 s {first} + 2 s close-up, 720p)" if b.get("angles")
                   else f"Kling 3.0 video ({core.CLIP_SECONDS} s, 720p)")
            room = " + Nano Banana 2.1 room edit" if b.get("set") == "room" else ""
            calls += [f"look {k}: {'Kling Virtual Try-On' if b['engine'] == 'kling' else 'Nano Banana 2.1 edit'}{room} + {vid}" for k in used]
        y, sr = audio_to_numpy(music)
        wav = core.write_wav(tmp / "music.wav", y, sr)
        if b["music"] == "sonilo" and motion:
            calls.append(f"music: Sonilo text to music ({b['music_seconds']} s)")
        out = _out_dir() / f"urban_cuts_{tmp.name}.mp4"
        label = "AI-generated" if (b["ai_label"] and motion) else ("Free draft" if b["ai_label"] else "")
        before = _pil(kw["before"]) if kw.get("before") is not None else None
        logo = _pil(kw["logo"]) if not _is_blank(kw.get("logo")) else None
        r = core.render(looks, json.loads(beats), out, tmp, b, music_path=wav, labels={"label": label}, before=before, logo=logo)
        thumbs = r.pop("_thumbs")
        sheet = core.contact_sheet(stills, thumbs, r["cuts"])
        r.update(mode=b["mode"], vibe=b["vibe"], looks_used=used, partner_calls=calls or ["none (free draft)"],
                 cost_estimate=core.cost_estimate(b, len(used), generated_motion=motion))
        return (VideoFromFile(str(out)), _tensor(sheet), json.dumps(r, indent=1))


NODE_CLASS_MAPPINGS = {"UrbanBrief": UrbanBrief, "UrbanShot": UrbanShot, "UrbanPickLook": UrbanPickLook, "UrbanSet": UrbanSet,
                       "UrbanMusic": UrbanMusic, "UrbanBeatDetect": UrbanBeatDetect, "UrbanBeatCut": UrbanBeatCut}
NODE_DISPLAY_NAME_MAPPINGS = {"UrbanBrief": "Urban Cuts: Your Choices + Consent", "UrbanShot": "Urban Cuts: Look Prompts",
                              "UrbanPickLook": "Urban Cuts: Pick Try-On / Edit", "UrbanSet": "Urban Cuts: Set (photo / white wall room)",
                              "UrbanMusic": "Urban Cuts: Pick Music",
                              "UrbanBeatDetect": "Urban Cuts: Beat Detect", "UrbanBeatCut": "Urban Cuts: Beat Cut Assemble"}
