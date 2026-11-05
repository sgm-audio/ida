# Workflow 3 — Acoustic guitar recorded over a DAW session

Goal: show that a guitar take sits in time with the session, after removing interface latency, and quantify how far off the grid it is.

## 0. Setup once (per rig)
Measure the latency between your guitar mic and the DAW timeline. Simplest method: record a click loopback (speaker → mic) and read the offset. Keep this number; it is the `--expect-lag` hint.

## 1. Capture
- **DAW session**: a click or backing track at a known tempo. Bounce it as `daw_backing.wav`.
- **Guitar take**: record the acoustic guitar against that backing (headphones; keep the backing out of the guitar mic when possible).
- Export the guitar take as `guitar_take.wav` (or extract from OBS as in workflow 4).

## 2. Find the latency (sync)
```bash
python -m ida_dsp sync --ref daw_backing.wav --other guitar_take.wav \
    --expect-lag 0.08 --window 0.1 --manifest sync.json
```
- `lag_s` is how much later the guitar starts than the DAW. Positive = delayed.
- **Use `--expect-lag`.** Rhythmic material repeats: a guitar on eighth notes correlates almost as well 0.25 s early or late. Without a hint the tool returns the strongest peak, and the other candidates are printed so you can see the ambiguity.
- Accuracy: the envelope stage has ~6 ms resolution. Expect a few ms of error.

## 3. Score the timing (groove)
```bash
python -m ida_dsp groove --perf guitar_take.wav --align-to daw_backing.wav \
    --expect-lag 0.08 --grid-bpm 120 --subdivision 2 --max-dev 60
```
Use `--subdivision 2` for eighths, `4` for sixteenths. Without a subdivision matching the playing, most notes fall outside the window and are rejected (the output reports `events_rejected`).

The output gives mean, median, standard deviation, and the share of notes within ±10 ms and ±20 ms, plus a histogram for the chart.

## 4. Calibrate the detector bias (do this once)
On the synthetic demo, the onset detector reads about +8 ms late against known timing (the demo's guitar has a 6 ms injected jitter; the groove spread came out at 6.5 ms). That bias comes from the detector, not the player. To correct it for your recordings, run the groove command on a click track you generated at known times and subtract the measured mean from your results. Report the calibrated value, not the raw one.

## 5. Publish
Embed `guitar_take.json` with `data-ida-audio` pointing at `guitar_take.wav`, and state the latency and groove numbers next to the panel with the grid settings used.

## Limits
- Latency of a few ms is within the method's error. Don't claim sub-5 ms tightness.
- Mic bleed of the backing track into the guitar mic makes raw-waveform alignment stronger, which only helps the refinement stage.
