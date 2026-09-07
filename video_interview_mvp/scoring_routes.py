"""Canonical scoring pipeline routes.

These routes keep the existing DB schema compatible while storing the new
structured per-answer and final-interview JSON contracts.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import legacy_main
from adaptive_models import AdaptiveProbeDecision, AnswerQuestionLink
from database import Answer, FinalReport, InterviewQuestion, InterviewSession, SessionQuestion, get_db
from services import llm_service


router = APIRouter()


def _linked_question(answer: Answer, db: Session):
    link = db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id == answer.id).first()
    if link:
        question = db.query(InterviewQuestion).filter(InterviewQuestion.id == link.interview_question_id).first()
        if question:
            return question
    return (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.session_id == answer.session_id,
            InterviewQuestion.question_text == answer.question_text,
        )
        .order_by(InterviewQuestion.id)
        .first()
    )


async def _analyze_answer(answer: Answer, db: Session) -> None:
    iq = _linked_question(answer, db)
    if iq:
        question_id = str(iq.id)
        question_text = iq.question_text
        competency = iq.competency or "general"
        reference_answer = iq.reference_answer or ""
        must_have = iq.must_have or []
        nice_to_have = iq.nice_to_have or []
        red_flags = iq.red_flags or []
    else:
        sq = db.query(SessionQuestion).filter(SessionQuestion.id == answer.session_question_id).first()
        q = sq.question if sq else None
        question_id = str(q.id if q else answer.id)
        question_text = answer.question_text or (q.question_text if q else "")
        competency = q.competency if q and q.competency else "general"
        reference_answer = q.reference_answer if q else ""
        must_have = q.must_have if q else []
        nice_to_have = q.nice_to_have if q else []
        red_flags = q.red_flags if q else []

    analysis = await llm_service.analyze_answer(
        question=question_text,
        reference_answer=reference_answer or "",
        must_have=must_have or [],
        nice_to_have=nice_to_have or [],
        red_flags=red_flags or [],
        candidate_transcript=answer.transcript_corrected or answer.transcript_raw or "",
        question_id=question_id,
        competency=competency,
    )
    answer.score = float(analysis["score_0_10"])
    answer.llm_analysis = analysis
    db.commit()


def _adaptive_answer_meta(answer: Answer, db: Session) -> dict:
    iq = _linked_question(answer, db)
    if not iq:
        return {
            "question": None,
            "root_question_id": None,
            "is_follow_up": False,
            "follow_up_index": None,
            "probe_reason": "",
            "probe_focus": "",
            "probe_source": "none",
            "technical_score_0_10": answer.score,
        }
    parent = (
        db.query(AdaptiveProbeDecision)
        .filter(AdaptiveProbeDecision.follow_up_question_id == iq.id)
        .first()
    )
    root_id = parent.root_interview_question_id if parent else iq.id
    latest = (
        db.query(AdaptiveProbeDecision)
        .filter(AdaptiveProbeDecision.root_interview_question_id == root_id)
        .order_by(AdaptiveProbeDecision.id.desc())
        .first()
    )
    resolved = latest.resolved_root_score_0_10 if latest and latest.resolved_root_score_0_10 is not None else answer.score
    return {
        "question": iq,
        "root_question_id": root_id,
        "is_follow_up": bool(parent),
        "follow_up_index": (parent.follow_up_count_before + 1) if parent else None,
        "probe_reason": parent.reason if parent else "",
        "probe_focus": parent.focus if parent else "",
        "probe_source": parent.source if parent else "none",
        "technical_score_0_10": resolved,
    }


def _answer_for_final(answer: Answer, db: Session, index: int) -> dict:
    meta = _adaptive_answer_meta(answer, db)
    iq = meta["question"]
    sq = db.query(SessionQuestion).filter(SessionQuestion.id == answer.session_question_id).first() if not iq else None
    q = sq.question if sq else None
    evaluation = answer.llm_analysis or {}
    question_id = str(iq.id if iq else (q.id if q else index))
    competency = (iq.competency if iq else (q.competency if q else "general")) or "general"
    return {
        "question_id": question_id,
        "question_text": answer.question_text or (iq.question_text if iq else (q.question_text if q else "")),
        "competency": competency,
        "transcript": answer.transcript_corrected or answer.transcript_raw or "",
        "is_follow_up": meta["is_follow_up"],
        "root_question_id": str(meta["root_question_id"] or question_id),
        "follow_up_index": meta["follow_up_index"],
        "probe_reason": meta["probe_reason"] or "",
        "probe_focus": meta["probe_focus"] or "",
        "probe_source": meta["probe_source"],
        "counts_toward_technical_average": not meta["is_follow_up"],
        "technical_score_0_10": meta["technical_score_0_10"],
        "evaluation": {
            "score_0_10": evaluation.get("score_0_10", answer.score if answer.score is not None else 5),
            "covered_must_have": evaluation.get("covered_must_have", []),
            "missing_must_have": evaluation.get("missing_must_have", []),
            "covered_nice_to_have": evaluation.get("covered_nice_to_have", []),
            "red_flags_found": evaluation.get("red_flags_found", []),
            "evidence_quotes": evaluation.get("evidence_quotes", []),
            "summary": evaluation.get("summary", evaluation.get("analysis", "")),
            "confidence_0_1": evaluation.get("confidence_0_1", evaluation.get("confidence", 0.0)),
        },
    }


def _answer_for_question(question_id: int, db: Session):
    link = (
        db.query(AnswerQuestionLink)
        .filter(AnswerQuestionLink.interview_question_id == question_id)
        .order_by(AnswerQuestionLink.id.desc())
        .first()
    )
    return db.query(Answer).filter(Answer.id == link.answer_id).first() if link else None


def _adaptive_follow_up_report(session_id: int, db: Session) -> list[dict]:
    decisions = (
        db.query(AdaptiveProbeDecision)
        .filter(
            AdaptiveProbeDecision.session_id == session_id,
            AdaptiveProbeDecision.ask_follow_up.is_(True),
            AdaptiveProbeDecision.follow_up_question_id.is_not(None),
        )
        .order_by(AdaptiveProbeDecision.root_interview_question_id, AdaptiveProbeDecision.id)
        .all()
    )
    grouped: dict[int, list[AdaptiveProbeDecision]] = {}
    for decision in decisions:
        grouped.setdefault(decision.root_interview_question_id, []).append(decision)

    result = []
    for root_id, items in grouped.items():
        root = db.query(InterviewQuestion).filter(InterviewQuestion.id == root_id).first()
        if not root:
            continue
        root_answer = _answer_for_question(root.id, db)
        latest = (
            db.query(AdaptiveProbeDecision)
            .filter(AdaptiveProbeDecision.root_interview_question_id == root.id)
            .order_by(AdaptiveProbeDecision.id.desc())
            .first()
        )
        follow_ups = []
        for decision in items:
            question = db.query(InterviewQuestion).filter(InterviewQuestion.id == decision.follow_up_question_id).first()
            answer = _answer_for_question(question.id, db) if question else None
            follow_ups.append({
                "index": decision.follow_up_count_before + 1,
                "question_id": question.id if question else decision.follow_up_question_id,
                "question": question.question_text if question else "",
                "reason": decision.reason or "",
                "focus": decision.focus or "",
                "source": decision.source,
                "decision_confidence_0_1": decision.confidence_0_1,
                "transcript": (answer.transcript_corrected or answer.transcript_raw or "") if answer else "",
                "score_0_10": answer.score if answer else None,
                "analysis": (answer.llm_analysis or {}) if answer else {},
            })
        result.append({
            "root_question_id": root.id,
            "root_question": root.question_text,
            "competency": root.competency or "general",
            "root_transcript": (root_answer.transcript_corrected or root_answer.transcript_raw or "") if root_answer else "",
            "follow_up_count": len(follow_ups),
            "resolved_root_score_0_10": latest.resolved_root_score_0_10 if latest else (root_answer.score if root_answer else None),
            "follow_ups": follow_ups,
        })
    return result


@router.post("/api/interviews/{session_id}/complete", response_class=JSONResponse)
async def complete_interview(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    legacy_main._assert_link_live(session)
    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    if not answers:
        raise HTTPException(status_code=400, detail="Нельзя завершить интервью без ответов")

    for answer in answers:
        transcript = answer.transcript_corrected or answer.transcript_raw
        if transcript and (answer.score is None or "score_0_10" not in (answer.llm_analysis or {})):
            await _analyze_answer(answer, db)

    answers_data = [_answer_for_final(answer, db, index) for index, answer in enumerate(answers, 1)]
    report_data = await llm_service.generate_final_report(
        vacancy_title=session.vacancy.title,
        vacancy_requirements=session.vacancy.requirements or session.vacancy.description or "",
        answers_data=answers_data,
    )

    final_report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not final_report:
        final_report = FinalReport(session_id=session_id)
        db.add(final_report)
    final_report.overall_score = report_data["overall_score_0_10"]
    final_report.recommendation = report_data["recommendation"]
    final_report.summary = report_data["summary"]
    final_report.strengths = report_data["strengths"]
    final_report.weaknesses = report_data["issues"]
    final_report.detected_skills = report_data["competencies"]
    final_report.areas_to_check = report_data["uncovered_vacancy_topics"]
    final_report.risk_factors = {
        "confidence_0_1": report_data["confidence_0_1"],
        "vacancy_coverage": report_data["vacancy_coverage"],
    }
    final_report.generated_at = datetime.utcnow()
    session.status = "completed"
    session.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(final_report)
    return {
        "message": "Интервью завершено, отчёт сгенерирован",
        "report_id": final_report.id,
        "evaluation_schema": "v2",
    }


def _compat_points(items: list, field: str) -> list[str]:
    result = []
    for item in items or []:
        if isinstance(item, dict):
            value = item.get(field)
        else:
            value = item
        if isinstance(value, str) and value.strip():
            result.append(value.strip())
    return result


@router.get("/api/reports/{session_id}", response_class=JSONResponse)
async def get_report(
    session_id: int,
    current_user=Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    session = legacy_main._get_accessible_session(session_id, current_user, db)
    report = session.final_report
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    full_video = legacy_main._find_full_video(session_id)
    full_video_meta = legacy_main.media_metadata(str(full_video) if full_video else None)

    details = report.risk_factors if isinstance(report.risk_factors, dict) else {}
    competencies = report.detected_skills if isinstance(report.detected_skills, list) else []
    strengths = report.strengths if isinstance(report.strengths, list) else []
    issues = report.weaknesses if isinstance(report.weaknesses, list) else []
    uncovered = report.areas_to_check if isinstance(report.areas_to_check, list) else []
    coverage = details.get("vacancy_coverage", {"must_have": [], "nice_to_have": []})
    confidence = details.get("confidence_0_1", 0.0)
    final_evaluation = {
        "recommendation": report.recommendation,
        "overall_score_0_10": report.overall_score,
        "confidence_0_1": confidence,
        "summary": report.summary or "",
        "competencies": competencies,
        "vacancy_coverage": coverage,
        "strengths": strengths,
        "issues": issues,
        "uncovered_vacancy_topics": uncovered,
    }

    compat_strengths = _compat_points(strengths, "point")
    compat_issues = _compat_points(issues, "point")
    compat_skills = _compat_points(competencies, "name")
    compat_risks = [
        item.get("point")
        for item in issues
        if isinstance(item, dict) and item.get("type") in {"риск", "противоречие"} and item.get("point")
    ]
    answer_payloads = []
    for answer in answers:
        meta = _adaptive_answer_meta(answer, db)
        answer_payloads.append({
            "id": answer.id,
            "question": answer.question_text,
            "transcript": answer.transcript_corrected or answer.transcript_raw,
            "transcript_raw": answer.transcript_raw,
            "score": answer.score,
            "is_follow_up": meta["is_follow_up"],
            "root_question_id": meta["root_question_id"],
            "follow_up_index": meta["follow_up_index"],
            "probe_reason": meta["probe_reason"],
            "probe_focus": meta["probe_focus"],
            "probe_source": meta["probe_source"],
            "audio_path": legacy_main._web_upload_path(answer.audio_path),
            "video_path": legacy_main._web_upload_path(answer.video_path),
            "audio_media": legacy_main.media_metadata(answer.audio_path, answer.media.audio_duration_ms if answer.media else None),
            "video_media": legacy_main.media_metadata(answer.video_path, answer.media.video_duration_ms if answer.media else None),
            "start_ms": answer.media.start_ms if answer.media else None,
            "end_ms": answer.media.end_ms if answer.media else None,
            "analysis": answer.llm_analysis,
        })
    # Непройденные корневые вопросы: активные, не сгенерированные follow-up, без
    # подтверждённого ответа. Иначе досрочно завершённое интервью выглядит как
    # полное — рекрутер не отличит «ответил плохо» от «не отвечал».
    generated_follow_up_ids = {
        row[0]
        for row in db.query(AdaptiveProbeDecision.follow_up_question_id)
        .filter(
            AdaptiveProbeDecision.session_id == session_id,
            AdaptiveProbeDecision.follow_up_question_id.is_not(None),
        )
        .all()
    }
    answered_ids = {
        link.interview_question_id
        for link in db.query(AnswerQuestionLink)
        .join(Answer, Answer.id == AnswerQuestionLink.answer_id)
        .filter(Answer.session_id == session_id, Answer.is_approved_by_candidate.is_(True))
        .all()
    }
    unanswered_questions = [
        {"question_id": q.id, "question": q.question_text, "competency": q.competency}
        for q in db.query(InterviewQuestion)
        .filter(InterviewQuestion.session_id == session_id, InterviewQuestion.is_active.is_(True))
        .order_by(InterviewQuestion.order_index, InterviewQuestion.id)
        .all()
        if q.id not in generated_follow_up_ids and q.id not in answered_ids
    ]

    return {
        "id": report.id,
        "session_id": report.session_id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "vacancy_text": session.vacancy.description or "",
        "overall_score": report.overall_score,
        "recommendation": report.recommendation,
        "summary": report.summary,
        "strengths": compat_strengths,
        "weaknesses": compat_issues,
        "detected_skills": compat_skills,
        "areas_to_check": uncovered,
        "risk_factors": compat_risks,
        "score_confidence": confidence,
        "vacancy_coverage": coverage,
        "final_evaluation": final_evaluation,
        "unanswered_questions": unanswered_questions,
        "adaptive_follow_ups": _adaptive_follow_up_report(session_id, db),
        "full_video_path": legacy_main._web_upload_path(str(full_video)) if full_video else None,
        "full_video_media": full_video_meta,
        "answers": answer_payloads,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "workflow_state": legacy_main._workflow_state(session),
        "lifecycle_status": session.lifecycle.status if session.lifecycle else "active",
        "lifecycle_note": session.lifecycle.note if session.lifecycle else "",
        "hr_review": legacy_main._review_payload(legacy_main._latest_review(session, "hr")),
        "manager_review": legacy_main._review_payload(legacy_main._latest_review(session, "hiring_manager")),
        "viewer_role": current_user.role,
    }