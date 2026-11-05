"""Audio loading shared by every workflow.

Accepts WAV/FLAC/OGG/MP3 directly through librosa. OBS recordings (MKV/MP4/MOV)
are demuxed with ffmpeg into a temporary WAV first, keeping the native channel
layout so that stereo metrics stay honest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import librosa
import numpy as np

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".mov", ".flv", ".ts", ".webm", ".m4v"}


def load_audio(path: str | os.PathLike, sr: int = 22050) -> tuple[np.ndarray, int]:
    """Return ``(channels, samples)`` float32 audio at ``sr`` and the sample rate."""
    path = Path(path)
    source = path
    tmp_name: str | None = None

    if path.suffix.lower() in VIDEO_EXTENSIONS:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError(
                f"{path.name} is a video container. ffmpeg is required to extract its audio "
                "(install ffmpeg, or export a WAV from OBS / your DAW first)."
            )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_name = tmp.name
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(path), "-vn",
             "-ar", str(sr), "-c:a", "pcm_s16le", tmp_name],
            check=True,
        )
        source = Path(tmp_name)

    try:
        y, _ = librosa.load(str(source), sr=sr, mono=False)
    finally:
        if tmp_name is not None:
            os.unlink(tmp_name)

    if y.ndim == 1:
        y = y[np.newaxis, :]
    return y.astype(np.float32), sr
