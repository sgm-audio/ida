"""Alignment and timing tools for multi-source sessions.

Used by two workflows:
  * OBS multicam: every camera's audio track is aligned to a reference camera.
  * Guitar over DAW: the live guitar take is aligned to the DAW bounce (removes
    interface latency) and then scored for timing against the session grid.

Sign convention (used everywhere):
  ``lag_s`` is how much later ``other`` starts than ``ref`` for the same event.
  ``trim_start_s = max(lag, 0)``  -> cut this much from the start of ``other``.
  ``pad_start_s  = max(-lag, 0)`` -> prepend this much silence to ``other``.
"""

from __future__ import annotations

import numpy as np
import librosa
from scipy.signal import correlate

from .audio_io import load_audio

COARSE_HOP = 128          # ~5.8 ms envelope resolution at 22.05 kHz
REFINE_WINDOW_S = 30.0    # raw-audio refinement uses up to this much of ref


def _mono(y: np.ndarray) -> np.ndarray:
    return y.mean(axis=0).astype(np.float64)


def estimate_offset(ref: np.ndarray, other: np.ndarray, sr: int,
                    max_lag_s: float = 30.0,
                    expect_lag_s: float | None = None,
                    window_s: float | None = None) -> dict:
    """Estimate the lag between two mono signals sharing the same sample rate.

    Stage 1 correlates onset-strength envelopes (robust to level differences
    between cameras and mics). Stage 2 refines to single-sample precision on
    the raw waveform around the coarse peak.

    Rhythmic material is periodic: a guitar on an 8th-note grid correlates
    almost as well 0.25 s early or late. ``candidates`` lists the strongest
    distinct peaks so that ambiguity is visible. Pass ``expect_lag_s`` and
    ``window_s`` (e.g. a measured interface latency of 0.08 s +/- 0.1 s) to
    restrict the search to the plausible peak.
    """
    ref = np.asarray(ref, dtype=np.float64)
    other = np.asarray(other, dtype=np.float64)

    env_r = librosa.onset.onset_strength(y=ref, sr=sr, hop_length=COARSE_HOP)
    env_o = librosa.onset.onset_strength(y=other, sr=sr, hop_length=COARSE_HOP)
    env_r = env_r - env_r.mean()
    env_o = env_o - env_o.mean()
    Lr, Lo = env_r.size, env_o.size

    # Normalised cross-correlation over all shifts. Index i maps to shift i-(Lr-1).
    corr = correlate(env_o, env_r, mode="full", method="fft")
    energy_o = correlate(env_o ** 2, np.ones(Lr), mode="full", method="fft")
    energy_r = float(np.sum(env_r ** 2)) + 1e-12
    ncc = corr / np.sqrt(np.maximum(energy_o, 1e-12) * energy_r)

    shifts = np.arange(corr.size) - (Lr - 1)
    max_shift = int(round(max_lag_s * sr / COARSE_HOP))
    overlap = np.minimum(Lr, Lo - shifts) - np.maximum(0, -shifts)
    valid = (np.abs(shifts) <= max_shift) & (overlap >= 0.5 * min(Lr, Lo))
    if expect_lag_s is not None:
        tol = window_s if window_s is not None else 0.1
        lag_of_shift = shifts * COARSE_HOP / sr
        valid &= np.abs(lag_of_shift - expect_lag_s) <= tol
    if not np.any(valid):
        raise ValueError("No overlapping audio within the lag search range; check the inputs.")
    ncc_masked = np.where(valid, ncc, -np.inf)
    best = int(np.argmax(ncc_masked))
    coarse_lag = int(shifts[best]) * COARSE_HOP          # in samples
    confidence = float(ncc[best])

    candidates = _distinct_peaks(ncc_masked, shifts, sr)

    # Stage 2: sample-accurate refinement on raw audio.
    M = int(min(ref.size, REFINE_WINDOW_S * sr))
    pad = 2 * COARSE_HOP
    start = coarse_lag - pad
    end = coarse_lag + pad + M
    seg = np.zeros(end - start)
    src_lo, src_hi = max(0, start), min(other.size, end)
    if src_hi > src_lo:
        seg[src_lo - start:src_hi - start] = other[src_lo:src_hi]
    ref_win = ref[:M]
    fine = correlate(seg, ref_win, mode="valid", method="fft")
    fine_lag = start + int(np.argmax(fine))

    return {
        "lag_s": round(fine_lag / sr, 6),
        "lag_samples": int(fine_lag),
        "trim_start_s": round(max(fine_lag, 0) / sr, 6),
        "pad_start_s": round(max(-fine_lag, 0) / sr, 6),
        "confidence": round(confidence, 4),
        "candidates": candidates,
        "sample_rate": int(sr),
    }


