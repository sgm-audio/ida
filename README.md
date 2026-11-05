# IDA — Interactive Demo Assets

Librosa-based audio analysis that turns real recordings into embeddable landing-page panels. Each panel shows an offline analysis (waveform, RMS, spectral centroid, mel spectrogram, beats, onsets, tempo curve, key, metrics) plus a live Web Audio analyser that measures what the visitor hears while it plays.

Four end-to-end workflows are documented in `workflows/`:

| Workflow | Input | Key commands |
|---|---|---|
| [Music production](workflows/music_production.md) | Bounced mix / stem | `analyze` |
| [Live coding](workflows/live_coding.md) | Performance recording (OBS, loopback) | `analyze` |
| [Acoustic guitar over a DAW session](workflows/guitar_over_daw.md) | DAW bounce + guitar take | `sync`, `groove` |
| [OBS multicamera](workflows/obs_multicam.md) | MKV/MP4 per camera | `sync` |

## Quick start

```bash
make install            # venv + librosa, soundfile, scipy, numpy
make test               # 10 tests: sync accuracy, groove scoring, schema, metrics
make demo               # synthetic clips -> web/demo/audio, JSON -> web/demo/data
make serve              # http://localhost:8000/demo/index.html
```

Synthetic demo clips stand in for real sessions. Replace them with your own WAV exports; the code path is the same.

## CLI

```bash
python -m ida_dsp analyze <file> -o out.json [--title "..."]
python -m ida_dsp sync --ref <ref> --other <a> [<b> ...] [--expect-lag S --window S] [--manifest m.json]
python -m ida_dsp groove --perf <take> (--align-to <ref> | --lag S) (--grid-bpm N [--subdivision 2] | --grid-from <file>)
python -m ida_dsp demo --out web/demo
```

Video containers (MKV, MP4, MOV, …) need `ffmpeg` on `PATH`; WAV/FLAC/OGG/MP3 do not.

## Layout

```
ida_dsp/          Python package
  analyze.py      offline analysis -> ida.analysis.v1 JSON
  sync.py         lag estimation (multi-camera, latency) and groove scoring
  audio_io.py     loading, video demux via ffmpeg
  demo.py         synthetic demo assets
  __main__.py     CLI
web/embed/ida-embed.js   zero-dependency widget (precomputed + live layers)
web/demo/index.html      example landing page
web/demo/data/*.json     demo analysis payloads (committed, small)
workflows/*.md           the four workflows
tests/                   pytest suite
```

## Embedding

```html
<script src="ida-embed.js" defer></script>
<div data-ida-src="mix.json" data-ida-audio="mix.wav"></div>
```

`window.IDA.mount(element)` mounts a panel added to the DOM later. Cross-origin audio needs `Access-Control-Allow-Origin` for the live layer; without it the precomputed layer still renders.

## What is measured, and what is not

Measured with librosa / NumPy from the source file:
- peak and RMS (dBFS), crest factor, clipped samples, silence ratio, DC offset, stereo correlation
- an approximate dynamic range (P95 − P10 of frame RMS above −60 dB)
- tempo (beat tracker on 5.8 ms frames), beats, onsets, tempo curve (8 s windows)
- key (Krumhansl-Schmuckler on chroma)
- mel spectrogram (96 bands), spectral centroid, waveform envelope

Not measured: integrated loudness (LUFS), true peak, PLR. Don't present the dynamic-range chip as a loudness standard.

Accuracy notes, verified on the synthetic demo (which has known timing):
- Tempo at hop 512 snapped 120 BPM to 117.45. Beat analysis now runs at hop 128, which gives 120.19.
- Latency sync recovers 0.080 s against a 0.084 s ground truth (≈6 ms envelope resolution).
- Periodic rhythm is ambiguous: the best correlation peak can be 0.25 s off. Use `--expect-lag` (a measured latency) to resolve it; the candidate list shows the alternatives.
- Onset-based timing has a ≈+8 ms late bias on this detector; calibrate per rig (see the guitar workflow).

## Browser check

The demo was loaded in headless Chromium: all three panels rendered with no console errors, and the live analyser measured peak, RMS and centroid during playback.
