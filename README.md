# Urban Cuts for ComfyUI

An open clone of Higgsfield's **Urban Cuts** app, built as a ComfyUI App Mode workflow. Give it one photo of a person,
3 to 5 outfits (or products) and a piece of music. It dresses the person in each look, animates each look, and cuts a
10 s 9:16 reel on the beat that loops.

![App Mode](docs/img/app-mode.png)

Entry for Comfy's [Open Source Higgsfield](https://comfy.org/open-source-higgsfield) challenge (category: Most Viral).
Apache-2.0.

## What you get

- `Your reel`: an H.264 + AAC MP4 at 9:16 (or 4:5 / 1:1). It opens on the plain "before" photo for 2 beats (the
  before→after hook), then each look lands on every 2nd beat, starting on a downbeat. It ends on a lineup of every
  look, one tile popping in per beat.
  Each cut hits with a punch-zoom, flash or whip pan, and each shot speeds up into the next cut. The last frame blends
  into the first, so the reel loops back to "before". Sound is -14 LUFS with true peak under -1 dBTP, and an `AI-generated` label is on by default.
- `Contact sheet`: the looks, plus one frame per cut with its time and effect.
- `Receipt`: JSON with BPM, beat times, the cut list, the partner calls made and their cost.
- `Beats`: BPM and beat times, as text.

Two modes:
- **Outfits**: the person wears each outfit.
- **Products**: the person presents each product, a "new arrivals" reel for a shop. There's an optional headline on the first look.

Three vibes (`street`, `runway`, `boutique`) set the moves and the cut effects. The hook and the lineup are switches in the form, and both are on by default.

**For a shop:**
- **Look tags:** type one line per look (`Rust bomber | $89`) and each look gets a numbered name-and-price tag, placed
  clear of the Reels/TikTok caption and buttons.
- **Branded lineup:** the lineup shows the tile numbers, your shop name and optional logo, and your call to action and
  handle. With tags and no call to action, it reads "Comment a number to shop".
- **Glow-up hit:** the before photo stutters into look 1 with a flash and a colour split.
- **Beat pulse:** a small zoom breath on every beat inside a shot.
- Every one of these has a switch or a field in the form.

**Consistency:**
- **Background lock:** with Kling try-on the motion prompt locks the background, so the person stays in their own photo's setting.
- **Colour match:** every look is matched to look 1, so cuts don't flicker.
- **Drift guard:** a clip is cut off where its background drifts away from frame 0.
- All three are noted in the receipt.

## How it works

| Step | Node | Runs on |
|---|---|---|
| Choices + consent gate | `Urban Cuts: Your Choices + Consent` | CPU, free |
| Try-on per look | `Kling Virtual Try-On` (or `Nano Banana 2.1` edit; products always use Nano Banana 2.1) | Comfy partner API |
| Motion per look | `Kling 3.0 Video`, image to video, 3 s, 720p, no audio | Comfy partner API |
| Music | your uploaded track, or `Sonilo Text to Music` | upload: free / Sonilo: partner API |
| Beat Detect | `Urban Cuts: Beat Detect` (librosa if installed, else a numpy onset envelope + dynamic-programming beat tracker) | CPU, free |
| Beat Cut Assemble | `Urban Cuts: Beat Cut Assemble` (numpy frame effects + ffmpeg) | CPU, free |

The pack avoids paying for steps it doesn't use:
- Unused branches are **lazy inputs**. When you pick Kling try-on, the Nano Banana node never runs.
- With your own track, Sonilo never runs.
- A slot left on `urban_blank.png` skips that look's try-on and video.
- The consent switch sits in front of every node, so a run with it off stops before anything is generated.
- Seeds are fixed. A re-run after one failed shot reuses the finished (already paid) steps from ComfyUI's cache.

**Free Draft** (`workflows/urban-cuts-draft.json`) uses the same edit with no partner nodes. You give it a photo per
look; it adds a Ken Burns push and the same beat cuts. Use it to try music, vibe and length for $0.

Reused from Comfy's own templates rather than rebuilt:
- the Sonilo wiring follows `api_sonilo_v2m`
- the try-on edit prompt wording follows `template_eric_seedance_5_subject_and_outfit_combine` (Image 1 = identity, Image 2 = the outfit, exactly)

## Cost

Prices come from the nodes' own price badges (ComfyUI 0.42 `comfy_api_nodes`, read 2026-10-29). The `Receipt` output
gives the same estimate for each run.

| Partner call | Unit price | Default run (4 looks, 10 s) |
|---|---|---|
| Kling Virtual Try-On | $0.16016 per image | 4 × = $0.641 |
| Nano Banana 2.1 edit, 1K, minimal thinking (fallback / products) | $0.048048 per image | (instead of try-on: 4 × = $0.192) |
| Kling 3.0 video, `kling-v3`, 720p, no audio | $0.084 per second | 4 × 3 s = $1.008 |
| Sonilo Text to Music | $0.0025 per second | 15 s = $0.038 |
| **Total** | | **$1.69** with Kling try-on, **$1.23** with Nano Banana |
| Free Draft | | **$0** |

