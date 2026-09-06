"""Report wrapper that keeps full-video technical status stable across page loads."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import legacy_main
import scoring_routes
from database import Answer, get_db
from mvp_models import FullInterviewMedia
from services.media_service import media_metadata

router = APIRouter()


def _timeline_duration_ms(session_id: int, db: Session) -> int | None:
    answers = db.query(Answer).filter(Answer.session_id == session_id).all()
    values = [
        int(answer.media.end_ms)
        for answer in answers
        if answer.media and answer.media.end_ms and answer.media.end_ms > 0
    ]
    return max(values) if values else None


@router.get("/api/reports/{session_id}", response_class=JSONResponse)
async def get_report(
    session_id: int,
    current_user=Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    payload = await scoring_routes.get_report(session_id=session_id, current_user=current_user, db=db)

    stored = db.query(FullInterviewMedia).filter(FullInterviewMedia.session_id == session_id).first()
    path = stored.path if stored else None
    if not path:
        found = legacy_main._find_full_video(session_id)
        path = str(found) if found else None

    fallback_duration = stored.duration_ms if stored and stored.duration_ms else _timeline_duration_ms(session_id, db)
    source = stored.duration_source if stored else ("answer_timeline" if fallback_duration else "unknown")
    meta = media_metadata(path, fallback_duration)
    meta["duration_source"] = source
    meta["technical_status"] = "available" if meta["playable"] else "needs_check"
    meta["technical_status_label"] = (
        "Видео доступно для просмотра"
        if meta["playable"]
        else "Автоматическая техническая проверка файла не завершена"
    )

    payload["full_video_path"] = legacy_main._web_upload_path(path) if path else None
    payload["full_video_media"] = meta
    return payload
