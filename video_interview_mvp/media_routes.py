"""Canonical full-video upload with durable playback metadata."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import legacy_main
from database import InterviewSession, get_db
from mvp_models import FullInterviewMedia
from services.media_service import media_metadata, normalize_video

router = APIRouter()


def _answer_timeline_duration_ms(session: InterviewSession) -> int | None:
    values = [
        int(answer.media.end_ms)
        for answer in session.answers
        if answer.media and answer.media.end_ms and answer.media.end_ms > 0
    ]
    return max(values) if values else None


@router.post("/api/interviews/{session_id}/full-video", response_class=JSONResponse)
async def upload_full_interview_video(
    session_id: int,
    client_duration_ms: int = Form(0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Получена пустая видеозапись")

    extension = legacy_main._safe_upload_extension(file.filename)
    destination = legacy_main.UPLOAD_DIR / f"full_interview_{session_id}{extension}"
    destination.write_bytes(content)

    normalized_path, probed_duration = normalize_video(destination)
    timeline_duration = _answer_timeline_duration_ms(session)
    if probed_duration:
        duration_ms = probed_duration
        duration_source = "server_probe"
    elif client_duration_ms > 0:
        duration_ms = client_duration_ms
        duration_source = "client_reported"
    else:
        duration_ms = timeline_duration
        duration_source = "answer_timeline" if timeline_duration else "unknown"

    legacy_main._build_answer_clips(session, normalized_path, db)
    metadata = media_metadata(str(normalized_path), duration_ms)

    stored = db.query(FullInterviewMedia).filter(FullInterviewMedia.session_id == session_id).first()
    if not stored:
        stored = FullInterviewMedia(session_id=session_id, path=str(normalized_path))
        db.add(stored)
    stored.path = str(normalized_path)
    stored.duration_ms = duration_ms
    stored.size_bytes = normalized_path.stat().st_size if normalized_path.exists() else 0
    stored.duration_source = duration_source
    stored.normalized = "normalized" in normalized_path.stem
    db.commit()

    return {
        "message": "Полная видеозапись сохранена",
        "video_path": legacy_main._web_upload_path(str(normalized_path)),
        "duration_source": duration_source,
        "technical_status": "available" if metadata["playable"] else "needs_check",
        **metadata,
    }