def _distinct_peaks(score: np.ndarray, shifts: np.ndarray, sr: int,
                    k: int = 5, min_sep_s: float = 0.05) -> list[dict]:
    """Top-``k`` correlation peaks at least ``min_sep_s`` apart, best first."""
    order = np.argsort(score)[::-1][:2000]
    picked: list[dict] = []
    for idx in order:
        if not np.isfinite(score[idx]):
            break
        lag = shifts[idx] * COARSE_HOP / sr
        if all(abs(lag - p["lag_s"]) >= min_sep_s for p in picked):
            picked.append({"lag_s": round(float(lag), 4), "score": round(float(score[idx]), 4)})
            if len(picked) == k:
                break
    return picked


def align_files(ref_path: str, other_paths: list[str], sr: int = 22050,
                max_lag_s: float = 30.0, expect_lag_s: float | None = None,
                window_s: float | None = None) -> dict:
    """Align several files to one reference. Returns a manifest-ready dict."""
    y_ref, _ = load_audio(ref_path, sr=sr)
    ref = _mono(y_ref)
    results = []
    for path in other_paths:
        y_o, _ = load_audio(path, sr=sr)
        res = estimate_offset(ref, _mono(y_o), sr, max_lag_s=max_lag_s,
                              expect_lag_s=expect_lag_s, window_s=window_s)
        results.append({"file": path, **res})
    return {"reference": ref_path, "sample_rate": sr, "tracks": results}


def ffmpeg_hint(track: dict) -> str:
    """Suggest an ffmpeg command that applies the alignment to a video/audio file."""
    if track["lag_s"] >= 0:
        return (f'ffmpeg -ss {track["trim_start_s"]:.3f} -i "{track["file"]}" '
                f'-c copy "aligned_{_stem(track["file"])}.mkv"')
    return (f'ffmpeg -itsoffset {track["pad_start_s"]:.3f} -i "{track["file"]}" '
            f'-c copy "aligned_{_stem(track["file"])}.mkv"')


def _stem(path: str) -> str:
    from pathlib import Path
    return Path(path).stem


def grid_from_bpm(bpm: float, duration_s: float, offset_s: float = 0.0,
                  subdivision: int = 1) -> np.ndarray:
    """Build a metronome grid (seconds) from a known tempo."""
    step = 60.0 / bpm / subdivision
    return np.arange(offset_s, duration_s, step)


def groove_report(grid_s, events_s, max_dev_ms: float = 120.0) -> dict:
    """Score event timing against a grid. Deviations are signed (+ = late)."""
    grid = np.sort(np.asarray(grid_s, dtype=float))
    events = np.sort(np.asarray(events_s, dtype=float))
    if grid.size == 0 or events.size == 0:
        raise ValueError("Need at least one grid point and one event.")

    idx = np.searchsorted(grid, events)
    left = np.clip(idx - 1, 0, grid.size - 1)
    right = np.clip(idx, 0, grid.size - 1)
    nearest = np.where(np.abs(events - grid[left]) <= np.abs(events - grid[right]),
                       grid[left], grid[right])
    dev_ms = (events - nearest) * 1000.0
    keep = np.abs(dev_ms) <= max_dev_ms
    dev = dev_ms[keep]
    if dev.size == 0:
        raise ValueError("No events fall within max_dev_ms of the grid.")

    edges = np.arange(-max_dev_ms, max_dev_ms + 10, 10)
    hist, _ = np.histogram(dev, bins=edges)
    return {
        "events_scored": int(dev.size),
        "events_rejected": int(events.size - dev.size),
        "mean_ms": round(float(dev.mean()), 2),
        "median_ms": round(float(np.median(dev)), 2),
        "std_ms": round(float(dev.std()), 2),
        "mean_abs_ms": round(float(np.mean(np.abs(dev))), 2),
        "within_10ms_pct": round(float(np.mean(np.abs(dev) <= 10 + 1e-6) * 100), 1),
        "within_20ms_pct": round(float(np.mean(np.abs(dev) <= 20 + 1e-6) * 100), 1),
        "histogram": {"bin_edges_ms": edges.tolist(), "counts": hist.tolist()},
    }
