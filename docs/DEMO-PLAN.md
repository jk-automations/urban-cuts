# Urban Cuts demo plan (2 min max)

The demo shows the real app in App Mode: inputs → Run → a beat-cut reel. It's recorded as a screen capture of the
ComfyUI tab, with the final reel shown full screen.

## Content rules

- **The person:** a fictional model made with Nano Banana 2.1 (text to image, no reference photo). No real person, no lookalike, no celebrity prompt.
- **Outfits:** 4 plain pieces with no logos or text, e.g. rust jacket, cream knit, blue suit, yellow top with black skirt.
- **Music:** Sonilo text to music with the street vibe's default prompt ("upbeat hip hop instrumental … no vocals"). Never a trending or copyrighted track.
- **Label:** the AI label stays on.

## Spend (founder approval needed before any of it)

| Item | Cost |
|---|---|
| Fictional model still, Nano Banana 2.1 1K | about $0.05 |
| 4 outfit flat-lays, Nano Banana 2.1 1K | about $0.19 |
| Full Urban Cuts run (4 × Kling try-on, 4 × Kling 3.0 3 s, Sonilo 12 s) | $1.68 |
| One retry margin | up to about $0.90 |
| **Cap asked for** | **$3.00** |

## Shot list

| Time | What's on screen | Voice-over / caption |
|---|---|---|
| 0:00–0:08 | The finished reel, full screen, with sound | "One photo, four outfits, one track." |
| 0:08–0:25 | App Mode form: person photo, consent switch, 4 outfits, vibe, music | "Urban Cuts, open source, in ComfyUI App Mode." |
| 0:25–0:35 | Tick consent, press Run, then the queue | "Consent first: it won't run without it." |
| 0:35–0:55 | Graph view, quick pan: try-on → Kling 3.0 → Sonilo → Beat Detect → Beat Cut | "Kling try-on and motion, Sonilo music, and our own beat detector and editor." |
| 0:55–1:10 | Contact sheet output: the looks, each cut with its time | "Every cut lands on the beat. Here's the cut list." |
| 1:10–1:20 | Receipt JSON: BPM, beat times, cost $1.68 | "It tells you what it called and what it cost." |
| 1:20–1:35 | Product mode quick switch + Free Draft ($0) run | "Products mode makes a new-arrivals reel; the free draft costs nothing." |
| 1:35–1:50 | The reel again, looping twice | "It loops." |
| 1:50–2:00 | Repo name + Apache-2.0 | "Free on GitHub." |

## Recording steps

1. Make the fictional model and the outfit flat-lays (paid, after approval). Put them in `input/`.
2. Open `workflows/urban-cuts.json`, choose the files, tick consent and press Run. Keep the receipt.
3. Record the screen at 1440×900 and add the final reel full screen.
4. Run the Free Draft on the same looks for the $0 segment.
