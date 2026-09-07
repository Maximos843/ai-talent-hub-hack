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
from services.document_service import polish_transcript
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
    legacy_main._assert_link_live(session)
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
    # Термины из самого вопроса и его рубрики: Deepgram распознаёт их как
    # термины, а не как похожие по звуку слова.
    keyterms = [
        *(interview_question.must_have or []),
        *(interview_question.nice_to_have or []),
        *interview_question.question_text.split(),
    ]
    if file_bytes:
        asr_result = await asr_service.transcribe_audio(file_bytes, language="ru", keyterms=keyterms)
        if asr_result.get("success") and asr_result.get("transcript"):
            raw_transcript = asr_result["transcript"].strip()
            asr_confidence = asr_result.get("confidence")
        elif not raw_transcript:
            raise HTTPException(
                status_code=502,
                detail=f"Не удалось распознать речь: {asr_result.get('error', 'ASR error')}",
            )

    # Расшифровку показываем кандидату и оцениваем — она должна быть читаемой.
    polished = await polish_transcript(raw_transcript, interview_question.question_text, keyterms)

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
        transcript_corrected=polished,
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


@router.delete("/api/interviews/answers/{answer_id}", response_class=JSONResponse)
async def discard_answer(answer_id: int, db: Session = Depends(get_db)):
    """«Ответить заново»: удаляет неподтверждённый ответ, чтобы записать заново.

    Безопасно, потому что оценка и решение об уточняющем вопросе создаются только
    при подтверждении транскрипта. У неподтверждённого ответа нет ни балла, ни
    AdaptiveProbeDecision — удалять нечего, кроме самого ответа, его медиа-строки,
    связи с вопросом и загруженного аудиофайла.
    """
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Ответ не найден")
    session = answer.interview_session
    if session and session.final_report:
        raise HTTPException(status_code=404, detail="Интервью уже завершено")
    if answer.is_approved_by_candidate:
        raise HTTPException(status_code=404, detail="Ответ уже подтверждён и не может быть удалён")

    if answer.audio_path:
        try:
            os.remove(answer.audio_path)
        except OSError:
            pass  # файла может не быть — это не мешает удалить запись
    db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id == answer.id).delete()
    db.delete(answer)  # AnswerMedia уходит каскадом (delete-orphan)
    db.commit()
    return {"message": "Ответ удалён"}
