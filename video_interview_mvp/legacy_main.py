"""FastAPI application for the AI video interview MVP."""
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import database
from config import ANSWER_TIME_LIMIT_SECONDS, MAX_QUESTIONS_PER_INTERVIEW, UPLOAD_DIR
from database import (
    Answer,
    AnswerMedia,
    CandidateLifecycle,
    FinalReport,
    InterviewQuestion,
    InterviewSession,
    Question,
    ReviewDecision,
    SessionQuestion,
    User,
    Vacancy,
    get_db,
)
from services import asr_service, llm_service
from services.media_service import extract_video_clip, media_metadata, normalize_audio, normalize_video


BASE_DIR = Path(__file__).parent
QUESTIONS_FILE = BASE_DIR / "data" / "questions.json"

database.init_db()

app = FastAPI(title="Video Interview MVP", version="1.4.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
security = HTTPBasic()

HR_INVITE_TOKEN = os.getenv("HR_INVITE_TOKEN", "hr_master_key_2024")
MANAGER_INVITE_TOKEN = os.getenv("MANAGER_INVITE_TOKEN", "manager_master_key_2024")
INVITE_CODES = {
    "hr": [HR_INVITE_TOKEN, "hr_invite_2024"],
    "hiring_manager": [MANAGER_INVITE_TOKEN, "hm_invite_2024"],
}


class UserCreate(BaseModel):
    username: str
    password: str
    role: str
    full_name: Optional[str] = None
    invite_code: Optional[str] = None


class VacancyCreate(BaseModel):
    title: str
    vacancy_text: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    grade: Optional[str] = "middle"


class InterviewStart(BaseModel):
    vacancy_id: int
    candidate_name: str


class TranscriptCorrection(BaseModel):
    answer_id: int
    corrected_transcript: str


class CandidateQuestionCreate(BaseModel):
    question_text: str
    competency: Optional[str] = "custom"
    reference_answer: Optional[str] = ""
    must_have: List[str] = Field(default_factory=list)
    nice_to_have: List[str] = Field(default_factory=list)
    red_flags: List[str] = Field(default_factory=list)


class CandidateQuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    competency: Optional[str] = None
    reference_answer: Optional[str] = None
    must_have: Optional[List[str]] = None
    nice_to_have: Optional[List[str]] = None
    red_flags: Optional[List[str]] = None
    is_active: Optional[bool] = None
    order_index: Optional[int] = None


class ReviewPayload(BaseModel):
    decision: str
    comment: Optional[str] = ""


class CandidateStatusUpdate(BaseModel):
    status: str
    note: Optional[str] = ""


def hash_password(password: str) -> str:
    return password


def get_current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or user.password_hash != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def _safe_upload_extension(filename: Optional[str], default: str = ".webm") -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in {".webm", ".mp4", ".m4a", ".wav", ".ogg"} else default


def _web_upload_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/uploads/{Path(path).name}"


def _load_question_bank() -> List[dict]:
    if not QUESTIONS_FILE.exists():
        return []
    with QUESTIONS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def _latest_review(session: InterviewSession, role: str) -> Optional[ReviewDecision]:
    items = [item for item in (session.review_decisions or []) if item.reviewer_role == role]
    return items[-1] if items else None


def _manager_can_view(session: InterviewSession) -> bool:
    hr_review = _latest_review(session, "hr")
    manager_review = _latest_review(session, "hiring_manager")
    return bool(manager_review or (hr_review and hr_review.decision == "approve"))


def _get_accessible_vacancy(vacancy_id: int, current_user: User, db: Session) -> Vacancy:
    query = db.query(Vacancy).filter(Vacancy.id == vacancy_id)
    if current_user.role == "hr":
        query = query.filter(Vacancy.owner_id == current_user.id)
    vacancy = query.first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    return vacancy


def _get_accessible_session(session_id: int, current_user: User, db: Session) -> InterviewSession:
    query = db.query(InterviewSession).join(Vacancy).filter(InterviewSession.id == session_id)
    if current_user.role == "hr":
        query = query.filter(Vacancy.owner_id == current_user.id)
    session = query.first()
    if not session:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    if current_user.role == "hiring_manager" and not _manager_can_view(session):
        raise HTTPException(status_code=404, detail="Кандидат ещё не передан нанимающему менеджеру")
    return session


def _question_counts(vacancy: Vacancy) -> tuple[int, int]:
    questions = vacancy.session_questions or []
    return len(questions), sum(1 for item in questions if item.is_approved)


def _review_payload(item: Optional[ReviewDecision]) -> Optional[dict]:
    if not item:
        return None
    reviewer_name = ""
    if item.reviewer:
        reviewer_name = item.reviewer.full_name or item.reviewer.username
    return {
        "decision": item.decision,
        "comment": item.comment or "",
        "reviewer_name": reviewer_name,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
    }


def _workflow_state(session: InterviewSession) -> str:
    if session.status not in {"completed", "hr_approved", "hr_rejected", "manager_approved", "manager_rejected"}:
        return session.status
    hr_review = _latest_review(session, "hr")
    manager_review = _latest_review(session, "hiring_manager")
    if manager_review:
        return "manager_approved" if manager_review.decision == "approve" else "manager_rejected"
    if hr_review:
        if hr_review.decision == "approve":
            return "awaiting_manager"
        if hr_review.decision == "reject":
            return "hr_rejected"
        return "awaiting_hr"
    return "awaiting_hr"


def _ensure_lifecycle(session: InterviewSession, db: Session) -> CandidateLifecycle:
    if session.lifecycle:
        return session.lifecycle
    lifecycle = CandidateLifecycle(session_id=session.id, status="active", note="")
    db.add(lifecycle)
    db.commit()
    db.refresh(session)
    return session.lifecycle


def _session_payload(session: InterviewSession) -> dict:
    report = session.final_report
    hr_review = _latest_review(session, "hr")
    manager_review = _latest_review(session, "hiring_manager")
    lifecycle = session.lifecycle
    return {
        "id": session.id,
        "candidate_name": session.candidate_name,
        "status": session.status,
        "workflow_state": _workflow_state(session),
        "lifecycle_status": lifecycle.status if lifecycle else "active",
        "lifecycle_note": lifecycle.note if lifecycle else "",
        "vacancy_id": session.vacancy_id,
        "vacancy_title": session.vacancy.title if session.vacancy else "",
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        "interview_url": f"/interview/{session.session_token}",
        "report_url": f"/report/{session.id}" if report else None,
        "overall_score": report.overall_score if report else None,
        "recommendation": report.recommendation if report else None,
        "hr_review": _review_payload(hr_review),
        "manager_review": _review_payload(manager_review),
        "question_count": len([q for q in (session.interview_questions or []) if q.is_active]),
        "questions_customized": bool(session.interview_questions),
    }


def _copy_default_questions_to_session(session: InterviewSession, db: Session) -> None:
    if session.interview_questions:
        return
    default_questions = (
        db.query(SessionQuestion)
        .filter(
            SessionQuestion.vacancy_id == session.vacancy_id,
            SessionQuestion.is_approved.is_(True),
        )
        .order_by(SessionQuestion.order_index, SessionQuestion.id)
        .all()
    )
    for index, item in enumerate(default_questions):
        if not item.question:
            continue
        q = item.question
        db.add(
            InterviewQuestion(
                session_id=session.id,
                source_session_question_id=item.id,
                question_text=q.question_text,
                competency=q.competency or "",
                reference_answer=q.reference_answer or "",
                must_have=q.must_have or [],
                nice_to_have=q.nice_to_have or [],
                red_flags=q.red_flags or [],
                order_index=index,
                is_active=True,
                is_custom=False,
            )
        )
    db.commit()
    db.refresh(session)


def _candidate_question_payload(question: InterviewQuestion) -> dict:
    return {
        "id": question.id,
        "question": question.question_text,
        "competency": question.competency or "",
        "reference_answer": question.reference_answer or "",
        "must_have": question.must_have or [],
        "nice_to_have": question.nice_to_have or [],
        "red_flags": question.red_flags or [],
        "order_index": question.order_index,
        "is_active": bool(question.is_active),
        "is_custom": bool(question.is_custom),
        "source_session_question_id": question.source_session_question_id,
    }


def _find_full_video(session_id: int) -> Optional[Path]:
    candidates = sorted(
        UPLOAD_DIR.glob(f"full_interview_{session_id}*"),
        key=lambda path: ("normalized" not in path.stem, -(path.stat().st_mtime if path.exists() else 0)),
    )
    return next((path for path in candidates if path.is_file() and path.stat().st_size > 0), None)


def _delete_candidate_media(session: InterviewSession) -> None:
    files = set()
    for answer in session.answers:
        for raw_path in (answer.audio_path, answer.video_path):
            if raw_path:
                files.add(Path(raw_path))
    files.update(UPLOAD_DIR.glob(f"full_interview_{session.id}*"))
    files.update(UPLOAD_DIR.glob(f"answer_{session.id}_*"))
    files.update(UPLOAD_DIR.glob(f"answer_clip_{session.id}_*"))
    for path in files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _build_answer_clips(session: InterviewSession, full_video: Path, db: Session) -> None:
    for answer in session.answers:
        media = answer.media
        if not media or media.end_ms <= media.start_ms:
            continue
        target = UPLOAD_DIR / f"answer_clip_{session.id}_{answer.id}.webm"
        clip_path, duration_ms = extract_video_clip(full_video, target, media.start_ms, media.end_ms)
        if not clip_path:
            continue
        answer.video_path = str(clip_path)
        media.video_duration_ms = duration_ms or max(0, media.end_ms - media.start_ms)
        media.video_size_bytes = clip_path.stat().st_size
    db.commit()


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.post("/api/auth/login")
async def login(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or user.password_hash != credentials.password:
        raise HTTPException(status_code=401, detail="Неверные учетные данные")
    return {"username": user.username, "role": user.role, "full_name": user.full_name}


@app.post("/api/auth/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    if user_data.role not in INVITE_CODES:
        raise HTTPException(status_code=400, detail="Неизвестная роль")
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    if not user_data.invite_code:
        raise HTTPException(status_code=400, detail="Необходимо ввести пригласительный код")
    if user_data.invite_code not in INVITE_CODES[user_data.role]:
        raise HTTPException(status_code=403, detail="Неверный пригласительный код")
    user = User(
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        role=user_data.role,
        full_name=user_data.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Пользователь успешно создан", "username": user.username}


@app.get("/api/vacancies", response_class=JSONResponse)
async def get_vacancies(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Vacancy)
    if current_user.role == "hr":
        query = query.filter(Vacancy.owner_id == current_user.id)
    vacancies = query.order_by(Vacancy.created_at.desc()).all()
    result = []
    for vacancy in vacancies:
        questions_count, approved_count = _question_counts(vacancy)
        result.append(
            {
                "id": vacancy.id,
                "title": vacancy.title,
                "grade": vacancy.grade,
                "detected_tags": vacancy.detected_tags or [],
                "created_at": vacancy.created_at.isoformat() if vacancy.created_at else None,
                "is_active": vacancy.is_active,
                "sessions_count": len(vacancy.interview_sessions),
                "completed_sessions_count": sum(1 for s in vacancy.interview_sessions if s.final_report),
                "questions_count": questions_count,
                "approved_questions_count": approved_count,
                "questions_approved": approved_count > 0,
            }
        )
    return result


@app.post("/api/vacancies", response_class=JSONResponse)
async def create_vacancy(
    vacancy_data: VacancyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR-менеджеры могут создавать вакансии")
    title = vacancy_data.title.strip()
    source_text = (vacancy_data.vacancy_text or "").strip()
    if not source_text:
        source_text = "\n\n".join(
            part.strip()
            for part in [vacancy_data.description or "", vacancy_data.requirements or ""]
            if part and part.strip()
        ).strip()
    if not title:
        raise HTTPException(status_code=400, detail="Укажите название вакансии")
    if not source_text:
        raise HTTPException(status_code=400, detail="Вставьте текст вакансии")

    detected_tags = await llm_service.extract_tags_from_vacancy(source_text, source_text)
    vacancy = Vacancy(
        title=title,
        description=source_text,
        requirements=source_text,
        grade=vacancy_data.grade or "middle",
        detected_tags=detected_tags,
        owner_id=current_user.id,
    )
    db.add(vacancy)
    db.commit()
    db.refresh(vacancy)

    bank = _load_question_bank()
    suggested = await llm_service.suggest_questions_for_vacancy(
        detected_tags=detected_tags,
        grade=vacancy.grade,
        available_questions=bank,
        limit=MAX_QUESTIONS_PER_INTERVIEW,
    )
    if not suggested and bank:
        suggested = bank[: min(MAX_QUESTIONS_PER_INTERVIEW, len(bank))]
    for idx, item in enumerate(suggested):
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
        db.add(SessionQuestion(vacancy_id=vacancy.id, question_id=question.id, order_index=idx, is_approved=False))
    db.commit()
    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "detected_tags": detected_tags,
        "suggested_questions_count": len(suggested),
        "questions_approved": False,
    }


@app.get("/api/vacancies/{vacancy_id}", response_class=JSONResponse)
async def get_vacancy_details(
    vacancy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    vacancy = _get_accessible_vacancy(vacancy_id, current_user, db)
    session_questions = (
        db.query(SessionQuestion)
        .filter(SessionQuestion.vacancy_id == vacancy_id)
        .order_by(SessionQuestion.order_index, SessionQuestion.id)
        .all()
    )
    questions = []
    for item in session_questions:
        q = item.question
        if q:
            questions.append({
                "session_question_id": item.id,
                "id": q.id,
                "question": q.question_text,
                "tags": q.tags or [],
                "competency": q.competency or "",
                "must_have": q.must_have or [],
                "nice_to_have": q.nice_to_have or [],
                "is_approved": bool(item.is_approved),
            })
    sessions = (
        db.query(InterviewSession)
        .filter(InterviewSession.vacancy_id == vacancy_id)
        .order_by(InterviewSession.created_at.desc())
        .all()
    )
    approved_count = sum(1 for q in questions if q["is_approved"])
    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "vacancy_text": vacancy.description or vacancy.requirements or "",
        "description": vacancy.description,
        "requirements": vacancy.requirements,
        "grade": vacancy.grade,
        "detected_tags": vacancy.detected_tags or [],
        "questions": questions,
        "questions_count": len(questions),
        "approved_questions_count": approved_count,
        "questions_approved": approved_count > 0,
        "sessions": [_session_payload(session) for session in sessions],
    }


@app.post("/api/vacancies/{vacancy_id}/approve-questions", response_class=JSONResponse)
async def approve_vacancy_questions(
    vacancy_id: int,
    question_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    _get_accessible_vacancy(vacancy_id, current_user, db)
    items = (
        db.query(SessionQuestion)
        .filter(SessionQuestion.vacancy_id == vacancy_id)
        .order_by(SessionQuestion.order_index, SessionQuestion.id)
        .all()
    )
    if not items:
        raise HTTPException(status_code=400, detail="Для вакансии нет предложенных вопросов")
    requested = list(dict.fromkeys(question_ids))
    if not requested:
        raise HTTPException(status_code=400, detail="Выберите хотя бы один вопрос")
    existing = {item.question_id for item in items}
    if any(qid not in existing for qid in requested):
        raise HTTPException(status_code=400, detail="В списке есть чужой вопрос")
    selected_order = {qid: idx for idx, qid in enumerate(requested)}
    rejected_index = len(requested)
    for item in items:
        item.is_approved = item.question_id in selected_order
        if item.is_approved:
            item.order_index = selected_order[item.question_id]
        else:
            item.order_index = rejected_index
            rejected_index += 1
    db.commit()
    return {"message": "Базовый пул вакансии сохранён", "approved_count": len(requested)}


@app.get("/api/questions", response_class=JSONResponse)
async def get_question_bank(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bank = _load_question_bank()
    db_questions = db.query(Question).all()
    by_text = {q.question_text: q for q in db_questions}
    result = []
    for item in bank:
        db_question = by_text.get(item.get("question", ""))
        result.append({
            "bank_id": item.get("id"),
            "database_id": db_question.id if db_question else None,
            "question": item.get("question", ""),
            "tags": item.get("tags", []),
            "competency": item.get("competency", ""),
            "must_have": item.get("must_have", []),
            "nice_to_have": item.get("nice_to_have", []),
            "usage_count": len(db_question.session_questions) if db_question else 0,
        })
    return result


@app.get("/api/candidates", response_class=JSONResponse)
async def get_candidates(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(InterviewSession).join(Vacancy)
    if current_user.role == "hr":
        query = query.filter(Vacancy.owner_id == current_user.id)
    sessions = query.order_by(InterviewSession.created_at.desc()).all()
    if current_user.role == "hiring_manager":
        sessions = [session for session in sessions if _manager_can_view(session)]
    return [_session_payload(session) for session in sessions]


@app.patch("/api/candidates/{session_id}/status", response_class=JSONResponse)
async def update_candidate_status(
    session_id: int,
    payload: CandidateStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять статус кандидата")
    session = _get_accessible_session(session_id, current_user, db)
    if payload.status not in {"active", "hold", "rejected", "hired"}:
        raise HTTPException(status_code=400, detail="Допустимые статусы: active, hold, rejected, hired")
    lifecycle = _ensure_lifecycle(session, db)
    lifecycle.status = payload.status
    lifecycle.note = (payload.note or "").strip()
    lifecycle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return {"message": "Статус кандидата сохранён", "candidate": _session_payload(session)}


@app.delete("/api/candidates/{session_id}", response_class=JSONResponse)
async def delete_candidate(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может удалять кандидатов")
    session = _get_accessible_session(session_id, current_user, db)
    if session.status == "in_progress":
        raise HTTPException(status_code=400, detail="Нельзя удалить кандидата во время интервью")
    if _latest_review(session, "hiring_manager") and (not session.lifecycle or session.lifecycle.status != "rejected"):
        raise HTTPException(
            status_code=400,
            detail="У кандидата уже есть финальное решение менеджера. Сначала отметьте его как «Отказ» в HR-статусе.",
        )
    _delete_candidate_media(session)
    name = session.candidate_name
    db.delete(session)
    db.commit()
    return {"message": f"Кандидат {name} удалён"}


@app.post("/api/interviews/create", response_class=JSONResponse)
async def create_interview_session(
    interview_data: InterviewStart,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR-менеджеры могут создавать интервью")
    vacancy = _get_accessible_vacancy(interview_data.vacancy_id, current_user, db)
    approved = (
        db.query(SessionQuestion)
        .filter(SessionQuestion.vacancy_id == vacancy.id, SessionQuestion.is_approved.is_(True))
        .count()
    )
    if approved == 0:
        raise HTTPException(status_code=400, detail="Сначала утвердите базовый пул вопросов вакансии")
    name = interview_data.candidate_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя кандидата")
    session = InterviewSession(vacancy_id=vacancy.id, candidate_name=name, session_token=str(uuid.uuid4()), status="pending")
    db.add(session)
    db.flush()
    db.add(CandidateLifecycle(session_id=session.id, status="active", note=""))
    db.commit()
    db.refresh(session)
    _copy_default_questions_to_session(session, db)
    return {
        "session_id": session.id,
        "session_token": session.session_token,
        "interview_url": f"/interview/{session.session_token}",
        "candidate_name": session.candidate_name,
        "vacancy_title": vacancy.title,
        "question_count": len(session.interview_questions),
    }


@app.get("/api/interviews/{session_id}/questions", response_class=JSONResponse)
async def get_candidate_questions(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять вопросы кандидата")
    session = _get_accessible_session(session_id, current_user, db)
    _copy_default_questions_to_session(session, db)
    questions = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.session_id == session.id)
        .order_by(InterviewQuestion.order_index, InterviewQuestion.id)
        .all()
    )
    return {
        "session_id": session.id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "editable": not bool(session.started_at),
        "questions": [_candidate_question_payload(q) for q in questions],
    }


@app.post("/api/interviews/{session_id}/questions", response_class=JSONResponse)
async def add_candidate_question(
    session_id: int,
    payload: CandidateQuestionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять вопросы кандидата")
    session = _get_accessible_session(session_id, current_user, db)
    if session.started_at:
        raise HTTPException(status_code=400, detail="Интервью уже началось — набор вопросов зафиксирован")
    text = payload.question_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Введите текст вопроса")
    max_order = max([q.order_index for q in session.interview_questions], default=-1)
    question = InterviewQuestion(
        session_id=session.id,
        source_session_question_id=None,
        question_text=text,
        competency=(payload.competency or "custom").strip(),
        reference_answer=payload.reference_answer or "",
        must_have=payload.must_have,
        nice_to_have=payload.nice_to_have,
        red_flags=payload.red_flags,
        order_index=max_order + 1,
        is_active=True,
        is_custom=True,
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return _candidate_question_payload(question)


@app.patch("/api/interviews/{session_id}/questions/{question_id}", response_class=JSONResponse)
async def update_candidate_question(
    session_id: int,
    question_id: int,
    payload: CandidateQuestionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять вопросы кандидата")
    session = _get_accessible_session(session_id, current_user, db)
    if session.started_at:
        raise HTTPException(status_code=400, detail="Интервью уже началось — набор вопросов зафиксирован")
    question = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.id == question_id, InterviewQuestion.session_id == session.id)
        .first()
    )
    if not question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    if payload.question_text is not None:
        text = payload.question_text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Текст вопроса не может быть пустым")
        question.question_text = text
    for field in ("competency", "reference_answer", "must_have", "nice_to_have", "red_flags", "is_active", "order_index"):
        value = getattr(payload, field)
        if value is not None:
            setattr(question, field, value)
    db.commit()
    db.refresh(question)
    return _candidate_question_payload(question)


@app.post("/api/interviews/{session_id}/questions/reset", response_class=JSONResponse)
async def reset_candidate_questions(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может менять вопросы кандидата")
    session = _get_accessible_session(session_id, current_user, db)
    if session.started_at:
        raise HTTPException(status_code=400, detail="Интервью уже началось — набор вопросов зафиксирован")
    db.query(InterviewQuestion).filter(InterviewQuestion.session_id == session.id).delete()
    db.commit()
    db.refresh(session)
    _copy_default_questions_to_session(session, db)
    return {"message": "Набор кандидата сброшен к базовому пулу вакансии"}


@app.get("/api/interviews/{session_token}", response_class=JSONResponse)
async def get_interview_session(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.final_report:
        raise HTTPException(status_code=400, detail="Интервью уже завершено")
    _copy_default_questions_to_session(session, db)
    questions = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.session_id == session.id, InterviewQuestion.is_active.is_(True))
        .order_by(InterviewQuestion.order_index, InterviewQuestion.id)
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="HR ещё не настроил вопросы интервью")
    return {
        "session_id": session.id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "questions": [{"session_question_id": q.id, "question": q.question_text} for q in questions],
        "time_limit": ANSWER_TIME_LIMIT_SECONDS,
    }


@app.post("/api/interviews/{session_token}/start", response_class=JSONResponse)
async def start_interview(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.final_report:
        raise HTTPException(status_code=400, detail="Интервью уже завершено")
    _copy_default_questions_to_session(session, db)
    active_count = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.session_id == session.id, InterviewQuestion.is_active.is_(True))
        .count()
    )
    if not active_count:
        raise HTTPException(status_code=400, detail="Для кандидата нет активных вопросов")
    session.status = "in_progress"
    session.started_at = session.started_at or datetime.utcnow()
    db.commit()
    return {"message": "Интервью начато", "session_id": session.id}


@app.post("/api/interviews/submit-answer", response_class=JSONResponse)
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
        extension = _safe_upload_extension(file.filename)
        filename = f"answer_{session_id}_{question_id}_{uuid.uuid4().hex[:8]}{extension}"
        raw_upload_path = UPLOAD_DIR / filename
        raw_upload_path.write_bytes(file_bytes)

    raw_transcript = transcript.strip()
    asr_confidence = None
    if file_bytes:
        asr_result = await asr_service.transcribe_audio(file_bytes, language="ru")
        if asr_result.get("success") and asr_result.get("transcript"):
            raw_transcript = asr_result["transcript"].strip()
            asr_confidence = asr_result.get("confidence")
        elif not raw_transcript:
            raise HTTPException(status_code=502, detail=f"Не удалось распознать речь: {asr_result.get('error', 'ASR error')}")

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
    effective_end = max(end_ms, start_ms + (audio_duration_ms or 0))
    db.add(AnswerMedia(
        answer_id=answer.id,
        start_ms=max(0, start_ms),
        end_ms=max(start_ms, effective_end),
        audio_duration_ms=audio_duration_ms,
        audio_size_bytes=audio_size_bytes,
    ))
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


async def analyze_answer(answer_id: int, db: Session) -> None:
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        return
    iq = (
        db.query(InterviewQuestion)
        .filter(InterviewQuestion.session_id == answer.session_id, InterviewQuestion.question_text == answer.question_text)
        .first()
    )
    if iq:
        question_text = iq.question_text
        reference_answer = iq.reference_answer or ""
        must_have = iq.must_have or []
        nice_to_have = iq.nice_to_have or []
        red_flags = iq.red_flags or []
    else:
        sq = db.query(SessionQuestion).filter(SessionQuestion.id == answer.session_question_id).first()
        q = sq.question if sq else None
        question_text = answer.question_text or (q.question_text if q else "")
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
    )
    answer.score = analysis.get("score", 5.0)
    answer.llm_analysis = analysis
    db.commit()


@app.post("/api/interviews/correct-transcript", response_class=JSONResponse)
async def correct_transcript(payload: TranscriptCorrection, db: Session = Depends(get_db)):
    answer = db.query(Answer).filter(Answer.id == payload.answer_id).first()
    if not answer:
        raise HTTPException(status_code=404, detail="Ответ не найден")
    corrected = payload.corrected_transcript.strip()
    if not corrected:
        raise HTTPException(status_code=400, detail="Транскрипция не может быть пустой")
    answer.transcript_corrected = corrected
    answer.is_approved_by_candidate = True
    db.commit()
    await analyze_answer(answer.id, db)
    return {"message": "Транскрипция подтверждена", "answer_id": answer.id}


@app.post("/api/interviews/{session_id}/full-video", response_class=JSONResponse)
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
    extension = _safe_upload_extension(file.filename)
    filename = f"full_interview_{session_id}{extension}"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(content)
    normalized_path, probed_duration = normalize_video(destination)
    duration_ms = probed_duration or (client_duration_ms if client_duration_ms > 0 else None)
    _build_answer_clips(session, normalized_path, db)
    metadata = media_metadata(str(normalized_path), duration_ms)
    return {"message": "Полная видеозапись сохранена", "video_path": _web_upload_path(str(normalized_path)), **metadata}


@app.post("/api/interviews/{session_id}/complete", response_class=JSONResponse)
async def complete_interview(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    if not answers:
        raise HTTPException(status_code=400, detail="Нельзя завершить интервью без ответов")
    for answer in answers:
        if answer.score is None and (answer.transcript_corrected or answer.transcript_raw):
            await analyze_answer(answer.id, db)
    answers_data = [{
        "question": answer.question_text,
        "transcript": answer.transcript_corrected or answer.transcript_raw,
        "score": answer.score,
        "analysis": (answer.llm_analysis or {}).get("analysis", ""),
        "strengths": (answer.llm_analysis or {}).get("strengths", []),
        "weaknesses": (answer.llm_analysis or {}).get("weaknesses", []),
        "covered_must_have": (answer.llm_analysis or {}).get("covered_must_have", []),
        "detected_red_flags": (answer.llm_analysis or {}).get("detected_red_flags", []),
    } for answer in answers]
    report_data = await llm_service.generate_final_report(
        vacancy_title=session.vacancy.title,
        vacancy_requirements=session.vacancy.requirements or session.vacancy.description or "",
        answers_data=answers_data,
    )
    final_report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not final_report:
        final_report = FinalReport(session_id=session_id)
        db.add(final_report)
    final_report.overall_score = report_data.get("overall_score", 5.0)
    final_report.recommendation = report_data.get("recommendation", "требуется дополнительная проверка")
    final_report.summary = report_data.get("summary", "")
    final_report.strengths = report_data.get("strengths", [])
    final_report.weaknesses = report_data.get("weaknesses", [])
    final_report.detected_skills = report_data.get("detected_skills", [])
    final_report.areas_to_check = report_data.get("areas_to_check", [])
    final_report.risk_factors = report_data.get("risk_factors", [])
    final_report.generated_at = datetime.utcnow()
    session.status = "completed"
    session.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(final_report)
    return {"message": "Интервью завершено, отчёт сгенерирован", "report_id": final_report.id}


@app.post("/api/reviews/{session_id}/hr", response_class=JSONResponse)
async def hr_review(
    session_id: int,
    payload: ReviewPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR может выполнить первый аппрув")
    session = _get_accessible_session(session_id, current_user, db)
    if not session.final_report:
        raise HTTPException(status_code=400, detail="Сначала должно завершиться интервью и сформироваться отчёт")
    if _latest_review(session, "hiring_manager"):
        raise HTTPException(status_code=400, detail="Финальное решение менеджера уже принято и не может быть переопределено HR")
    if payload.decision not in {"approve", "reject", "needs_review"}:
        raise HTTPException(status_code=400, detail="Неизвестное решение")
    db.add(ReviewDecision(
        session_id=session.id,
        reviewer_id=current_user.id,
        reviewer_role="hr",
        decision=payload.decision,
        comment=(payload.comment or "").strip(),
    ))
    session.status = "hr_approved" if payload.decision == "approve" else "hr_rejected" if payload.decision == "reject" else "completed"
    if payload.decision == "reject":
        lifecycle = _ensure_lifecycle(session, db)
        lifecycle.status = "rejected"
        lifecycle.note = (payload.comment or "").strip()
    db.commit()
    db.refresh(session)
    return {"message": "Решение HR сохранено", "workflow_state": _workflow_state(session)}


@app.post("/api/reviews/{session_id}/manager", response_class=JSONResponse)
async def manager_review(
    session_id: int,
    payload: ReviewPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hiring_manager":
        raise HTTPException(status_code=403, detail="Финальное решение доступно только нанимающему менеджеру")
    session = _get_accessible_session(session_id, current_user, db)
    if not session.final_report:
        raise HTTPException(status_code=400, detail="Отчёт ещё не готов")
    hr_decision = _latest_review(session, "hr")
    if not hr_decision or hr_decision.decision != "approve":
        raise HTTPException(status_code=400, detail="Сначала HR должен одобрить кандидата")
    if _latest_review(session, "hiring_manager"):
        raise HTTPException(status_code=400, detail="Финальное решение уже принято")
    if payload.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="Менеджер должен выбрать финально: одобрить или отклонить")
    db.add(ReviewDecision(
        session_id=session.id,
        reviewer_id=current_user.id,
        reviewer_role="hiring_manager",
        decision=payload.decision,
        comment=(payload.comment or "").strip(),
    ))
    session.status = "manager_approved" if payload.decision == "approve" else "manager_rejected"
    lifecycle = _ensure_lifecycle(session, db)
    lifecycle.status = "hired" if payload.decision == "approve" else "rejected"
    lifecycle.note = (payload.comment or "").strip()
    db.commit()
    db.refresh(session)
    return {"message": "Финальное решение сохранено", "workflow_state": _workflow_state(session)}


@app.get("/api/reports/{session_id}", response_class=JSONResponse)
async def get_report(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_accessible_session(session_id, current_user, db)
    report = session.final_report
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    full_video = _find_full_video(session_id)
    full_video_meta = media_metadata(str(full_video) if full_video else None)
    return {
        "id": report.id,
        "session_id": report.session_id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "vacancy_text": session.vacancy.description or "",
        "overall_score": report.overall_score,
        "recommendation": report.recommendation,
        "summary": report.summary,
        "strengths": report.strengths or [],
        "weaknesses": report.weaknesses or [],
        "detected_skills": report.detected_skills or [],
        "areas_to_check": report.areas_to_check or [],
        "risk_factors": report.risk_factors or [],
        "full_video_path": _web_upload_path(str(full_video)) if full_video else None,
        "full_video_media": full_video_meta,
        "answers": [{
            "id": answer.id,
            "question": answer.question_text,
            "transcript": answer.transcript_corrected or answer.transcript_raw,
            "transcript_raw": answer.transcript_raw,
            "score": answer.score,
            "audio_path": _web_upload_path(answer.audio_path),
            "video_path": _web_upload_path(answer.video_path),
            "audio_media": media_metadata(answer.audio_path, answer.media.audio_duration_ms if answer.media else None),
            "video_media": media_metadata(answer.video_path, answer.media.video_duration_ms if answer.media else None),
            "start_ms": answer.media.start_ms if answer.media else None,
            "end_ms": answer.media.end_ms if answer.media else None,
            "analysis": answer.llm_analysis,
        } for answer in answers],
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        "workflow_state": _workflow_state(session),
        "lifecycle_status": session.lifecycle.status if session.lifecycle else "active",
        "lifecycle_note": session.lifecycle.note if session.lifecycle else "",
        "hr_review": _review_payload(_latest_review(session, "hr")),
        "manager_review": _review_payload(_latest_review(session, "hiring_manager")),
        "viewer_role": current_user.role,
    }


@app.get("/interview/{session_token}", response_class=HTMLResponse)
async def interview_page(session_token: str, request: Request, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return templates.TemplateResponse(
        "interview.html",
        {
            "request": request,
            "session_token": session_token,
            "candidate_name": session.candidate_name,
            "vacancy_title": session.vacancy.title,
        },
    )


@app.get("/report/{session_id}", response_class=HTMLResponse)
async def report_page(session_id: int, request: Request, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session or not session.final_report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    return templates.TemplateResponse("report.html", {"request": request, "session_id": session_id})


if __name__ == "__main__":
    import uvicorn

    key_path = BASE_DIR / "key.pem"
    cert_path = BASE_DIR / "cert.pem"
    kwargs = {"host": "0.0.0.0", "port": 8000}
    if key_path.exists() and cert_path.exists():
        kwargs.update({"ssl_keyfile": str(key_path), "ssl_certfile": str(cert_path)})
    uvicorn.run(app, **kwargs)
