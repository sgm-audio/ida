import base64
import json

import numpy as np
import pytest

from ida_dsp.analyze import SCHEMA, analyze, estimate_key, write_analysis
from ida_dsp.demo import write_demo_assets
from ida_dsp.sync import estimate_offset, groove_report, grid_from_bpm

SR = 22050


def _click_track(seconds=8.0, seed=0):
    rng = np.random.default_rng(seed)
    y = np.zeros(int(seconds * SR))
    for t in np.sort(rng.uniform(0.2, seconds - 0.5, 24)):
        i = int(t * SR)
        n = int(0.03 * SR)
        y[i:i + n] += rng.uniform(-1, 1, n) * np.exp(-np.arange(n) / (0.004 * SR))
    return y


@pytest.mark.parametrize("shift_s", [1.2345, -0.5, 0.0])
def test_estimate_offset_recovers_known_shift(shift_s):
    base = _click_track(10.0)
    shift = int(round(shift_s * SR))
    if shift >= 0:
        other = np.concatenate([np.zeros(shift), base])
    else:
        other = base[-shift:]
    res = estimate_offset(base, other, SR)
    # other = base delayed by shift, so lag == shift_s
    assert abs(res["lag_samples"] - shift) <= 1
    assert res["confidence"] > 0.5


def test_trim_and_pad_convention():
    base = _click_track(6.0)
    late = np.concatenate([np.zeros(SR), base])  # starts 1 s later
    res = estimate_offset(base, late, SR)
    assert res["trim_start_s"] == pytest.approx(1.0, abs=1e-3)
    assert res["pad_start_s"] == 0.0
    early = base[SR // 2:]  # starts 0.5 s too late -> needs padding
    res2 = estimate_offset(base, early, SR)
    assert res2["pad_start_s"] == pytest.approx(0.5, abs=1e-3)
    assert res2["trim_start_s"] == 0.0


def test_groove_report_measures_known_deviation():
    grid = grid_from_bpm(120, 10.0)           # 0.5 s spacing
    events = grid + 0.010                     # every hit 10 ms late
    rep = groove_report(grid, events)
    assert rep["mean_ms"] == pytest.approx(10.0, abs=0.01)
    assert rep["std_ms"] == pytest.approx(0.0, abs=0.01)
    assert rep["within_10ms_pct"] == 100.0


def test_groove_rejects_far_events():
    grid = grid_from_bpm(120, 4.0)
    rep = groove_report(grid, np.array([0.25, 0.75 + 0.3]), max_dev_ms=120)
    assert rep["events_scored"] == 1
    assert rep["events_rejected"] == 1


def test_key_estimate_prefers_c_major_for_c_major_profile():
    from ida_dsp.analyze import _MAJOR
    name, r = estimate_key(_MAJOR.copy())
    assert name == "C major"
    assert r > 0.99


def test_analyze_writes_compact_schema(tmp_path):
    files = write_demo_assets(tmp_path / "audio")
    data = analyze(files["mix"], title="mix")
    assert data["schema"] == SCHEMA
    assert data["metrics"]["channels"] == 1
    assert data["metrics"]["peak_dbfs"] == pytest.approx(-1.0, abs=0.3)
    assert len(data["waveform"]["min_max"]) == data["waveform"]["bins"]
    spec = data["spectrogram"]
    raw = base64.b64decode(spec["data"])
    assert len(raw) == spec["n_mels"] * spec["frames"]
    assert 60 < data["musical"]["tempo_bpm"] < 140
    out = write_analysis(data, tmp_path / "mix.json")
    assert out.stat().st_size < 400_000
    json.loads(out.read_text())


def test_stereo_correlation_detects_identical_channels(tmp_path):
    import soundfile as sf
    y = _click_track(3.0)
    sf.write(tmp_path / "st.wav", np.stack([y, y], axis=1), SR)
    data = analyze(tmp_path / "st.wav")
    assert data["metrics"]["channels"] == 2
    assert data["metrics"]["stereo_correlation"] == pytest.approx(1.0, abs=1e-3)


def test_expected_lag_resolves_periodic_ambiguity():
    # A strictly periodic grid: every 0.25 s the signal looks the same.
    seconds = 8.0
    t = np.arange(int(seconds * SR)) / SR
    base = (np.sin(2 * np.pi * 220 * t) * (np.modf(t * 4)[0] < 0.1)).astype(float)
    late = np.concatenate([np.zeros(int(0.084 * SR)), base])[:base.size]
    free = estimate_offset(base, late, SR)
    assert abs(free["lag_s"] - 0.084) > 0.1          # ambiguous without a hint
    assert len(free["candidates"]) >= 2
    hinted = estimate_offset(base, late, SR, expect_lag_s=0.08, window_s=0.05)
    assert hinted["lag_s"] == pytest.approx(0.084, abs=0.002)
