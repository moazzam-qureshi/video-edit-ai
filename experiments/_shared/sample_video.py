"""
Shared helpers for loading sample videos and pulling frames.

Design choices:
- We shell out to ffmpeg/ffprobe instead of using OpenCV for I/O. Reason:
  OpenCV's VideoCapture has well-known accuracy issues with timestamps and
  variable-frame-rate videos. ffmpeg is the production tool we'll use anyway.
- Functions return Paths to artifacts on disk, not in-memory arrays — keeps
  memory bounded for long videos, and lets downstream tools (PySceneDetect,
  MediaPipe) consume files directly.
- Everything is deterministic given the same inputs, so re-runs produce
  identical outputs and metrics.json deltas are meaningful.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FfmpegNotFound(RuntimeError):
    pass


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise FfmpegNotFound(
            "ffmpeg/ffprobe not on PATH. On the VPS: sudo apt install -y ffmpeg"
        )


@dataclass
class VideoInfo:
    path: Path
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    codec: str
    size_mb: float


def probe(video_path: str | Path) -> VideoInfo:
    """Inspect a video with ffprobe. Cheap; safe to call repeatedly."""
    _require_ffmpeg()
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(p)

    cmd = [
        "ffprobe", "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(p),
    ]
    out = subprocess.check_output(cmd).decode("utf-8", errors="replace")
    data = json.loads(out)

    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise ValueError(f"{p}: no video stream")
    v = video_streams[0]

    fps_str = v.get("avg_frame_rate", "0/1")
    num, _, den = fps_str.partition("/")
    try:
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0.0)

    return VideoInfo(
        path=p,
        duration_s=duration,
        width=int(v.get("width", 0)),
        height=int(v.get("height", 0)),
        fps=fps,
        has_audio=bool(audio_streams),
        codec=v.get("codec_name", "unknown"),
        size_mb=round(p.stat().st_size / 1024**2, 2),
    )


def extract_audio(
    video_path: str | Path,
    out_path: str | Path,
    sample_rate: int = 16000,
    mono: bool = True,
) -> Path:
    """
    Pull audio out as 16 kHz mono WAV — the input format Whisper/Silero want.
    Overwrites out_path if it exists.
    """
    _require_ffmpeg()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vn",
        "-ac", "1" if mono else "2",
        "-ar", str(sample_rate),
        "-acodec", "pcm_s16le",
        str(out),
    ]
    subprocess.check_call(cmd)
    return out


def extract_frames(
    video_path: str | Path,
    out_dir: str | Path,
    fps: float = 1.0,
    max_width: int | None = 768,
    quality: int = 3,
) -> list[Path]:
    """
    Sample frames at `fps` frames-per-second of source video.

    - max_width: if set, scales frames preserving aspect (height auto). Common
      vision models accept 512-768px happily; defaults to 768.
    - quality: ffmpeg -q:v scale (2 best, 31 worst). 3 is high quality, small.

    Returns sorted list of frame paths. Frames named frame_000001.jpg etc.
    """
    _require_ffmpeg()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("frame_*.jpg"):
        f.unlink()

    vf = [f"fps={fps}"]
    if max_width is not None:
        vf.append(f"scale={max_width}:-2")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", ",".join(vf),
        "-q:v", str(quality),
        str(out / "frame_%06d.jpg"),
    ]
    subprocess.check_call(cmd)
    return sorted(out.glob("frame_*.jpg"))


def extract_frame_at(
    video_path: str | Path,
    timestamp_s: float,
    out_path: str | Path,
    max_width: int | None = 768,
    quality: int = 3,
) -> Path:
    """Single-frame grab at a specific timestamp. Useful for cut analysis (VM-1)."""
    _require_ffmpeg()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = []
    if max_width is not None:
        vf.append(f"scale={max_width}:-2")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{timestamp_s:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", str(quality),
    ]
    if vf:
        cmd.extend(["-vf", ",".join(vf)])
    cmd.append(str(out))
    subprocess.check_call(cmd)
    return out


def clip(
    video_path: str | Path,
    out_path: str | Path,
    start_s: float,
    duration_s: float,
    copy_codec: bool = True,
) -> Path:
    """
    Cut a sub-clip. `copy_codec=True` is fast (no re-encode) but cuts at the
    nearest keyframe — slightly inaccurate at boundaries. Set False for frame-
    accurate cuts when correctness matters more than speed.
    """
    _require_ffmpeg()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start_s:.3f}", "-i", str(video_path), "-t", f"{duration_s:.3f}"]
    if copy_codec:
        cmd.extend(["-c", "copy"])
    cmd.append(str(out))
    subprocess.check_call(cmd)
    return out
