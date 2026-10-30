# Model scan for the Urban Cuts demo run (2026-10-29)

This is the JK rule: scan the options before any AI generation. The entry must be a ComfyUI app, so the candidates are
ComfyUI partner nodes and local models. Prices come from the nodes' price badges in ComfyUI 0.42, read today. A
"not quoted" price was not checked live and was not used.

## Results by task

| Task | Candidate | Price | Notes | Pick |
|---|---|---|---|---|
| Fictional model + outfit stills | Nano Banana 2.1, 1K, minimal thinking (partner) | $0.048 per image | Text to image, no reference photo, so it can't copy a real person | **yes** |
| | Nano Banana 2 Lite | ~$0.041 per image | Cheaper, but no quality evidence for full-body fashion | no |
| | Local Z-Image (`jk-local-image`) | $0 | GPU is reserved for Tiny World until 10-30 | no |
| Try-on (person wears outfit) | Kling Virtual Try-On (partner) | $0.160 per image | A dedicated try-on model that keeps pose and identity | **yes** |
| | Nano Banana 2.1 image edit | $0.048 per image | Cheaper. Restages the scene and may redraw the face | in the app as the alternative |
| | fal FASHN / IDM-VTON | not quoted | Not a ComfyUI partner node, so out of scope for the entry | no |
| | Local CatVTON | $0 | GPU busy | no |
| Motion per look | Kling 3.0 (`kling-v3`) 720p, no audio, 3 s | $0.084/s = $0.252 per clip | The cheapest Kling 3.0 tier, and 3 s is the minimum length | **yes** |
| | Kling 3.0 turbo 720p | $0.112/s | Costs more | no |
| | Kling 3.0 Omni std | $0.084/s | Same price, made for multi-reference work | no |
| | Local LTX-2.5 | $0 | GPU busy | no |
| Music | Sonilo text to music | $0.0025/s = $0.03 for 12 s | Original, made on demand, no licence question | **yes** |
| | ACE-Step local | $0 | GPU busy | no |

## Planned spend

- Input stills: 5 × $0.048 = $0.24.
- Full app run: $1.68.
- Total: about $1.92, against the founder-approved $3 cap. `tools/run_paid.py` enforces the cap with a ledger.
