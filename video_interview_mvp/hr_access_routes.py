"""Canonical HR lifecycle route with review-hierarchy guardrails."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

import legacy_main
from database import User, get_db

router = APIRouter()


@router.patch("/api/candidates/{session_id}/status", response_class=JSONResponse)
async def update_candidate_status(
    session_id: int,
    payload: legacy_main.CandidateStatusUpdate,
    current_user: User = Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять HR-статус кандидата")

    session = legacy_main._get_accessible_session(session_id, current_user, db)
    allowed = {"active", "hold", "rejected"}
    if payload.status == "hired":
        raise HTTPException(
            status_code=403,
            detail="Статус «Нанят» выставляется только после финального одобрения нанимающего менеджера",
        )
    if payload.status not in allowed:
        raise HTTPException(status_code=400, detail="Допустимые HR-статусы: active, hold, rejected")

    manager_review = legacy_main._latest_review(session, "hiring_manager")
    if manager_review:
        final_status = "hired" if manager_review.decision == "approve" else "rejected"
        if payload.status != final_status:
            raise HTTPException(
                status_code=409,
                detail="После финального решения менеджера HR-статус фиксируется автоматически",
            )

    lifecycle = legacy_main._ensure_lifecycle(session, db)
    lifecycle.status = payload.status
    lifecycle.note = (payload.note or "").strip()
    lifecycle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return {"message": "HR-статус кандидата сохранён", "candidate": legacy_main._session_payload(session)}
