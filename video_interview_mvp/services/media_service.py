"""Helpers for durable browser MediaRecorder uploads.

Browser MediaRecorder files (especially WebM blobs made from timeslices) can be
valid media while still missing duration/cue metadata. Browsers then display
0:00. The Docker image already contains ffmpeg, so uploads are normalized once
on the server and probed before they are exposed in reports.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _run(command: list[str], timeout: int = 90) -> bool:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def probe_duration_ms(path: Path) -> Optional[int]:
    if not FFPROBE or not path.exists() or path.stat().st_size == 0:
        return None
    try:
        result = subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        payload = json.loads(result.stdout or "{}")
        duration = float((payload.get("format") or {}).get("duration") or 0)
        return int(round(duration * 1000)) if duration > 0 else None
    except (ValueError, json.JSONDecodeError, subprocess.SubprocessError, OSError):
        return None


def normalize_audio(source: Path) -> tuple[Path, Optional[int]]:
    """Convert browser audio to MP3 with deterministic duration metadata."""
    if not FFMPEG or not source.exists():
        return source, probe_duration_ms(source)

    target = source.with_suffix(".mp3")
    ok = _run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-map_metadata",
            "-1",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(target),
        ],
        timeout=45,
    )
    if not ok or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return source, probe_duration_ms(source)

    source.unlink(missing_ok=True)
    return target, probe_duration_ms(target)


def normalize_video(source: Path) -> tuple[Path, Optional[int]]:
    """Remux browser video so the container has duration/cue metadata."""
    if not FFMPEG or not source.exists():
        return source, probe_duration_ms(source)

    suffix = source.suffix.lower()
    if suffix == ".mp4":
        target = source.with_name(f"{source.stem}_normalized.mp4")
        command = [
            FFMPEG,
            "-y",
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ]
    else:
        target = source.with_name(f"{source.stem}_normalized.webm")
        command = [
            FFMPEG,
            "-y",
            "-i",
            str(source),
            "-map",
            "0",
            "-c",
            "copy",
            str(target),
        ]

    ok = _run(command, timeout=120)
    if not ok or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return source, probe_duration_ms(source)

    duration = probe_duration_ms(target)
    source.unlink(missing_ok=True)
    return target, duration


def extract_video_clip(source: Path, target: Path, start_ms: int, end_ms: int) -> tuple[Optional[Path], Optional[int]]:
    """Create an independently seekable per-answer clip from continuous video."""
    if not FFMPEG or not source.exists() or end_ms <= start_ms:
        return None, None

    start_seconds = max(0, start_ms) / 1000
    duration_seconds = max(0.25, (end_ms - start_ms) / 1000)
    target.parent.mkdir(parents=True, exist_ok=True)
    ok = _run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-i",
            str(source),
            "-t",
            f"{duration_seconds:.3f}",
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            "realtime",
            "-cpu-used",
            "6",
            "-b:v",
            "650k",
            "-c:a",
            "libopus",
            "-b:a",
            "64k",
            str(target),
        ],
        timeout=max(45, int(duration_seconds * 4)),
    )
    if not ok or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return None, None
    return target, probe_duration_ms(target)


def media_metadata(path: Optional[str], fallback_duration_ms: Optional[int] = None) -> dict:
    if not path:
        return {"exists": False, "size_bytes": 0, "duration_ms": fallback_duration_ms, "playable": False}
    file_path = Path(path)
    exists = file_path.exists()
    size = file_path.stat().st_size if exists else 0
    duration = probe_duration_ms(file_path) if exists else None
    duration = duration or fallback_duration_ms
    return {
        "exists": exists,
        "size_bytes": size,
        "duration_ms": duration,
        "playable": bool(exists and size > 1000 and duration and duration >= 500),
    }
