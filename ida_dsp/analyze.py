"""Offline DSP analysis that produces a compact JSON document for the embed widget.

The JSON (schema ``ida.analysis.v1``) is intentionally small (typically < 200 KB):
  * waveform min/max envelope (800 bins)
  * RMS (dBFS), spectral centroid and onset-strength series (600 points)
  * mel spectrogram (96 bands x <=600 frames), uint8 + base64
  * beats, onsets, tempo curve, key estimate and measured metrics

Every number shown on a landing page should come from this file, so the claim
"measured with librosa" is always checkable against the source audio.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path

import librosa
import numpy as np

from .audio_io import load_audio

SCHEMA = "ida.analysis.v1"
DEFAULT_SR = 22050
HOP = 512            # display frames (spectrogram, RMS, centroid)
RHYTHM_HOP = 128     # onset/beat/tempo: 5.8 ms frames; at hop 512 a 120 BPM beat is
                     # 21.5 frames, so tempo snaps to 117.45 BPM (quantisation, not music)
N_FFT = 2048
N_MELS = 96
SPEC_DB = 80.0
SPEC_FRAMES = 600
SERIES_POINTS = 600
WAVE_BINS = 800
TEMPO_WINDOW_S = 8.0
TEMPO_HOP_S = 4.0

# Krumhansl-Kessler key profiles (tonic at index 0).
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _db(x: float) -> float:
    return 20.0 * math.log10(max(float(x), 1e-10))


def _bin_mean(x: np.ndarray, n: int) -> np.ndarray:
    """Average the last axis into at most ``n`` contiguous bins."""
    length = x.shape[-1]
    if length <= n:
        return x
    edges = np.linspace(0, length, n + 1).astype(int)
    return np.stack([x[..., a:b].mean(axis=-1) for a, b in zip(edges[:-1], edges[1:])], axis=-1)


def _min_max_peaks(y: np.ndarray, n: int) -> list[list[float]]:
    edges = np.linspace(0, y.size, n + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = y[a:max(b, a + 1)]
        out.append([round(float(seg.min()), 4), round(float(seg.max()), 4)])
    return out


def estimate_key(chroma_mean: np.ndarray) -> tuple[str, float]:
    """Krumhansl-Schmuckler key estimate from a 12-bin mean chroma vector."""
    if not np.any(chroma_mean > 0):
        return "undetermined", 0.0
    best_r, best_name = -2.0, "undetermined"
    for shift in range(12):
        for profile, mode in ((_MAJOR, "major"), (_MINOR, "minor")):
            r = float(np.corrcoef(np.roll(profile, shift), chroma_mean)[0, 1])
            if np.isfinite(r) and r > best_r:
                best_r, best_name = r, f"{_NOTES[shift]} {mode}"
    return best_name, best_r


def _tempo_curve(oenv: np.ndarray, sr: int) -> dict:
    win = int(TEMPO_WINDOW_S * sr / RHYTHM_HOP)
    step = int(TEMPO_HOP_S * sr / RHYTHM_HOP)
    times, bpms = [], []
    if oenv.size >= win:
        for start in range(0, oenv.size - win + 1, step):
            seg = oenv[start:start + win]
            bpm = librosa.feature.tempo(onset_envelope=seg, sr=sr, hop_length=RHYTHM_HOP)
            times.append(librosa.frames_to_time(start + win // 2, sr=sr, hop_length=RHYTHM_HOP))
            bpms.append(float(np.atleast_1d(bpm)[0]))
    return {"t": [round(float(t), 3) for t in times], "bpm": [round(b, 2) for b in bpms]}


def analyze(path: str | Path, title: str | None = None, sr: int = DEFAULT_SR) -> dict:
    """Run the full analysis on one audio (or video) file and return the JSON-ready dict."""
    path = Path(path)
    y, sr = load_audio(path, sr=sr)
    channels = int(y.shape[0])
    mono = y.mean(axis=0).astype(np.float32)
    n = mono.size
    if n < sr * 0.5:
        raise ValueError(f"{path.name} is shorter than 0.5 s; nothing to analyse.")
    duration = n / sr

    # --- level metrics -------------------------------------------------------
    peak = float(np.max(np.abs(mono)))
    rms_total = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    rms = librosa.feature.rms(y=mono, frame_length=N_FFT, hop_length=HOP)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=1.0, amin=1e-5, top_db=None)
    active = rms_db > -60.0
    level_db = rms_db[active] if np.any(active) else rms_db
    stereo_corr = None
    if channels == 2:
        c = float(np.corrcoef(y[0], y[1])[0, 1])
        stereo_corr = round(c, 4) if np.isfinite(c) else None

    metrics = {
        "duration_s": round(duration, 3),
        "sample_rate": int(sr),
        "channels": channels,
        "peak_dbfs": round(_db(peak), 2),
        "rms_dbfs": round(_db(rms_total), 2),
        "crest_factor_db": round(_db(peak) - _db(rms_total), 2),
        "dynamic_range_db_approx": round(float(np.percentile(level_db, 95) - np.percentile(level_db, 10)), 2),
        "clipped_samples": int(np.sum(np.abs(mono) >= 0.999)),
        "silence_ratio": round(float(np.mean(~active)), 4),
        "dc_offset": round(float(np.mean(mono)), 6),
        "stereo_correlation": stereo_corr,
    }

    # --- rhythm, pitch -------------------------------------------------------
    oenv = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=RHYTHM_HOP)
    tempo, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr,
                                           hop_length=RHYTHM_HOP, units="time")
    onsets = librosa.onset.onset_detect(onset_envelope=oenv, sr=sr,
                                        hop_length=RHYTHM_HOP, units="time")
    chroma = librosa.feature.chroma_stft(y=mono, sr=sr, n_fft=N_FFT, hop_length=HOP)
    key, key_r = estimate_key(chroma.mean(axis=1))
    metrics["onset_rate_per_s"] = round(len(onsets) / duration, 3)

    # --- spectrogram (mel, dB, quantised to uint8) --------------------------
    S = librosa.feature.melspectrogram(y=mono, sr=sr, n_fft=N_FFT, hop_length=HOP,
                                       n_mels=N_MELS, fmax=sr / 2)
    S_db = librosa.power_to_db(S, ref=np.max, top_db=SPEC_DB)
    S_db = _bin_mean(S_db, SPEC_FRAMES)
    q = np.clip(np.round((S_db + SPEC_DB) / SPEC_DB * 255.0), 0, 255).astype(np.uint8)
    mel_freqs = librosa.mel_frequencies(n_mels=N_MELS, fmin=0.0, fmax=sr / 2)

    # --- time-series -------------------------------------------------------
    centroid = librosa.feature.spectral_centroid(y=mono, sr=sr, n_fft=N_FFT, hop_length=HOP)[0]

    # Every time series is interpolated onto one shared uniform grid so the
    # widget can overlay them without per-series time bookkeeping.
    t_grid = np.linspace(0.0, duration, SERIES_POINTS)
    t_disp = librosa.frames_to_time(np.arange(rms.size), sr=sr, hop_length=HOP)
    t_rhythm = librosa.frames_to_time(np.arange(oenv.size), sr=sr, hop_length=RHYTHM_HOP)

    def on_grid(values: np.ndarray, times: np.ndarray, digits: int) -> list[float]:
        return [round(float(v), digits) for v in np.interp(t_grid, times, values)]

    return {
        "schema": SCHEMA,
        "title": title or path.stem,
        "generated_by": {"tool": "ida_dsp", "librosa": librosa.__version__},
        "metrics": metrics,
        "musical": {
            "tempo_bpm": round(float(np.atleast_1d(tempo)[0]), 2),
            "beats_s": [round(float(b), 3) for b in beats],
            "onsets_s": [round(float(o), 3) for o in onsets],
            "key": key,
            "key_correlation": round(key_r, 3),
            "tempo_curve": _tempo_curve(oenv, sr),
        },
        "waveform": {"bins": WAVE_BINS, "min_max": _min_max_peaks(mono, WAVE_BINS)},
        "series": {
            "t": [round(float(t), 3) for t in t_grid],
            "rms_db": on_grid(np.maximum(rms_db, -90.0), t_disp, 2),
            "centroid_hz": on_grid(centroid, t_disp, 1),
            "onset_strength": on_grid(oenv, t_rhythm, 3),
        },
        "spectrogram": {
            "n_mels": N_MELS,
            "frames": int(q.shape[1]),
            "db_range": SPEC_DB,
            "freqs_hz": [round(float(f), 1) for f in mel_freqs],
            "encoding": "uint8 row-major [mel][frame], 0 = -db_range, 255 = 0 dB",
            "data": base64.b64encode(q.tobytes()).decode("ascii"),
        },
    }


def write_analysis(analysis: dict, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(analysis, fh, separators=(",", ":"))
    return out
