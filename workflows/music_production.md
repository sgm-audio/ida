# Workflow 1 — Music production: analysis panels from a finished mix

Goal: turn a mixdown (or a stem) into a landing-page panel whose numbers are measured, not written by hand.

## 1. Export
From your DAW, bounce the **mix** as WAV (24-bit or 16-bit, 44.1/48 kHz). Use the same file you publish, so the panel describes what listeners hear.

## 2. Analyse
```bash
python -m ida_dsp analyze exports/mix.wav -o site/assets/ida/mix.json --title "Track name — final mix"
cp exports/mix.wav site/assets/ida/mix.wav        # the audio the widget plays
```
The command prints peak, RMS, crest factor, tempo, key and onset count. The JSON (~80 KB) holds the waveform envelope, RMS curve, centroid, mel spectrogram, beats, onsets and a tempo curve.

## 3. Check the numbers before publishing
| Metric | What to look for |
|---|---|
| `clipped_samples` | Should be 0 for a master. Non-zero means you publish clipping. |
| `peak_dbfs` | Usually between −1 and −0.1 for a finished master. |
| `tempo_bpm` | Compare with your session tempo. Tracker estimates can be off on sparse or tempo-changing material; check `tempo_curve`. |
| `key` | A Krumhansl estimate. Treat it as a hint for tonal material; it is weak on drones or atonal music. |
| `stereo_correlation` | Near +1 means near-mono. Values below 0 indicate phase problems. |

## 4. Embed
```html
<script src="/assets/ida/ida-embed.js" defer></script>
<div data-ida-src="/assets/ida/mix.json" data-ida-audio="/assets/ida/mix.wav"></div>
```
Copy `web/embed/ida-embed.js` next to the JSON, or serve it from your CDN.

## Limits (say these on the page)
- Integrated loudness (LUFS) and true peak are **not** computed; the "dynamic range" chip is an approximation (P95 − P10 of frame RMS). If you publish loudness claims, measure them with a dedicated meter and cite it.
- Spectrum is a mel spectrogram at 96 bands, not a linear FFT.
