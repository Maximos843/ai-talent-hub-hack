"""Adaptive follow-up question flow for candidate interviews."""
from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import legacy_main
from adaptive_models import (
    AdaptiveProbeDecision,
    AnswerQuestionLink,
    InterviewQuestionProbeConfig,
    QuestionProbeConfig,
)
from config import ANSWER_TIME_LIMIT_SECONDS
from database import Answer, InterviewQuestion, InterviewSession, SessionQuestion, get_db
from services import llm_service


router = APIRouter()
MAX_FOLLOW_UPS = 2
FOLLOW_UP_CONFIDENCE_THRESHOLD = 0.55


def _clean_list(values) -> list[str]:
    result = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result


def _norm_question(value: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", " ", (value or "").lower()).strip()


def snapshot_probe_configs(session: InterviewSession, db: Session) -> None:
    """Freeze bank-level follow-up hints onto a candidate's planned questions."""
    for iq in session.interview_questions or []:
        existing = (
            db.query(InterviewQuestionProbeConfig)
            .filter(InterviewQuestionProbeConfig.interview_question_id == iq.id)
            .first()
        )
        if existing:
            continue
        possible = []
        if iq.source_session_question_id:
            sq = db.query(SessionQuestion).filter(SessionQuestion.id == iq.source_session_question_id).first()
            if sq:
                config = (
                    db.query(QuestionProbeConfig)
                    .filter(QuestionProbeConfig.question_id == sq.question_id)
                    .first()
                )
                possible = _clean_list(config.possible_extra_questions if config else [])
        db.add(
            InterviewQuestionProbeConfig(
                interview_question_id=iq.id,
                possible_extra_questions=possible,
            )
        )
    db.commit()


def _question_for_answer(answer: Answer, db: Session) -> Optional[InterviewQuestion]:
    link = db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id == answer.id).first()
    if link:
        return db.query(InterviewQuestion).filter(InterviewQuestion.id == link.interview_question_id).first()
    return (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.session_id == answer.session_id,
            InterviewQuestion.question_text == answer.question_text,
        )
        .order_by(InterviewQuestion.id)
        .first()
    )


def _ensure_answer_link(answer: Answer, question: InterviewQuestion, db: Session) -> AnswerQuestionLink:
    link = db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id == answer.id).first()
    if not link:
        link = AnswerQuestionLink(answer_id=answer.id, interview_question_id=question.id)
        db.add(link)
        db.flush()
    return link


def _root_question(question: InterviewQuestion, db: Session) -> InterviewQuestion:
    parent = (
        db.query(AdaptiveProbeDecision)
        .filter(AdaptiveProbeDecision.follow_up_question_id == question.id)
        .first()
    )
    if not parent:
        return question
    return db.query(InterviewQuestion).filter(InterviewQuestion.id == parent.root_interview_question_id).first() or question


def _follow_up_count(root_id: int, db: Session) -> int:
    return (
        db.query(AdaptiveProbeDecision)
        .filter(
            AdaptiveProbeDecision.root_interview_question_id == root_id,
            AdaptiveProbeDecision.ask_follow_up.is_(True),
            AdaptiveProbeDecision.follow_up_question_id.is_not(None),
        )
        .count()
    )


def _chain_questions(root: InterviewQuestion, db: Session) -> list[InterviewQuestion]:
    result = [root]
    decisions = (
        db.query(AdaptiveProbeDecision)
        .filter(
            AdaptiveProbeDecision.root_interview_question_id == root.id,
            AdaptiveProbeDecision.ask_follow_up.is_(True),
            AdaptiveProbeDecision.follow_up_question_id.is_not(None),
        )
        .order_by(AdaptiveProbeDecision.id)
        .all()
    )
    for decision in decisions:
        question = db.query(InterviewQuestion).filter(InterviewQuestion.id == decision.follow_up_question_id).first()
        if question:
            result.append(question)
    return result


