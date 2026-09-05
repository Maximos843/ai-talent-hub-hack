"""Helpers for durable browser MediaRecorder uploads.

MediaRecorder blobs (especially WebM assembled from timeslices) may contain valid
media but miss duration/cue metadata. Browsers then render them as 0:00.  The
hackathon image already contains ffmpeg, so uploads are remuxed/transcoded once
on the server and probed before we expose them in reports.
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
    """Return media duration in milliseconds when ffprobe can determine it."""
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
    """Convert a browser audio blob to MP3 for predictable report playback.

    MP3 is intentionally used here because it plays in all target browsers and
    ffmpeg writes deterministic duration metadata.  If ffmpeg is unavailable we
    keep the original upload and rely on the client-side measured duration.
    """
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
    """Remux browser video so the container contains duration/cue metadata.

    No video re-encode is done: it would be unnecessarily slow for a hackathon
    interview.  MP4 gets fast-start metadata; WebM is remuxed into a fresh WebM
    container. If remuxing fails, the original upload is retained.
    """
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
