"""Candidate answer submission with an explicit Answer -> InterviewQuestion link.

The legacy endpoint kept only question text/source SessionQuestion, which becomes
ambiguous once adaptive questions are generated. This route preserves the same
HTTP contract and media/ASR behavior while storing the exact shown question id.
"""
from __future__ import annotations

import os
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from fastapi import Depends

import legacy_main
from adaptive_models import AnswerQuestionLink
from database import Answer, AnswerMedia, InterviewQuestion, InterviewSession, get_db
from services import asr_service
from services.media_service import normalize_audio


router = APIRouter()


@router.post("/api/interviews/submit-answer", response_class=JSONResponse)
async def submit_answer(
    session_id: int = Form(...),
    question_id: int = Form(...),
    transcript: str = Form(""),
    start_ms: int = Form(0),
    end_ms: int = Form(0),
    client_duration_ms: int = Form(0),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    interview_question = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.id == question_id,
            InterviewQuestion.session_id == session.id,
            InterviewQuestion.is_active.is_(True),
        )
        .first()
    )
    if not interview_question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")

    audio_path = None
    audio_duration_ms = client_duration_ms if client_duration_ms > 0 else None
    audio_size_bytes = None
    file_bytes = b""
    raw_upload_path = None
    if file:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Получена пустая аудиозапись")
        extension = legacy_main._safe_upload_extension(file.filename)
        filename = f"answer_{session_id}_{question_id}_{uuid.uuid4().hex[:8]}{extension}"
        raw_upload_path = legacy_main.UPLOAD_DIR / filename
        raw_upload_path.write_bytes(file_bytes)

    raw_transcript = transcript.strip()
    asr_confidence = None
    if file_bytes:
        asr_result = await asr_service.transcribe_audio(file_bytes, language="ru")
        if asr_result.get("success") and asr_result.get("transcript"):
            raw_transcript = asr_result["transcript"].strip()
            asr_confidence = asr_result.get("confidence")
        elif not raw_transcript:
            raise HTTPException(
                status_code=502,
                detail=f"Не удалось распознать речь: {asr_result.get('error', 'ASR error')}",
            )

    if raw_upload_path:
        normalized_path, probed_duration = normalize_audio(raw_upload_path)
        audio_path = str(normalized_path)
        audio_duration_ms = probed_duration or audio_duration_ms
        audio_size_bytes = normalized_path.stat().st_size if normalized_path.exists() else len(file_bytes)

    answer = Answer(
        session_id=session_id,
        session_question_id=interview_question.source_session_question_id,
        question_text=interview_question.question_text,
        video_path=None,
        audio_path=audio_path,
        transcript_raw=raw_transcript,
        transcript_corrected=raw_transcript,
        is_approved_by_candidate=False,
    )
    db.add(answer)
    db.flush()
    db.add(AnswerQuestionLink(answer_id=answer.id, interview_question_id=interview_question.id))
    effective_end = max(end_ms, start_ms + (audio_duration_ms or 0))
    db.add(
        AnswerMedia(
            answer_id=answer.id,
            start_ms=max(0, start_ms),
            end_ms=max(start_ms, effective_end),
            audio_duration_ms=audio_duration_ms,
            audio_size_bytes=audio_size_bytes,
        )
    )
    db.commit()
    db.refresh(answer)
    return {
        "answer_id": answer.id,
        "message": "Ответ сохранён",
        "transcript": raw_transcript,
        "asr_confidence": asr_confidence,
        "mock_asr": not bool(os.getenv("DEEPGRAM_API_KEY")),
        "audio_duration_ms": audio_duration_ms,
        "audio_size_bytes": audio_size_bytes,
    }