def _chain_turns(root: InterviewQuestion, db: Session) -> list[dict]:
    turns = []
    for question in _chain_questions(root, db):
        link = (
            db.query(AnswerQuestionLink)
            .filter(AnswerQuestionLink.interview_question_id == question.id)
            .order_by(AnswerQuestionLink.id.desc())
            .first()
        )
        answer = db.query(Answer).filter(Answer.id == link.answer_id).first() if link else None
        if not answer or not answer.is_approved_by_candidate:
            continue
        analysis = answer.llm_analysis or {}
        turns.append(
            {
                "question_id": str(question.id),
                "question": question.question_text,
                "transcript": answer.transcript_corrected or answer.transcript_raw or "",
                "score_0_10": analysis.get("score_0_10", answer.score if answer.score is not None else 5),
                "summary": analysis.get("summary", analysis.get("analysis", "")),
            }
        )
    return turns


def _decision_response(decision: AdaptiveProbeDecision, db: Session) -> dict:
    follow_up = None
    if decision.ask_follow_up and decision.follow_up_question_id:
        question = db.query(InterviewQuestion).filter(InterviewQuestion.id == decision.follow_up_question_id).first()
        if question:
            follow_up = {
                "session_question_id": question.id,
                "question": question.question_text,
                "follow_up_index": decision.follow_up_count_before + 1,
                "max_follow_ups": MAX_FOLLOW_UPS,
                "root_question_id": decision.root_interview_question_id,
            }
    return {
        "message": "Транскрипция подтверждена",
        "answer_id": decision.trigger_answer_id,
        "follow_up": follow_up,
    }


