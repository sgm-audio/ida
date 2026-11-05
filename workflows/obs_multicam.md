# Workflow 4 — OBS recording with multiple cameras

Goal: align every camera to one reference so the edit is in sync, and report the offsets.

## 1. Capture
- Record every camera in OBS to MKV (safe against crashes). Start all recordings from one scene so their audio shares a start.
- Use **one** audio source as the reference (the camera with the best audio, or a dedicated room mic recorded into each file). Clap once at the start for a visual and audible marker; it helps you verify the result.
- Check that the sample rate matches across files (OBS: Settings → Audio → 48 kHz).

## 2. Requirements
- Python 3.10+ with `pip install -r requirements.txt`
- **ffmpeg** on `PATH` (needed to read MKV/MP4 audio; the tool errors clearly if it is missing).

## 3. Align
```bash
python -m ida_dsp sync \
    --ref  recordings/cam1.mkv \
    --other recordings/cam2.mkv recordings/cam3.mkv \
    --max-lag 15 --manifest multicam_sync.json
```
Output per file: `lag_s`, a confidence score, alternate candidates, and an ffmpeg hint.
- `lag_s > 0`: the file started **later**; trim `trim_start_s` from its start (the hint does this).
- `lag_s < 0`: the file started **earlier**; `pad_start_s` of silence is needed (the hint uses `-itsoffset`).

## 4. Check before editing
- `confidence` should be clearly above the alternates. A low value or two near-equal candidates means the recordings share no distinct transient; add a clap or use a common audio source.
- Listen at the aligned point with the clap; it should line up within a frame (≈16–40 ms at 25–60 fps). Audio-based alignment gives ~6 ms resolution, so video frame accuracy is the limit when you edit.

## 5. Run the ffmpeg hints
The hints use `-c copy`. Stream copy trims only at keyframes, so the cut may be a few frames off. For frame-exact edits, re-encode:
```bash
ffmpeg -ss 1.834 -i recordings/cam2.mkv -c:v libx264 -crf 18 -c:a aac aligned_cam2.mp4
```

## 6. Optional: analyse the program mix for the page
```bash
python -m ida_dsp analyze recordings/program_mix.wav -o site/assets/ida/program.json
```
