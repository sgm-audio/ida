"""Synthetic stand-in recordings so the whole pipeline runs without real sessions.

Replace these with your own bounces, takes and OBS exports; the analysis code is
identical. Everything here is deterministic (fixed seed) so the demo numbers in
the docs stay reproducible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 22050
RNG = np.random.default_rng(7)


def _env(n: int, attack_s: float, decay_s: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(t / attack_s, 1.0) * np.exp(-t / decay_s)


def pluck(freq: float, dur: float, amp: float = 0.25) -> np.ndarray:
    """Guitar-like pluck: decaying harmonics plus a short noisy attack."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, a in enumerate([1.0, 0.5, 0.3, 0.18, 0.1, 0.05], start=1):
        if freq * k < SR / 2:
            out += a / k * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * (1.5 + 0.8 * k))
    attack = RNG.uniform(-1, 1, n) * np.exp(-t / 0.004) * 0.15
    return amp * (out + attack) * _env(n, 0.002, dur / 2)


def bass_note(freq: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)
    return 0.35 * tone * _env(n, 0.01, dur / 1.5)


def kick(dur: float = 0.25) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t / 0.02)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return 0.9 * np.sin(phase) * np.exp(-t / 0.08)


def hat(dur: float = 0.05) -> np.ndarray:
    n = int(dur * SR)
    noise = RNG.uniform(-1, 1, n)
    hp = np.diff(noise, prepend=0.0)
    return 0.12 * hp * _env(n, 0.001, 0.015)


def place(buf: np.ndarray, sound: np.ndarray, at_s: float) -> None:
    i = int(at_s * SR)
    j = min(buf.size, i + sound.size)
    if i < buf.size:
        buf[i:j] += sound[:j - i]


def _bar_length(bpm: float) -> float:
    return 4 * 60.0 / bpm


CHORDS = [  # A minor -> F -> C -> G, arpeggiated on 8ths
    [220.0, 261.63, 329.63], [174.61, 220.0, 261.63],
    [261.63, 329.63, 392.0], [196.0, 246.94, 293.66],
]


def daw_backing(bpm: float = 120.0, bars: int = 4) -> np.ndarray:
    """Drum-and-bass backing track (kick on quarters, hats on 8ths) - the DAW bounce."""
    beat = 60.0 / bpm
    total = bars * _bar_length(bpm) + 1.0
    buf = np.zeros(int(total * SR))
    for b in range(bars * 4):
        place(buf, kick(), b * beat)
    for e in range(bars * 8):
        place(buf, hat(), e * beat / 2)
    for b in range(bars):  # one bass note per bar: the chord root, an octave down
        root = CHORDS[b % len(CHORDS)][0] / 2
        place(buf, bass_note(root, 4 * beat), b * _bar_length(bpm))
    return buf * 0.7


def guitar_take(bpm: float = 120.0, bars: int = 4, latency_s: float = 0.084,
                jitter_s: float = 0.006) -> np.ndarray:
    """Acoustic-guitar arpeggios played along to the backing, with latency and human timing."""
    beat = 60.0 / bpm
    total = bars * _bar_length(bpm) + 1.5
    buf = np.zeros(int(total * SR))
    step = beat / 2
    for bar in range(bars):  # one chord per bar: eight 8th-note plucks
        chord = CHORDS[bar % len(CHORDS)]
        for pos in range(8):
            note = chord[pos % len(chord)]
            t = bar * _bar_length(bpm) + pos * step
            t += RNG.normal(0, jitter_s)
            place(buf, pluck(note, 0.6), t + latency_s)
    buf += RNG.normal(0, 0.002, buf.size)  # room noise
    return buf


def live_pattern(bpm: float = 128.0, seconds: float = 16.0) -> np.ndarray:
    """Live-coding style pattern: evolving density of blips and filtered noise sweeps."""
    beat = 60.0 / bpm
    buf = np.zeros(int(seconds * SR))
    t = 0.0
    freqs = [440.0, 554.37, 659.25, 880.0]
    i = 0
    while t < seconds:
        density = 0.5 + 0.5 * np.sin(2 * np.pi * t / 8.0)
        if density > 0.5 or i % 2 == 0:
            f = freqs[int(RNG.integers(len(freqs)))]
            n = int(0.12 * SR)
            tt = np.arange(n) / SR
            blip = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.05) * 0.3
            place(buf, blip, t)
        if i % 8 == 0:
            n = int(0.3 * SR)
            noise = RNG.uniform(-1, 1, n)
            sweep = np.convolve(noise, np.ones(16) / 16, mode="same")
            place(buf, sweep * _env(n, 0.05, 0.2) * 0.25, t)
        t += beat / (2 if density > 0.6 else 4)
        i += 1
    return buf


def write_demo_assets(out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    backing = daw_backing()
    take = guitar_take()
    files = {
        "daw_backing": out / "daw_backing.wav",
        "guitar_take": out / "guitar_take.wav",
        "live_pattern": out / "live_pattern.wav",
        "mix": out / "mix.wav",
    }
    n_take = take.size
    padded_backing = np.zeros(n_take)
    padded_backing[:min(n_take, backing.size)] = backing[:min(n_take, backing.size)]
    mix = padded_backing * 0.8 + take * 0.9
    mix = mix / max(1e-9, np.max(np.abs(mix))) * 0.891  # about -1 dBFS peak

    sf.write(files["daw_backing"], backing / max(1e-9, np.max(np.abs(backing))) * 0.8, SR, subtype="PCM_16")
    sf.write(files["guitar_take"], take / max(1e-9, np.max(np.abs(take))) * 0.8, SR, subtype="PCM_16")
    sf.write(files["mix"], mix, SR, subtype="PCM_16")
    lp = live_pattern()
    sf.write(files["live_pattern"], lp / max(1e-9, np.max(np.abs(lp))) * 0.8, SR, subtype="PCM_16")
    return files