async def _make_probe_decision(answer: Answer, question: InterviewQuestion, db: Session) -> AdaptiveProbeDecision:
    root = _root_question(question, db)
    follow_up_count = _follow_up_count(root.id, db)
    config = (
        db.query(InterviewQuestionProbeConfig)
        .filter(InterviewQuestionProbeConfig.interview_question_id == root.id)
        .first()
    )
    possible = _clean_list(config.possible_extra_questions if config else [])
    turns = _chain_turns(root, db)
    scores = [float(turn["score_0_10"]) for turn in turns if turn.get("score_0_10") is not None]
    fallback_score = sum(scores) / len(scores) if scores else float(answer.score if answer.score is not None else 5.0)

    if (root.competency or "").strip().lower() in {"motivation", "motivational", "мотивация"}:
        result = {
            "ask_follow_up": False,
            "follow_up_question": None,
            "follow_up_must_have": [],
            "reason": "Мотивационный вопрос не участвует в автоматическом техническом probing.",
            "focus": "",
            "source": "none",
            "resolved_root_score_0_10": fallback_score,
            "confidence_0_1": 1.0,
        }
    else:
        result = await llm_service.decide_follow_up(
            root_question_id=str(root.id),
            root_question=root.question_text,
            competency=root.competency or "general",
            reference_answer=root.reference_answer or "",
            must_have=root.must_have or [],
            nice_to_have=root.nice_to_have or [],
            red_flags=root.red_flags or [],
            possible_extra_questions=possible,
            turns=turns,
            already_asked_questions=[item.question_text for item in _chain_questions(root, db)],
            follow_up_count=follow_up_count,
            max_follow_ups=MAX_FOLLOW_UPS,
        )

    ask = bool(result.get("ask_follow_up"))
    confidence = max(0.0, min(1.0, float(result.get("confidence_0_1", 0.0))))
    text = str(result.get("follow_up_question") or "").strip()
    normalized_asked = {_norm_question(item.question_text) for item in _chain_questions(root, db)}
    if (
        follow_up_count >= MAX_FOLLOW_UPS
        or confidence < FOLLOW_UP_CONFIDENCE_THRESHOLD
        or len(text) < 10
        or _norm_question(text) in normalized_asked
    ):
        ask = False
        text = ""

    resolved = result.get("resolved_root_score_0_10", fallback_score)
    try:
        resolved = max(0.0, min(10.0, float(resolved)))
    except (TypeError, ValueError):
        resolved = fallback_score

    follow_up_question = None
    source = "none"
    if ask:
        source = "possible_extra_questions" if _norm_question(text) in {_norm_question(x) for x in possible} else "generated"
        must_have = _clean_list(result.get("follow_up_must_have", []))[:4]
        max_order = max([item.order_index for item in answer.interview_session.interview_questions], default=-1)
        follow_up_question = InterviewQuestion(
            session_id=answer.session_id,
            source_session_question_id=None,
            question_text=text,
            competency=root.competency or "general",
            reference_answer=str(result.get("focus") or "").strip(),
            must_have=must_have,
            nice_to_have=[],
            red_flags=[],
            order_index=max_order + 1,
            is_active=True,
            is_custom=True,
        )
        db.add(follow_up_question)
        db.flush()
        db.add(
            InterviewQuestionProbeConfig(
                interview_question_id=follow_up_question.id,
                possible_extra_questions=[],
            )
        )

    decision = AdaptiveProbeDecision(
        session_id=answer.session_id,
        root_interview_question_id=root.id,
        trigger_answer_id=answer.id,
        follow_up_question_id=follow_up_question.id if follow_up_question else None,
        follow_up_count_before=follow_up_count,
        ask_follow_up=ask,
        reason=str(result.get("reason") or "").strip(),
        focus=str(result.get("focus") or "").strip(),
        source=source,
        resolved_root_score_0_10=round(resolved, 2),
        confidence_0_1=confidence,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


@router.get("/api/interviews/{session_token}", response_class=JSONResponse)
async def get_interview_session(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.final_report:
        raise HTTPException(status_code=400, detail="Интервью уже завершено")
    legacy_main._copy_default_questions_to_session(session, db)
    generated_ids = {
        row[0]
        for row in db.query(AdaptiveProbeDecision.follow_up_question_id)
        .filter(
            AdaptiveProbeDecision.session_id == session.id,
            AdaptiveProbeDecision.follow_up_question_id.is_not(None),
        )
        .all()
    }
    questions = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.session_id == session.id,
            InterviewQuestion.is_active.is_(True),
        )
        .order_by(InterviewQuestion.order_index, InterviewQuestion.id)
        .all()
    )
    questions = [question for question in questions if question.id not in generated_ids]
    if not questions:
        raise HTTPException(status_code=400, detail="HR ещё не настроил вопросы интервью")
    return {
        "session_id": session.id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "questions": [{"session_question_id": q.id, "question": q.question_text} for q in questions],
        "time_limit": ANSWER_TIME_LIMIT_SECONDS,
        "adaptive_follow_ups": {"enabled": True, "max_per_question": MAX_FOLLOW_UPS},
    }


@router.post("/api/interviews/correct-transcript", response_class=JSONResponse)
async def correct_transcript(payload: legacy_main.TranscriptCorrection, db: Session = Depends(get_db)):
    answer = db.query(Answer).filter(Answer.id == payload.answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Ответ не найден")
    corrected = payload.corrected_transcript.strip()
    if not corrected:
        raise HTTPException(status_code=400, detail="Транскрипция не может быть пустой")

    existing = (
        db.query(AdaptiveProbeDecision)
        .filter(AdaptiveProbeDecision.trigger_answer_id == answer.id)
        .first()
    )
    if existing:
        if corrected != (answer.transcript_corrected or "").strip():
            raise HTTPException(status_code=409, detail="Ответ уже подтверждён и использован для выбора следующего вопроса")
        return _decision_response(existing, db)

    question = _question_for_answer(answer, db)
    if not question:
        raise HTTPException(status_code=404, detail="Не удалось определить вопрос для ответа")
    _ensure_answer_link(answer, question, db)
    answer.transcript_corrected = corrected
    answer.is_approved_by_candidate = True
    db.commit()

    # Import lazily to avoid a module-import cycle between canonical routers.
    from scoring_routes import _analyze_answer

    await _analyze_answer(answer, db)
    decision = await _make_probe_decision(answer, question, db)
    return _decision_response(decision, db)
