"""API рабочего места рекрутера: доска вакансий и канбан кандидатов.

Ключевое решение — воронка кандидата вычисляется в одном месте. В базе статус
размазан по трём независимым источникам (``session.status``, вычисляемый
``workflow_state`` и ручной ``lifecycle``), и карточка канбана обязана знать
ровно одну колонку. Здесь они схлопываются, а ручной статус HR имеет приоритет
над автоматикой.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import legacy_main
from database import InterviewSession, User, Vacancy, get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# Колонки канбана в порядке движения кандидата по воронке.
BOARD_COLUMNS = [
    ("applied", "Новые", "Кандидат заведён, ссылку ещё не отправляли"),
    ("invited", "Приглашены", "Ссылка отправлена, ждём прохождения интервью"),
    ("interviewed", "Прошли интервью", "Оценка готова, нужен вердикт рекрутера"),
    ("advanced", "Продвинуты", "Переданы дальше по воронке"),
    ("rejected", "Отклонены", "Отказ на любом этапе"),
]
VACANCY_STATUSES = {"draft", "active", "closed"}


def _require_hr(user: User = Depends(legacy_main.get_current_user)) -> User:
    if user.role != "hr":
        raise HTTPException(status_code=403, detail="Рабочее место доступно только HR")
    return user


def _stage(session: InterviewSession) -> str:
    """Единственная точка правды о том, в какой колонке живёт кандидат."""
    lifecycle = session.lifecycle.status if session.lifecycle else "active"
    # Ручное решение HR перебивает автоматику: рекрутер перетащил карточку — так и есть.
    if lifecycle == "rejected":
        return "rejected"
    if lifecycle == "hired":
        return "advanced"

    state = legacy_main._workflow_state(session)
    if state in {"manager_approved", "hr_approved"}:
        return "advanced"
    if state in {"manager_rejected", "hr_rejected"}:
        return "rejected"
    if state in {"completed", "awaiting_hr", "awaiting_manager"}:
        return "interviewed"
    if session.invited_at:
        return "invited"
    return "applied"


def _vacancy_status(vacancy: Vacancy, approved_count: int) -> str:
    """Черновик определяется фактом утверждения вопросов, а не только полем."""
    stored = (vacancy.status or "draft").strip()
    if stored == "closed":
        return "closed"
    return "active" if approved_count > 0 else "draft"


def _waiting_on(session: InterviewSession, stage: str) -> Optional[str]:
    """Чей сейчас ход. В Greenhouse и Ashby именно это, а не счётчики,
    делает доску рабочей: красный — ждём команду, серый — ждём кандидата."""
    if stage == "applied":
        return "recruiter"  # ссылка ещё не отправлена
    if stage == "invited":
        return "candidate"
    if stage == "interviewed":
        return "manager" if legacy_main._workflow_state(session) == "awaiting_manager" else "recruiter"
    return None


def _stage_entered_at(session: InterviewSession, stage: str) -> Optional[datetime]:
    """Момент попадания в текущую колонку — из него считаются дни в этапе."""
    if stage == "invited":
        return session.invited_at
    if stage == "interviewed":
        return session.completed_at or session.invited_at
    if stage in {"advanced", "rejected"} and session.lifecycle:
        return session.lifecycle.updated_at
    return session.created_at


def _candidate_card(session: InterviewSession) -> dict:
    profile = getattr(session, "profile", None)
    report = session.final_report
    stage = _stage(session)
    entered = _stage_entered_at(session, stage)
    days_in_stage = (datetime.utcnow() - entered).days if entered else None
    return {
        "id": session.id,
        "name": session.candidate_name,
        "stage": stage,
        "waiting_on": _waiting_on(session, stage),
        "days_in_stage": days_in_stage,
        "workflow_state": legacy_main._workflow_state(session),
        "lifecycle_status": session.lifecycle.status if session.lifecycle else "active",
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "invited_at": session.invited_at.isoformat() if session.invited_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
        "interview_url": f"/interview/{session.session_token}",
        "overall_score": report.overall_score if report else None,
        "recommendation": report.recommendation if report else None,
        "has_report": report is not None,
        "email": profile.email if profile else None,
        "telegram_username": profile.telegram_username if profile else None,
        "telegram_linked": bool(profile and profile.telegram_chat_id),
        "resume_filename": profile.resume_filename if profile else None,
        "match_score": profile.match_score if profile else None,
        "match_summary": profile.match_summary if profile else None,
        "question_count": len(session.interview_questions),
    }


def _owned_vacancy(vacancy_id: int, user: User, db: Session) -> Vacancy:
    vacancy = db.query(Vacancy).filter(Vacancy.id == vacancy_id).first()
    if not vacancy or vacancy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    return vacancy


@router.get("/vacancies")
async def list_vacancies(user: User = Depends(_require_hr), db: Session = Depends(get_db)):
    """Карточки вакансий со счётчиками по колонкам канбана."""
    vacancies = (
        db.query(Vacancy)
        .filter(Vacancy.owner_id == user.id)
        .order_by(Vacancy.created_at.desc())
        .all()
    )
    result = []
    for vacancy in vacancies:
        approved = sum(1 for item in vacancy.session_questions if item.is_approved)
        counts = {key: 0 for key, _, _ in BOARD_COLUMNS}
        for session in vacancy.interview_sessions:
            counts[_stage(session)] += 1
        result.append(
            {
                "id": vacancy.id,
                "title": vacancy.title,
                "grade": vacancy.grade,
                "status": _vacancy_status(vacancy, approved),
                "detected_tags": vacancy.detected_tags or [],
                "created_at": vacancy.created_at.isoformat() if vacancy.created_at else None,
                "closed_at": vacancy.closed_at.isoformat() if vacancy.closed_at else None,
                "questions_count": len(vacancy.session_questions),
                "approved_questions_count": approved,
                "candidates_total": len(vacancy.interview_sessions),
                "stage_counts": counts,
            }
        )
    return result


class VacancyStatusUpdate(BaseModel):
    status: str


@router.patch("/vacancies/{vacancy_id}/status")
async def set_vacancy_status(
    vacancy_id: int,
    payload: VacancyStatusUpdate,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    vacancy = _owned_vacancy(vacancy_id, user, db)
    if payload.status not in VACANCY_STATUSES:
        raise HTTPException(status_code=400, detail="Допустимые статусы: draft, active, closed")
    approved = sum(1 for item in vacancy.session_questions if item.is_approved)
    if payload.status == "active" and approved == 0:
        raise HTTPException(status_code=400, detail="Сначала утвердите пул вопросов — иначе ссылку выдать нельзя")
    vacancy.status = payload.status
    vacancy.closed_at = datetime.utcnow() if payload.status == "closed" else None
    vacancy.is_active = payload.status != "closed"
    db.commit()
    return {"id": vacancy.id, "status": _vacancy_status(vacancy, approved)}


@router.get("/vacancies/{vacancy_id}/board")
async def vacancy_board(
    vacancy_id: int,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    vacancy = _owned_vacancy(vacancy_id, user, db)
    approved = sum(1 for item in vacancy.session_questions if item.is_approved)
    cards = [_candidate_card(session) for session in vacancy.interview_sessions]
    columns = [
        {
            "key": key,
            "title": title,
            "hint": hint,
            "candidates": [card for card in cards if card["stage"] == key],
        }
        for key, title, hint in BOARD_COLUMNS
    ]
    profile = getattr(vacancy, "profile", None)
    scored = [card["overall_score"] for card in cards if card["overall_score"] is not None]
    invited = [card for card in cards if card["invited_at"]]

    return {
        "vacancy": {
            "id": vacancy.id,
            "title": vacancy.title,
            "grade": vacancy.grade,
            "status": _vacancy_status(vacancy, approved),
            "detected_tags": vacancy.detected_tags or [],
            "vacancy_text": vacancy.description or "",
            "created_at": vacancy.created_at.isoformat() if vacancy.created_at else None,
            "closed_at": vacancy.closed_at.isoformat() if vacancy.closed_at else None,
            "questions_count": len(vacancy.session_questions),
            "approved_questions_count": approved,
            "summary": (profile.summary if profile else "") or "",
            "must_have": (profile.must_have if profile else None) or [],
            "nice_to_have": (profile.nice_to_have if profile else None) or [],
            "stop_factors": (profile.stop_factors if profile else None) or [],
            "responsibilities": (profile.responsibilities if profile else None) or [],
        },
        "stats": _board_stats(cards, invited, scored),
        "columns": columns,
    }


def _board_stats(cards: list[dict], invited: list[dict], scored: list[float]) -> dict:
    """Статистика воронки по вакансии.

    Считаем от приглашённых, а не от всех заведённых: кандидат, которому ещё не
    отправили ссылку, не может «не дойти» до конца интервью — иначе completion
    rate занижался бы каждым свежим добавлением в первую колонку.
    """
    completed = [card for card in cards if card["has_report"]]
    decided = [card for card in cards if card["stage"] in {"advanced", "rejected"}]
    advanced = [card for card in cards if card["stage"] == "advanced"]

    def days_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
        if not start or not end:
            return None
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 86400

    lags = [
        value
        for value in (days_between(card["invited_at"], card["completed_at"]) for card in completed)
        if value is not None
    ]

    return {
        "total": len(cards),
        "invited": len(invited),
        "completed": len(completed),
        "decided": len(decided),
        "advanced": len(advanced),
        # Доля дошедших до конца среди тех, кому реально отправили ссылку.
        "completion_rate": round(len(completed) / len(invited), 2) if invited else None,
        # Доля прошедших дальше среди тех, по кому вердикт уже вынесен.
        "pass_rate": round(len(advanced) / len(decided), 2) if decided else None,
        "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
        # Медиана лага «отправили ссылку → интервью завершено», в днях.
        "median_days_to_complete": round(sorted(lags)[len(lags) // 2], 1) if lags else None,
        "awaiting_decision": sum(1 for card in cards if card["stage"] == "interviewed"),
    }


@router.post("/candidates/{session_id}/invite")
async def mark_invited(
    session_id: int,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Фиксирует факт отправки ссылки — это и переводит карточку во вторую колонку."""
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session or session.vacancy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    approved = sum(1 for item in session.vacancy.session_questions if item.is_approved)
    if approved == 0:
        raise HTTPException(status_code=400, detail="Сначала утвердите пул вопросов вакансии")
    if not session.invited_at:
        session.invited_at = datetime.utcnow()
        db.commit()
        db.refresh(session)
    return {"candidate": _candidate_card(session), "interview_url": f"/interview/{session.session_token}"}