## Install

You need:
- ComfyUI 0.42+ with frontend 1.41+ (App Mode)
- `ffmpeg` on PATH
- `numpy` and Pillow (already in ComfyUI)
- optional: `librosa`

There are no model downloads and no GPU. Generation runs on Comfy's partner API (main app) or not at all (draft app).

```bash
cd ComfyUI/custom_nodes
git clone <this repo> urban-cuts
python urban-cuts/tools/make_samples.py --input-dir ../input    # sample inputs for the draft app (optional)
```

Restart ComfyUI and open `workflows/urban-cuts.json` (or `urban-cuts-draft.json`). It opens in App Mode. Then:
1. Tick **I have this person's consent**.
2. Pick your photos and music.
3. Press **Run**.

Partner nodes need a Comfy account with credits.

## Rules the app keeps

- **Consent:** the run stops unless you confirm that you have the person's consent to use their photo (or it's you).
- **Music:** use a track you own or have licensed, or generate one with Sonilo. Never a trending or copyrighted song.
- **Labelling:** keep the AI label on when you post. The draft labels itself `Free draft`.
- **Prompts:** the generation prompts ask for no logos, brand names or text, and no other people.

## Demo output (paid partner run, 2026-10-29)

- `docs/examples/demo-reel-street.mp4`: a fictional model made with Nano Banana 2.1 (not a real person), 4 plain
  outfits with no logos, Kling try-on, Kling 3.0 motion, and a Sonilo track. 10.00 s, -14.2 LUFS, -2.1 dBTP, 119.8 BPM.
  - Timeline: before 0–1.00 s; looks cut at 1.00 / 2.00 / 3.00 / 4.00 / 5.00 / 6.00 / 7.00 s; the lineup starts at 8.00 s with tiles at 8.00 / 8.50 / 9.00 / 9.50 s.
- `docs/examples/demo-contact-sheet-street.png` and `docs/examples/demo-receipt.json`.
- Demo video (90 s): `docs/demo/urban-cuts-demo.mp4`, built by `tools/record_demo.mjs` (real screenshots of the app) and `tools/make_demo_video.py`.
- Spend: $0.24 for the input stills, $1.68 for the app run, and $0.25 to regenerate look 3 with the background-locked
  prompt (the first version walked onto a street). That's $2.17 in all, estimated from the price badges.
- After the run, a fix made each cut snap to the tempo grid (the tracker had slipped near the end of the track). The reel
  was then re-cut from the same saved clips at no extra cost.

## Examples (free draft, code-drawn sample inputs, original code-made beat)

- `docs/examples/draft-reel-street.mp4`: outfits, street vibe, headline "New arrivals". Made by pressing Run in App
  Mode (`tools/e2e_draft.mjs`).
- `docs/examples/draft-reel-products-boutique.mp4`: products, boutique vibe, 4:5.
- `docs/examples/draft-contact-sheet-street.png`

The sample person is a faceless code-drawn figure, not a real person. The demo plan is in `docs/DEMO-PLAN.md`.

## Development

```bash
python tools/build_app.py && python tools/build_app.py --draft        # API-format graphs
python tools/check_graph.py workflows/urban-cuts-api.json --url http://127.0.0.1:8197   # checks, never queues
node tools/make_app.mjs http://127.0.0.1:8197 workflows/urban-cuts-api.json workflows/urban-cuts.json docs/img/app-mode.png
python tools/run_draft.py --url http://127.0.0.1:8197 --consent        # queue the FREE draft (refuses paid nodes)
node tools/e2e_draft.mjs http://127.0.0.1:8197 workflows/urban-cuts-draft.json shot.png   # press Run in the real UI
PYTHONPATH=<pytest dir> <ComfyUI venv>/bin/python -m pytest              # tests; partner nodes are mocked
```

- `make_app.mjs` and `e2e_draft.mjs` need the `playwright` npm package.
- Both block any `/prompt` that contains a partner node.

The tests check these things:
- **Beats:** on 120 / 97 / 128 / 140 BPM click tracks, beats are within ±20 ms and downbeats follow the bar accent.
- **The edit:** every cut lands on a beat; the length is within ±0.1 s; the first frame equals the last; loudness is -14 ±1 LUFS with true peak ≤ -1 dBTP.
- **Modes and gates:** Product mode works, and an unticked consent box stops the run (in code and on the live server).
- **Lazy branches:** unused or blank slots never ask for their paid nodes.
- **Pipeline:** the mocked partner pipeline runs end to end.
- **Graph:** both graphs pass against the live `/object_info`.

## Licences and credits

| Part | Licence |
|---|---|
| Code, workflows, sample images, sample beat | Apache-2.0 (this repo) |
| Font: Inter | SIL OFL 1.1 (`fonts/OFL.txt`) |
| ffmpeg (called, not bundled) | LGPL/GPL, per your build |

"Urban Cuts" names the Higgsfield app this reproduces. This project is not affiliated with Higgsfield, and no Higgsfield
code or assets are used: the behaviour is rebuilt from scratch on ComfyUI nodes.
