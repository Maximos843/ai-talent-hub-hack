"""Editable question-bank API and DB-backed bank snapshot for vacancy suggestions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import database
import legacy_main
from adaptive_models import QuestionProbeConfig
from database import Question, User, get_db


BASE_DIR = Path(__file__).resolve().parent
QUESTIONS_FILE = BASE_DIR / "data" / "questions.json"
router = APIRouter()


class QuestionCreate(BaseModel):
    question: str
    tags: List[str] = Field(default_factory=list)
    competency: str = "general"
    reference_answer: str = ""
    must_have: List[str] = Field(default_factory=list)
    nice_to_have: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)
    possible_extra_questions: List[str] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    question: Optional[str] = None
    tags: Optional[List[str]] = None
    competency: Optional[str] = None
    reference_answer: Optional[str] = None
    must_have: Optional[List[str]] = None
    nice_to_have: Optional[List[str]] = None
    red_flags: Optional[List[str]] = None
    possible_extra_questions: Optional[List[str]] = None


def _clean_list(values: List[str]) -> List[str]:
    result = []
    for value in values or []:
        item = str(value).strip()
        if item and item not in result:
            result.append(item)
    return result


def _probe_config(question_id: int, db: Session) -> Optional[QuestionProbeConfig]:
    return db.query(QuestionProbeConfig).filter(QuestionProbeConfig.question_id == question_id).first()


def _payload(question: Question, db: Session) -> dict:
    config = _probe_config(question.id, db)
    return {
        "bank_id": str(question.id),
        "database_id": question.id,
        "question": question.question_text,
        "tags": question.tags or [],
        "competency": question.competency or "general",
        "reference_answer": question.reference_answer or "",
        "must_have": question.must_have or [],
        "nice_to_have": question.nice_to_have or [],
        "red_flags": question.red_flags or [],
        "possible_extra_questions": config.possible_extra_questions if config else [],
        "usage_count": len(question.session_questions or []),
    }


def ensure_question_bank_seeded() -> None:
    """Import bundled questions and backfill follow-up hints without overwriting HR edits."""
    if not QUESTIONS_FILE.exists():
        return
    try:
        seed = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    db = database.SessionLocal()
    try:
        by_text = {q.question_text: q for q in db.query(Question).all()}
        changed = False
        for item in seed:
            text = str(item.get("question", "")).strip()
            if not text:
                continue
            question = by_text.get(text)
            if not question:
                question = Question(
                    question_text=text,
                    tags=_clean_list(item.get("tags", [])),
                    competency=str(item.get("competency", "general")).strip() or "general",
                    reference_answer=str(item.get("reference_answer", "")),
                    must_have=_clean_list(item.get("must_have", [])),
                    nice_to_have=_clean_list(item.get("nice_to_have", [])),
                    red_flags=_clean_list(item.get("red_flags", [])),
                )
                db.add(question)
                db.flush()
                by_text[text] = question
                changed = True
            if not _probe_config(question.id, db):
                db.add(
                    QuestionProbeConfig(
                        question_id=question.id,
                        possible_extra_questions=_clean_list(item.get("possible_extra_questions", [])),
                    )
                )
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def load_question_bank_snapshot() -> List[dict]:
    """Compatibility hook used by vacancy creation; DB is source of truth."""
    ensure_question_bank_seeded()
    db = database.SessionLocal()
    try:
        result = []
        for q in db.query(Question).order_by(Question.competency, Question.id).all():
            config = _probe_config(q.id, db)
            result.append(
                {
                    "id": str(q.id),
                    "question": q.question_text,
                    "tags": q.tags or [],
                    "competency": q.competency or "general",
                    "reference_answer": q.reference_answer or "",
                    "must_have": q.must_have or [],
                    "nice_to_have": q.nice_to_have or [],
                    "red_flags": q.red_flags or [],
                    "possible_extra_questions": config.possible_extra_questions if config else [],
                }
            )
        return result
    finally:
        db.close()


def _require_hr(user: User = Depends(legacy_main.get_current_user)) -> User:
    if user.role != "hr":
        raise HTTPException(status_code=403, detail="Банк вопросов доступен для редактирования только HR")
    return user


@router.get("/api/questions")
def get_questions(
    q: str = Query(""),
    tag: str = Query(""),
    competency: str = Query(""),
    user: User = Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    ensure_question_bank_seeded()
    needle = q.strip().lower()
    tag_value = tag.strip().lower()
    competency_value = competency.strip().lower()
    result = []
    for question in db.query(Question).order_by(Question.competency, Question.id).all():
        payload = _payload(question, db)
        haystack = " ".join([
            payload["question"], payload["competency"], " ".join(payload["tags"]),
            payload["reference_answer"], " ".join(payload["must_have"]),
            " ".join(payload["nice_to_have"]), " ".join(payload["red_flags"]),
            " ".join(payload["possible_extra_questions"]),
        ]).lower()
        if needle and needle not in haystack:
            continue
        if tag_value and tag_value not in {str(x).lower() for x in payload["tags"]}:
            continue
        if competency_value and payload["competency"].lower() != competency_value:
            continue
        result.append(payload)
    return result


@router.get("/api/questions/meta")
def question_meta(
    user: User = Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    ensure_question_bank_seeded()
    questions = db.query(Question).all()
    tags = sorted({str(tag) for question in questions for tag in (question.tags or []) if str(tag).strip()})
    competencies = sorted({question.competency or "general" for question in questions})
    return {"tags": tags, "competencies": competencies, "count": len(questions)}


@router.post("/api/questions")
def create_question(
    payload: QuestionCreate,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    text = payload.question.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Введите текст вопроса")
    if db.query(Question).filter(Question.question_text == text).first():
        raise HTTPException(status_code=400, detail="Такой вопрос уже есть в банке")
    question = Question(
        question_text=text,
        tags=_clean_list(payload.tags),
        competency=payload.competency.strip() or "general",
        reference_answer=payload.reference_answer.strip(),
        must_have=_clean_list(payload.must_have),
        nice_to_have=_clean_list(payload.nice_to_have),
        red_flags=_clean_list(payload.red_flags),
    )
    db.add(question)
    db.flush()
    db.add(
        QuestionProbeConfig(
            question_id=question.id,
            possible_extra_questions=_clean_list(payload.possible_extra_questions),
        )
    )
    db.commit()
    db.refresh(question)
    return _payload(question, db)


@router.patch("/api/questions/{question_id}")
def update_question(
    question_id: int,
    payload: QuestionUpdate,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    if payload.question is not None:
        text = payload.question.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Текст вопроса не может быть пустым")
        duplicate = db.query(Question).filter(Question.question_text == text, Question.id != question_id).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Такой вопрос уже есть в банке")
        question.question_text = text
    if payload.tags is not None:
        question.tags = _clean_list(payload.tags)
    if payload.competency is not None:
        question.competency = payload.competency.strip() or "general"
    if payload.reference_answer is not None:
        question.reference_answer = payload.reference_answer.strip()
    if payload.must_have is not None:
        question.must_have = _clean_list(payload.must_have)
    if payload.nice_to_have is not None:
        question.nice_to_have = _clean_list(payload.nice_to_have)
    if payload.red_flags is not None:
        question.red_flags = _clean_list(payload.red_flags)
    if payload.possible_extra_questions is not None:
        config = _probe_config(question.id, db)
        if not config:
            config = QuestionProbeConfig(question_id=question.id)
            db.add(config)
        config.possible_extra_questions = _clean_list(payload.possible_extra_questions)
    db.commit()
    db.refresh(question)
    return _payload(question, db)


ensure_question_bank_seeded()