class StageUpdate(BaseModel):
    stage: str
    note: Optional[str] = ""


@router.patch("/candidates/{session_id}/stage")
async def move_candidate(
    session_id: int,
    payload: StageUpdate,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Ручной перенос карточки. Пишем в lifecycle — он перебивает автоматику."""
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session or session.vacancy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Кандидат не найден")

    valid = {key for key, _, _ in BOARD_COLUMNS}
    if payload.stage not in valid:
        raise HTTPException(status_code=400, detail=f"Допустимые колонки: {', '.join(sorted(valid))}")

    lifecycle = legacy_main._ensure_lifecycle(session, db)
    if payload.stage == "rejected":
        lifecycle.status = "rejected"
    elif payload.stage == "advanced":
        lifecycle.status = "hired"
    else:
        # Возврат в рабочие колонки снимает ручной override и отдаёт карточку автоматике.
        lifecycle.status = "active"
        if payload.stage == "applied":
            session.invited_at = None
        elif payload.stage == "invited" and not session.invited_at:
            session.invited_at = datetime.utcnow()
    lifecycle.note = (payload.note or "").strip()
    lifecycle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return {"candidate": _candidate_card(session)}


# --------------------------------------------------------------------------
# Мастер создания вакансии и приём резюме
# --------------------------------------------------------------------------
import asyncio
import uuid
from pathlib import Path

from fastapi import File, Form, UploadFile

from config import UPLOAD_DIR
from database import CandidateLifecycle, Question, SessionQuestion
from services import llm_service
from adaptive_models import QuestionProbeConfig
from services.document_service import (
    DocumentError,
    enrich_question,
    extract_text,
    generate_questions,
    match_resume,
    parse_vacancy,
)
from workspace_models import CandidateProfile, VacancyProfile

RESUME_DIR = Path(UPLOAD_DIR) / "resumes"
RESUME_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _normalize_telegram(value: str) -> Optional[str]:
    """Приводит @ivan, https://t.me/ivan и ivan к одному виду."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix):]
            break
    cleaned = cleaned.split("?")[0].strip("/ ")
    return cleaned[:64] or None


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    payload = await file.read()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 10 МБ")
    if not payload:
        raise HTTPException(status_code=400, detail="Файл пустой")
    return payload, file.filename or "document"


@router.post("/vacancies/parse")
async def parse_vacancy_document(
    file: Optional[UploadFile] = File(None),
    vacancy_text: str = Form(""),
    _: User = Depends(_require_hr),
):
    """Шаг 1 мастера: PDF или текст на вход, структура требований на выход."""
    text = vacancy_text.strip()
    source_filename = ""
    if file is not None:
        payload, source_filename = await _read_upload(file)
        try:
            text = extract_text(payload, source_filename)
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(text) < 40:
        raise HTTPException(status_code=400, detail="Слишком короткий текст вакансии — нужно хотя бы описание требований")

    parsed = await parse_vacancy(text)
    parsed["vacancy_text"] = text
    parsed["source_filename"] = source_filename
    parsed["demo_mode"] = not bool(llm_service.api_key)
    return parsed


class VacancyDraft(BaseModel):
    title: str
    grade: str = "middle"
    vacancy_text: str
    summary: str = ""
    source_filename: str = ""
    must_have: List[dict] = []
    nice_to_have: List[dict] = []
    responsibilities: List[str] = []
    stop_factors: List[str] = []
    tags: List[str] = []


@router.post("/vacancies")
async def create_vacancy_from_draft(
    draft: VacancyDraft,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Шаг 3 мастера: сохраняем вакансию, разбор и предложенный пул вопросов."""
    title = draft.title.strip()
    text = draft.vacancy_text.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Укажите название вакансии")
    if not text:
        raise HTTPException(status_code=400, detail="Текст вакансии пустой")

    # Теги из разбора LLM дополняются словарным матчером — он ловит то,
    # что модель могла пропустить, и наоборот.
    keyword_tags = await llm_service.extract_tags_from_vacancy(text, text)
    tags = list(dict.fromkeys([*(tag.lower() for tag in draft.tags), *keyword_tags]))

    vacancy = Vacancy(
        title=title,
        description=text,
        requirements=text,
        grade=(draft.grade or "middle").lower(),
        detected_tags=tags,
        owner_id=user.id,
        status="draft",
    )
    db.add(vacancy)
    db.flush()

    # SQLite переиспользует освободившиеся id, поэтому на новом vacancy_id может
    # уже лежать разбор от удалённой вакансии. Снимаем это явно, а не полагаемся
    # на то, что каскад отработал при удалении.
    db.query(VacancyProfile).filter(VacancyProfile.vacancy_id == vacancy.id).delete()
    db.add(
        VacancyProfile(
            vacancy_id=vacancy.id,
            source_filename=draft.source_filename or None,
            must_have=draft.must_have,
            nice_to_have=draft.nice_to_have,
            stop_factors=draft.stop_factors,
            responsibilities=draft.responsibilities,
            summary=draft.summary,
        )
    )

    bank = legacy_main._load_question_bank()
    suggested = _relevant_bank_questions(bank, draft.must_have, tags)

    # Гибридная схема из рамки продукта: банк закрывает то, что умеет, а
    # оставшиеся навыки LLM достраивает. Иначе редкий стек остаётся
    # непроверенным, и промах по нему не отличить от зоны роста.
    picked_tags = {str(tag).lower() for question in suggested for tag in (question.get("tags") or [])}
    picked_tags |= {str(question.get("competency") or "").lower() for question in suggested}
    requested = [item["skill"].lower() for item in draft.must_have if item.get("skill")] or tags
    uncovered = [skill for skill in dict.fromkeys(requested) if skill not in picked_tags]
    generated: List[dict] = []
    if uncovered:
        try:
            generated = await asyncio.wait_for(
                generate_questions(text, vacancy.grade, uncovered, limit=6), timeout=120
            )
        except Exception as exc:
            # Достройка не должна ронять создание вакансии: банк уже что-то дал,
            # а недостающие вопросы рекрутер может добавить руками.
            logger.warning("Не удалось сгенерировать вопросы под %s: %s", uncovered, exc)

    if not suggested and not generated and bank:
        suggested = bank[: legacy_main.MAX_QUESTIONS_PER_INTERVIEW]

    for index, item in enumerate([*suggested, *generated]):
        question = db.query(Question).filter(Question.question_text == item["question"]).first()
        if not question:
            question = Question(
                question_text=item["question"],
                tags=item.get("tags", []),
                competency=item.get("competency", ""),
                reference_answer=item.get("reference_answer", ""),
                must_have=item.get("must_have", []),
                nice_to_have=item.get("nice_to_have", []),
                red_flags=item.get("red_flags", []),
            )
            db.add(question)
            db.flush()
        # Уточняющие вопросы едут вместе с вопросом, иначе у сгенерированных
        # не будет подсказок для адаптивной части интервью.
        extras = item.get("possible_extra_questions") or []
        if extras and not db.query(QuestionProbeConfig).filter(QuestionProbeConfig.question_id == question.id).first():
            db.add(QuestionProbeConfig(question_id=question.id, possible_extra_questions=extras))
        db.add(SessionQuestion(vacancy_id=vacancy.id, question_id=question.id, order_index=index, is_approved=False))

    db.commit()
    db.refresh(vacancy)
    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "status": "draft",
        "suggested_questions_count": len(suggested) + len(generated),
        "from_bank": len(suggested),
        "generated": len(generated),
    }


BANK_SUGGESTION_LIMIT = 6


def _relevant_bank_questions(bank: list[dict], must_have: List[dict], tags: List[str]) -> List[dict]:
    """Отбирает из банка только вопросы, реально относящиеся к вакансии.

    Штатный подборщик берёт всё, где совпал хотя бы один тег. На вакансию по
    React это притаскивало вопросы про Spring, потому что общий тег «backend»
    находился и там и там. Поэтому требуем совпадения по названному навыку, а
    не по служебному тегу из словаря.
    """
    skills = {str(item.get("skill", "")).strip().lower() for item in must_have if item.get("skill")}
    skills |= {tag.strip().lower() for tag in tags}
    skills.discard("")
    if not skills:
        return bank[:BANK_SUGGESTION_LIMIT]

    scored: List[tuple[int, dict]] = []
    for question in bank:
        question_tags = {str(tag).lower() for tag in question.get("tags") or []}
        competency = str(question.get("competency") or "").lower()
        # Точное совпадение тега весомее, чем вхождение подстроки.
        exact = len(question_tags & skills)
        partial = sum(
            1
            for skill in skills
            for tag in question_tags
            if skill != tag and (skill in tag or tag in skill)
        )
        score = exact * 2 + partial + (2 if competency in skills else 0)
        if score >= 2:
            scored.append((score, question))

    scored.sort(key=lambda item: -item[0])
    return [question for _, question in scored[:BANK_SUGGESTION_LIMIT]]


@router.post("/vacancies/{vacancy_id}/candidates")
async def add_candidate(
    vacancy_id: int,
    candidate_name: str = Form(...),
    email: str = Form(""),
    telegram_username: str = Form(""),
    file: Optional[UploadFile] = File(None),
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Заводит кандидата в первую колонку. Резюме опционально, но если оно есть —
    сразу считаем соответствие вакансии, чтобы рекрутер видел приоритет."""
    vacancy = _owned_vacancy(vacancy_id, user, db)
    name = candidate_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя кандидата")
    approved = sum(1 for item in vacancy.session_questions if item.is_approved)
    if approved == 0:
        raise HTTPException(status_code=400, detail="Сначала утвердите пул вопросов вакансии")

    session = InterviewSession(
        vacancy_id=vacancy.id,
        candidate_name=name,
        session_token=str(uuid.uuid4()),
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=legacy_main.INTERVIEW_LINK_TTL_DAYS),
    )
    db.add(session)
    db.flush()
    db.add(CandidateLifecycle(session_id=session.id, status="active", note=""))
    db.commit()
    db.refresh(session)
    legacy_main._copy_default_questions_to_session(session, db)

    contacts = {
        "email": email.strip() or None,
        "telegram_username": _normalize_telegram(telegram_username),
    }

    if file is None:
        if any(contacts.values()):
            db.add(CandidateProfile(session_id=session.id, **contacts))
            db.commit()
            db.refresh(session)
        return {"candidate": _candidate_card(session)}

    if file is not None:
        payload, filename = await _read_upload(file)
        try:
            resume_text = extract_text(payload, filename)
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        stored = RESUME_DIR / f"{session.id}_{uuid.uuid4().hex[:8]}_{Path(filename).name}"
        stored.write_bytes(payload)

        profile = db.query(VacancyProfile).filter(VacancyProfile.vacancy_id == vacancy.id).first()
        must_have = (profile.must_have if profile else None) or []
        try:
            analysis = await asyncio.wait_for(
                match_resume(vacancy.description or "", must_have, resume_text), timeout=90
            )
        except Exception as exc:
            # Разбор резюме не должен ронять создание кандидата: карточка нужна
            # рекрутеру в любом случае, оценку можно пересчитать позже.
            logger.warning("Не удалось оценить резюме кандидата %s: %s", session.id, exc)
            analysis = {"match_score": None, "summary": "", "details": [], "parsed": {}}

        db.add(
            CandidateProfile(
                session_id=session.id,
                **contacts,
                resume_filename=Path(filename).name,
                resume_path=str(stored),
                resume_text=resume_text,
                parsed=analysis.get("parsed") or {},
                match_score=analysis.get("match_score"),
                match_summary=analysis.get("summary") or "",
                match_details=analysis.get("details") or [],
            )
        )
        db.commit()
        db.refresh(session)

    return {"candidate": _candidate_card(session)}


@router.get("/skills")
async def skills_library(_: User = Depends(_require_hr)):
    """Справочник навыков для конструктора вакансии.

    Источник — банк вопросов, и это осознанно: рекрутер сразу видит, какой навык
    интервью реально сможет проверить, а какой останется незакрытым. Это та же
    матрица «вопрос → компетенция», только на входе, а не на выходе.
    """
    bank = legacy_main._load_question_bank()
    by_skill: dict[str, dict] = {}
    for question in bank:
        competency = str(question.get("competency") or "").strip()
        for tag in question.get("tags") or []:
            key = str(tag).strip().lower()
            if not key:
                continue
            entry = by_skill.setdefault(key, {"skill": key, "questions": 0, "competencies": set()})
            entry["questions"] += 1
            if competency:
                entry["competencies"].add(competency)

    result = [
        {"skill": item["skill"], "questions": item["questions"], "competencies": sorted(item["competencies"])}
        for item in by_skill.values()
    ]
    result.sort(key=lambda item: (-item["questions"], item["skill"]))
    return result


class CustomQuestion(BaseModel):
    question: str


@router.post("/vacancies/{vacancy_id}/questions")
async def add_custom_question(
    vacancy_id: int,
    payload: CustomQuestion,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Свой вопрос рекрутера с достроенной рубрикой.

    Просто положить текст в список нельзя: пайплайн оценивает ответ по
    must-have сигналам и красным флагам, и без них вопрос не участвует в оценке.
    """
    vacancy = _owned_vacancy(vacancy_id, user, db)
    text = payload.question.strip()
    if len(text) < 10:
        raise HTTPException(status_code=400, detail="Вопрос слишком короткий")
    if len(text) > 600:
        raise HTTPException(status_code=400, detail="Вопрос длиннее 600 символов")

    profile = db.query(VacancyProfile).filter(VacancyProfile.vacancy_id == vacancy.id).first()
    skills = [item.get("skill", "") for item in (profile.must_have if profile else None) or []]
    try:
        enriched = await asyncio.wait_for(
            enrich_question(text, vacancy.description or "", vacancy.grade or "middle", skills),
            timeout=90,
        )
    except Exception as exc:
        # Рубрику всегда можно дописать руками, а вопрос терять нельзя.
        logger.warning("Не удалось достроить рубрику для вопроса: %s", exc)
        enriched = {
            "question": text,
            "original_question": text,
            "rewritten": False,
            "competency": "custom",
            "tags": [],
            "reference_answer": "",
            "must_have": [],
            "nice_to_have": [],
            "red_flags": [],
            "possible_extra_questions": [],
        }

    # Дубли проверяем по итоговой формулировке: модель могла привести к тому же
    # виду вопрос, который в вакансии уже есть.
    final_text = enriched["question"]
    existing = db.query(Question).filter(Question.question_text == final_text).first()
    if existing and any(item.question_id == existing.id for item in vacancy.session_questions):
        raise HTTPException(status_code=400, detail="Такой вопрос уже есть в этой вакансии")

    question = existing or Question(question_text=final_text)
    question.tags = enriched["tags"]
    question.competency = enriched["competency"]
    question.reference_answer = enriched["reference_answer"]
    question.must_have = enriched["must_have"]
    question.nice_to_have = enriched["nice_to_have"]
    question.red_flags = enriched["red_flags"]
    if not existing:
        db.add(question)
    db.flush()

    extras = enriched["possible_extra_questions"]
    if extras and not db.query(QuestionProbeConfig).filter(QuestionProbeConfig.question_id == question.id).first():
        db.add(QuestionProbeConfig(question_id=question.id, possible_extra_questions=extras))

    next_index = max((item.order_index or 0) for item in vacancy.session_questions) + 1 if vacancy.session_questions else 0
    db.add(SessionQuestion(vacancy_id=vacancy.id, question_id=question.id, order_index=next_index, is_approved=False))
    db.commit()

    return {
        "id": question.id,
        "session_question_id": next_index,
        "question": question.question_text,
        "original_question": enriched.get("original_question", text),
        "rewritten": enriched.get("rewritten", False),
        "competency": question.competency,
        "tags": question.tags or [],
        "reference_answer": question.reference_answer or "",
        "must_have": question.must_have or [],
        "nice_to_have": question.nice_to_have or [],
        "red_flags": question.red_flags or [],
        "possible_extra_questions": extras,
        "is_approved": False,
        "is_custom": True,
    }


class QuestionTextUpdate(BaseModel):
    question: str


@router.patch("/questions/{question_id}")
async def update_question_text(
    question_id: int,
    payload: QuestionTextUpdate,
    user: User = Depends(_require_hr),
    db: Session = Depends(get_db),
):
    """Правка формулировки вопроса — в том числе откат переформулировки."""
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")

    owned = (
        db.query(SessionQuestion)
        .join(Vacancy, Vacancy.id == SessionQuestion.vacancy_id)
        .filter(SessionQuestion.question_id == question_id, Vacancy.owner_id == user.id)
        .first()
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Вопрос не найден")

    text = payload.question.strip()
    if len(text) < 10:
        raise HTTPException(status_code=400, detail="Вопрос слишком короткий")
    if len(text) > 600:
        raise HTTPException(status_code=400, detail="Вопрос длиннее 600 символов")

    clash = db.query(Question).filter(Question.question_text == text, Question.id != question_id).first()
    if clash:
        # Такая формулировка уже существует отдельным вопросом — например, её
        # добавляли до появления переформулировки. Переименовывать нельзя, но
        # намерение рекрутера выполнимо: переводим вакансию на готовый вопрос.
        already_here = [
            item for item in db.query(SessionQuestion)
            .filter(SessionQuestion.vacancy_id == owned.vacancy_id, SessionQuestion.question_id == clash.id)
            .all()
        ]
        if already_here:
            # Обе формулировки уже в вакансии — оставляем ту, что была раньше.
            db.query(SessionQuestion).filter(
                SessionQuestion.vacancy_id == owned.vacancy_id,
                SessionQuestion.question_id == question_id,
            ).delete()
        else:
            db.query(SessionQuestion).filter(
                SessionQuestion.vacancy_id == owned.vacancy_id,
                SessionQuestion.question_id == question_id,
            ).update({"question_id": clash.id})
        db.commit()
        return {"id": clash.id, "question": clash.question_text, "replaced_id": question_id}

    question.question_text = text
    db.commit()
    return {"id": question.id, "question": question.question_text}


@router.get("/candidates")
async def all_candidates(user: User = Depends(_require_hr), db: Session = Depends(get_db)):
    """Сквозной список кандидатов по всем вакансиям рекрутера.

    Канбан отвечает на вопрос «что происходит по этой вакансии», а список — на
    другой: «где вообще все мои кандидаты и кто ждёт моего решения».
    """
    sessions = (
        db.query(InterviewSession)
        .join(Vacancy, Vacancy.id == InterviewSession.vacancy_id)
        .filter(Vacancy.owner_id == user.id)
        .order_by(InterviewSession.created_at.desc())
        .all()
    )
    items = []
    for session in sessions:
        card = _candidate_card(session)
        card["vacancy_id"] = session.vacancy_id
        card["vacancy_title"] = session.vacancy.title
        card["vacancy_grade"] = session.vacancy.grade
        items.append(card)

    return {
        "candidates": items,
        "vacancies": [
            {"id": vacancy.id, "title": vacancy.title}
            for vacancy in db.query(Vacancy).filter(Vacancy.owner_id == user.id).order_by(Vacancy.title).all()
        ],
        "counts": {
            "total": len(items),
            "waiting_recruiter": sum(1 for item in items if item["waiting_on"] == "recruiter"),
            "waiting_manager": sum(1 for item in items if item["waiting_on"] == "manager"),
            "waiting_candidate": sum(1 for item in items if item["waiting_on"] == "candidate"),
        },
    }


class QuestionDraft(BaseModel):
    question: str
    competency: str = ""


@router.post("/questions/draft")
async def draft_question_rubric(
    payload: QuestionDraft,
    _: User = Depends(_require_hr),
):
    """Черновик рубрики для банка: формулировка и критерии оценки, без сохранения.

    Тот же механизм, что и для своего вопроса в вакансии, но без её контекста —
    вопрос в банке общий и не должен быть привязан к конкретному стеку.
    """
    text = payload.question.strip()
    if len(text) < 10:
        raise HTTPException(status_code=400, detail="Вопрос слишком короткий")
    if len(text) > 600:
        raise HTTPException(status_code=400, detail="Вопрос длиннее 600 символов")
    try:
        return await asyncio.wait_for(
            enrich_question(text, "", "middle", [payload.competency] if payload.competency else []),
            timeout=90,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Модель не ответила вовремя, попробуйте ещё раз") from exc
    except Exception as exc:
        logger.warning("Черновик рубрики не собрался: %s", exc)
        raise HTTPException(status_code=502, detail="Не удалось собрать рубрику") from exc


@router.get("/manager/candidates")
async def manager_queue(
    user: User = Depends(legacy_main.get_current_user),
    db: Session = Depends(get_db),
):
    """Очередь нанимающего менеджера: только переданные ему кандидаты.

    Доступ к кандидату у менеджера появляется лишь после одобрения рекрутера,
    поэтому список и есть его рабочее место — искать по вакансиям ему незачем.
    """
    if user.role != "hiring_manager":
        raise HTTPException(status_code=403, detail="Раздел доступен нанимающему менеджеру")

    sessions = (
        db.query(InterviewSession)
        .join(Vacancy, Vacancy.id == InterviewSession.vacancy_id)
        .order_by(InterviewSession.completed_at.desc())
        .all()
    )
    items = []
    for session in sessions:
        if not legacy_main._manager_can_view(session) or not session.final_report:
            continue
        card = _candidate_card(session)
        card["vacancy_id"] = session.vacancy_id
        card["vacancy_title"] = session.vacancy.title
        card["vacancy_grade"] = session.vacancy.grade
        card["summary"] = session.final_report.summary or ""
        hr = legacy_main._latest_review(session, "hr")
        manager = legacy_main._latest_review(session, "hiring_manager")
        card["hr_comment"] = hr.comment if hr else ""
        card["hr_reviewer"] = hr.reviewer.full_name or hr.reviewer.username if hr and hr.reviewer else ""
        card["decided"] = bool(manager)
        card["manager_decision"] = manager.decision if manager else None
        items.append(card)

    pending = [item for item in items if not item["decided"]]
    return {
        "candidates": items,
        "counts": {"pending": len(pending), "total": len(items)},
    }
