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
from database import Answer, FinalReport, InterviewQuestion, InterviewSession, SessionQuestion, get_db
from services import llm_service


router = APIRouter()


async def _analyze_answer(answer: Answer, db: Session) -> None:
    iq = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.session_id == answer.session_id,
            InterviewQuestion.question_text == answer.question_text,
        )
        .first()
    )
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


def _answer_for_final(answer: Answer, db: Session, index: int) -> dict:
    iq = (
        db.query(InterviewQuestion)
        .filter(
            InterviewQuestion.session_id == answer.session_id,
            InterviewQuestion.question_text == answer.question_text,
        )
        .first()
    )
    sq = db.query(SessionQuestion).filter(SessionQuestion.id == answer.session_question_id).first() if not iq else None
    q = sq.question if sq else None
    evaluation = answer.llm_analysis or {}
    return {
        "question_id": str(iq.id if iq else (q.id if q else index)),
        "question_text": answer.question_text or (iq.question_text if iq else (q.question_text if q else "")),
        "competency": (iq.competency if iq else (q.competency if q else "general")) or "general",
        "transcript": answer.transcript_corrected or answer.transcript_raw or "",
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


@router.post("/api/interviews/{session_id}/complete", response_class=JSONResponse)
async def complete_interview(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
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

    # Keep the old top-level shape string-based so the existing report.html and
    # any current consumers do not break. Rich v2 data lives in final_evaluation.
    compat_strengths = _compat_points(strengths, "point")
    compat_issues = _compat_points(issues, "point")
    compat_skills = _compat_points(competencies, "name")
    compat_risks = [
        item.get("point")
        for item in issues
        if isinstance(item, dict) and item.get("type") in {"риск", "противоречие"} and item.get("point")
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
        "full_video_path": legacy_main._web_upload_path(str(full_video)) if full_video else None,
        "full_video_media": full_video_meta,
        "answers": [{
            "id": answer.id,
            "question": answer.question_text,
            "transcript": answer.transcript_corrected or answer.transcript_raw,
            "transcript_raw": answer.transcript_raw,
            "score": answer.score,
            "audio_path": legacy_main._web_upload_path(answer.audio_path),
            "video_path": legacy_main._web_upload_path(answer.video_path),
            "audio_media": legacy_main.media_metadata(answer.audio_path, answer.media.audio_duration_ms if answer.media else None),
            "video_media": legacy_main.media_metadata(answer.video_path, answer.media.video_duration_ms if answer.media else None),
            "start_ms": answer.media.start_ms if answer.media else None,
            "end_ms": answer.media.end_ms if answer.media else None,
            "analysis": answer.llm_analysis,
        } for answer in answers],
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "workflow_state": legacy_main._workflow_state(session),
        "lifecycle_status": session.lifecycle.status if session.lifecycle else "active",
        "lifecycle_note": session.lifecycle.note if session.lifecycle else "",
        "hr_review": legacy_main._review_payload(legacy_main._latest_review(session, "hr")),
        "manager_review": legacy_main._review_payload(legacy_main._latest_review(session, "hiring_manager")),
        "viewer_role": current_user.role,
    }
