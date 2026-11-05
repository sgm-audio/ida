# Workflow 2 — Live coding: showing a pattern's structure

Goal: a panel that shows how a live-coded performance (Strudel, TidalCycles, SuperCollider, Sonic Pi, etc.) changes density, timbre and tempo over time.

## 1. Capture
Record the output of the performance in one take. Options:
- **OBS**: add an *Audio Output Capture* source (desktop audio), record to MKV, then extract audio (step 2 handles MKV directly if ffmpeg is installed).
- **DAW / audio interface loopback**: route the synth output to a recording track.

Keep the take at least 16 s so the tempo curve (8 s windows, 4 s hop) has several points.

## 2. Analyse
```bash
python -m ida_dsp analyze recordings/set-03.mkv -o site/assets/ida/set-03.json --title "Live set, 03"
ffmpeg -i recordings/set-03.mkv -vn -c:a flac site/assets/ida/set-03.flac   # the playable audio (optional, smaller)
```
Use `set-03.flac` as `data-ida-audio` if you want the page to play audio without video decoding.

## 3. What the panel shows
- **Onsets (dots) and onset rate** — event density. Live-coded density changes show up as changes in the dot spacing.
- **`musical.tempo_curve`** — tempo estimated every 4 s. A stable line means a locked clock; drift means a tempo change or a loose clock.
- **Centroid line** — brightness over time. Filter sweeps show as steady climbs.
- **Live analyser** — what the visitor hears, measured in their browser while playing.

## 4. Caveats
- Tempo for sparse or polyrhythmic patterns is unreliable. Read the curve, not only the summary BPM.
- Browser playback applies the output device's processing; the precomputed layer is the reference.
