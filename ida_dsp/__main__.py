"""Command-line entry point: ``python -m ida_dsp <command> ...``

Commands
  analyze   Analyse one file and write the embed JSON.
  sync      Align one or more tracks/cameras to a reference (writes a manifest).
  groove    Score performance onsets against a DAW grid or a BPM.
  demo      Generate synthetic demo assets and their analysis JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyze import analyze, write_analysis
from .sync import align_files, ffmpeg_hint, grid_from_bpm, groove_report


def _cmd_analyze(args: argparse.Namespace) -> int:
    data = analyze(args.input, title=args.title, sr=args.sr)
    out = write_analysis(data, args.output)
    m = data["metrics"]
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  duration {m['duration_s']} s | peak {m['peak_dbfs']} dBFS | "
          f"RMS {m['rms_dbfs']} dBFS | clipped {m['clipped_samples']}")
    print(f"  tempo {data['musical']['tempo_bpm']} BPM | key {data['musical']['key']} | "
          f"{len(data['musical']['onsets_s'])} onsets")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    manifest = align_files(args.ref, args.other, sr=args.sr, max_lag_s=args.max_lag,
                           expect_lag_s=args.expect_lag, window_s=args.window)
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"wrote {args.manifest}")
    for t in manifest["tracks"]:
        print(f"{t['file']}: lag {t['lag_s']:+.4f} s "
              f"(confidence {t['confidence']:.2f})")
        others = ", ".join(f"{c['lag_s']:+.3f}s={c['score']:.2f}" for c in t["candidates"][1:])
        if others:
            print(f"  other candidates: {others}")
        print(f"  {ffmpeg_hint(t)}")
    return 0


def _cmd_groove(args: argparse.Namespace) -> int:
    import librosa
    from .audio_io import load_audio

    y, sr = load_audio(args.perf, sr=args.sr)
    mono = y.mean(axis=0)
    duration = mono.size / sr
    lag = args.lag
    if args.align_to:
        from .sync import estimate_offset
        yr, _ = load_audio(args.align_to, sr=sr)
        res = estimate_offset(yr.mean(axis=0), mono, sr,
                              expect_lag_s=args.expect_lag, window_s=args.window)
        lag = res["lag_s"]
        print(f"aligned to {args.align_to}: lag {lag:+.4f} s (confidence {res['confidence']:.2f})")

    if args.grid_bpm:
        grid = grid_from_bpm(args.grid_bpm, duration, offset_s=args.grid_offset,
                             subdivision=args.subdivision)
    else:
        from .audio_io import load_audio as _la
        yr, srr = _la(args.grid_from, sr=sr)
        oenv = librosa.onset.onset_strength(y=yr.mean(axis=0), sr=srr)
        _, beats = librosa.beat.beat_track(onset_envelope=oenv, sr=srr, units="time")
        grid = beats

    # Fine hop (128 samples ~ 5.8 ms) keeps onset-peak bias small. On a synthetic
    # guitar take with known timing, hop 128 gave a 6.5 ms spread (the injected
    # jitter); hop 512 gave 12 ms and backtracking flipped the bias to early.
    onsets = librosa.onset.onset_detect(y=mono, sr=sr, hop_length=128, units="time")
    onsets_in_grid_time = onsets - lag
    report = groove_report(grid, onsets_in_grid_time, max_dev_ms=args.max_dev)
    report["lag_s"] = round(float(lag), 6)
    print(json.dumps(report, indent=2))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from .demo import write_demo_assets

    out = Path(args.out)
    files = write_demo_assets(out / "audio")
    specs = [
        ("mix", "Music production mix", files["mix"]),
        ("guitar_take", "Acoustic guitar over DAW", files["guitar_take"]),
        ("live_pattern", "Live coding pattern", files["live_pattern"]),
    ]
    for name, title, path in specs:
        data = analyze(path, title=title)
        write_analysis(data, out / "data" / f"{name}.json")
        print(f"analysed {name}: {data['musical']['tempo_bpm']} BPM, key {data['musical']['key']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ida_dsp", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="analyse one file -> embed JSON")
    a.add_argument("input")
    a.add_argument("-o", "--output", required=True)
    a.add_argument("--title")
    a.add_argument("--sr", type=int, default=22050)
    a.set_defaults(func=_cmd_analyze)

    s = sub.add_parser("sync", help="align tracks/cameras to a reference")
    s.add_argument("--ref", required=True, help="reference file (e.g. camera 1 or DAW bounce)")
    s.add_argument("--other", nargs="+", required=True, help="files to align to the reference")
    s.add_argument("--manifest", help="write alignment manifest JSON here")
    s.add_argument("--max-lag", type=float, default=30.0)
    s.add_argument("--expect-lag", type=float, help="known lag in seconds (e.g. interface latency)")
    s.add_argument("--window", type=float, default=0.1, help="+/- tolerance around --expect-lag")
    s.add_argument("--sr", type=int, default=22050)
    s.set_defaults(func=_cmd_sync)

    g = sub.add_parser("groove", help="timing deviation of performance onsets vs a grid")
    g.add_argument("--perf", required=True, help="performance file, e.g. guitar take")
    g.add_argument("--align-to", help="DAW bounce or click reference; estimates latency")
    g.add_argument("--expect-lag", type=float, help="known latency (s) to constrain alignment")
    g.add_argument("--window", type=float, default=0.1)
    g.add_argument("--lag", type=float, default=0.0, help="manual latency (s) if not aligning")
    grid = g.add_mutually_exclusive_group(required=True)
    grid.add_argument("--grid-bpm", type=float, help="metronome tempo")
    grid.add_argument("--grid-from", help="derive grid beats from this file")
    g.add_argument("--grid-offset", type=float, default=0.0)
    g.add_argument("--subdivision", type=int, default=1, help="1=quarter notes, 2=8ths, 4=16ths")
    g.add_argument("--max-dev", type=float, default=120.0)
    g.add_argument("--sr", type=int, default=22050)
    g.set_defaults(func=_cmd_groove)

    d = sub.add_parser("demo", help="generate synthetic demo assets")
    d.add_argument("--out", default="web/demo")
    d.set_defaults(func=_cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
