"""FastAPI application for the AI video interview MVP."""
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database
from config import ANSWER_TIME_LIMIT_SECONDS, MAX_QUESTIONS_PER_INTERVIEW, UPLOAD_DIR
from database import (
    Answer,
    FinalReport,
    InterviewSession,
    Question,
    SessionQuestion,
    User,
    Vacancy,
    get_db,
)
from services import asr_service, llm_service


BASE_DIR = Path(__file__).parent
QUESTIONS_FILE = BASE_DIR / "data" / "questions.json"

# Database is intentionally lightweight for the hackathon MVP.
database.init_db()

app = FastAPI(title="Video Interview MVP", version="1.1.0")
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
    description: str
    requirements: str
    grade: Optional[str] = "middle"


class InterviewStart(BaseModel):
    vacancy_id: int
    candidate_name: str


class TranscriptCorrection(BaseModel):
    answer_id: int
    corrected_transcript: str


def hash_password(password: str) -> str:
    # MVP only. Replace with bcrypt/argon2 before production use.
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
    # The current MVP keeps browser-side Basic Auth state in the dashboard.
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.post("/api/auth/login")
async def login(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
):
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
async def get_vacancies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Hiring managers need the same list in the demo UI; HR sees owned vacancies.
    query = db.query(Vacancy)
    if current_user.role == "hr":
        query = query.filter(Vacancy.owner_id == current_user.id)
    vacancies = query.order_by(Vacancy.created_at.desc()).all()
    return [
        {
            "id": v.id,
            "title": v.title,
            "grade": v.grade,
            "detected_tags": v.detected_tags or [],
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "is_active": v.is_active,
            "sessions_count": len(v.interview_sessions),
        }
        for v in vacancies
    ]


@app.post("/api/vacancies", response_class=JSONResponse)
async def create_vacancy(
    vacancy_data: VacancyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR-менеджеры могут создавать вакансии")

    detected_tags = await llm_service.extract_tags_from_vacancy(
        vacancy_data.description,
        vacancy_data.requirements,
    )
    vacancy = Vacancy(
        title=vacancy_data.title,
        description=vacancy_data.description,
        requirements=vacancy_data.requirements,
        grade=vacancy_data.grade,
        detected_tags=detected_tags,
        owner_id=current_user.id,
    )
    db.add(vacancy)
    db.commit()
    db.refresh(vacancy)

    available_questions = []
    if QUESTIONS_FILE.exists():
        with QUESTIONS_FILE.open("r", encoding="utf-8") as file:
            available_questions = json.load(file)

    suggested = await llm_service.suggest_questions_for_vacancy(
        detected_tags=detected_tags,
        grade=vacancy_data.grade,
        available_questions=available_questions,
        limit=MAX_QUESTIONS_PER_INTERVIEW,
    )

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
        db.add(
            SessionQuestion(
                vacancy_id=vacancy.id,
                question_id=question.id,
                order_index=idx,
                is_approved=True,
            )
        )
    db.commit()

    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "detected_tags": detected_tags,
        "suggested_questions_count": len(suggested),
    }


@app.get("/api/vacancies/{vacancy_id}", response_class=JSONResponse)
async def get_vacancy_details(
    vacancy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    vacancy = db.query(Vacancy).filter(Vacancy.id == vacancy_id).first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    session_questions = (
        db.query(SessionQuestion)
        .filter(SessionQuestion.vacancy_id == vacancy_id)
        .order_by(SessionQuestion.order_index)
        .all()
    )
    questions = []
    for sq in session_questions:
        q = db.query(Question).filter(Question.id == sq.question_id).first()
        if q:
            questions.append(
                {
                    "session_question_id": sq.id,
                    "id": q.id,
                    "question": q.question_text,
                    "tags": q.tags or [],
                    "competency": q.competency,
                }
            )

    sessions = db.query(InterviewSession).filter(InterviewSession.vacancy_id == vacancy_id).all()
    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "description": vacancy.description,
        "requirements": vacancy.requirements,
        "grade": vacancy.grade,
        "detected_tags": vacancy.detected_tags or [],
        "questions": questions,
        "sessions": [
            {
                "id": s.id,
                "candidate_name": s.candidate_name,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
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
    if not db.query(Vacancy).filter(Vacancy.id == vacancy_id).first():
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    db.query(SessionQuestion).filter(SessionQuestion.vacancy_id == vacancy_id).delete()
    for idx, question_id in enumerate(question_ids):
        db.add(
            SessionQuestion(
                vacancy_id=vacancy_id,
                question_id=question_id,
                order_index=idx,
                is_approved=True,
            )
        )
    db.commit()
    return {"message": "Вопросы успешно аппрувлены", "count": len(question_ids)}


@app.post("/api/interviews/create", response_class=JSONResponse)
async def create_interview_session(
    interview_data: InterviewStart,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "hr":
        raise HTTPException(status_code=403, detail="Только HR-менеджеры могут создавать интервью")
    vacancy = db.query(Vacancy).filter(Vacancy.id == interview_data.vacancy_id).first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    session = InterviewSession(
        vacancy_id=vacancy.id,
        candidate_name=interview_data.candidate_name,
        session_token=str(uuid.uuid4()),
        status="pending",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "session_token": session.session_token,
        "interview_url": f"/interview/{session.session_token}",
        "candidate_name": session.candidate_name,
    }


@app.get("/api/interviews/{session_token}", response_class=JSONResponse)
async def get_interview_session(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Интервью уже завершено")

    session_questions = (
        db.query(SessionQuestion)
        .filter(SessionQuestion.vacancy_id == session.vacancy_id)
        .order_by(SessionQuestion.order_index)
        .all()
    )
    questions = []
    for sq in session_questions:
        q = db.query(Question).filter(Question.id == sq.question_id).first()
        if q:
            questions.append({"session_question_id": sq.id, "question": q.question_text})

    return {
        "session_id": session.id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "questions": questions,
        "time_limit": ANSWER_TIME_LIMIT_SECONDS,
    }


@app.post("/api/interviews/{session_token}/start", response_class=JSONResponse)
async def start_interview(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Интервью уже завершено")
    session.status = "in_progress"
    session.started_at = session.started_at or datetime.utcnow()
    db.commit()
    return {"message": "Интервью начато", "session_id": session.id}


@app.post("/api/interviews/submit-answer", response_class=JSONResponse)
async def submit_answer(
    session_id: int = Form(...),
    question_id: int = Form(...),
    transcript: str = Form(""),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Store one answer audio and return its ASR transcript.

    This endpoint deliberately works without API keys: ASRService returns a mock
    transcript when DEEPGRAM_API_KEY is absent, so the complete UI flow remains
    testable on a fresh checkout.
    """
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session_question = (
        db.query(SessionQuestion)
        .filter(
            SessionQuestion.id == question_id,
            SessionQuestion.vacancy_id == session.vacancy_id,
        )
        .first()
    )
    if not session_question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")
    question = db.query(Question).filter(Question.id == session_question.question_id).first()

    audio_path = None
    file_bytes = b""
    if file:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Получена пустая аудиозапись")
        extension = _safe_upload_extension(file.filename)
        filename = f"answer_{session_id}_{question_id}_{uuid.uuid4().hex[:8]}{extension}"
        destination = UPLOAD_DIR / filename
        destination.write_bytes(file_bytes)
        audio_path = str(destination)

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

    answer = Answer(
        session_id=session_id,
        session_question_id=question_id,
        question_text=question.question_text,
        video_path=None,
        audio_path=audio_path,
        transcript_raw=raw_transcript,
        transcript_corrected=raw_transcript,
        is_approved_by_candidate=False,
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    return {
        "answer_id": answer.id,
        "message": "Ответ сохранён",
        "transcript": raw_transcript,
        "asr_confidence": asr_confidence,
        "mock_asr": not bool(os.getenv("DEEPGRAM_API_KEY")),
    }


async def analyze_answer(answer_id: int, db: Session) -> None:
    answer = db.query(Answer).filter(Answer.id == answer_id).first()
    if not answer:
        return
    session_question = db.query(SessionQuestion).filter(SessionQuestion.id == answer.session_question_id).first()
    if not session_question:
        return
    question = db.query(Question).filter(Question.id == session_question.question_id).first()
    if not question:
        return

    analysis = await llm_service.analyze_answer(
        question=question.question_text,
        reference_answer=question.reference_answer or "",
        must_have=question.must_have or [],
        nice_to_have=question.nice_to_have or [],
        red_flags=question.red_flags or [],
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
    # One inexpensive evaluation call per confirmed answer. With no LLM_API_KEY the
    # service uses its built-in mock, keeping local/demo mode fully functional.
    await analyze_answer(answer.id, db)
    return {"message": "Транскрипция подтверждена", "answer_id": answer.id}


@app.post("/api/interviews/{session_id}/full-video", response_class=JSONResponse)
async def upload_full_interview_video(
    session_id: int,
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
    return {
        "message": "Полная видеозапись сохранена",
        "video_path": f"/uploads/{filename}",
        "size_bytes": len(content),
    }


@app.post("/api/interviews/{session_id}/complete", response_class=JSONResponse)
async def complete_interview(session_id: int, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    if not answers:
        raise HTTPException(status_code=400, detail="Нельзя завершить интервью без ответов")

    # Recover gracefully if a candidate closed transcript review without analysis.
    for answer in answers:
        if answer.score is None and (answer.transcript_corrected or answer.transcript_raw):
            await analyze_answer(answer.id, db)

    answers_data = [
        {
            "question": answer.question_text,
            "transcript": answer.transcript_corrected or answer.transcript_raw,
            "score": answer.score,
            "analysis": (answer.llm_analysis or {}).get("analysis", ""),
            "strengths": (answer.llm_analysis or {}).get("strengths", []),
            "weaknesses": (answer.llm_analysis or {}).get("weaknesses", []),
        }
        for answer in answers
    ]
    report_data = await llm_service.generate_final_report(
        vacancy_title=session.vacancy.title,
        vacancy_requirements=session.vacancy.requirements or "",
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

    session.status = "completed"
    session.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(final_report)
    return {"message": "Интервью завершено, отчёт сгенерирован", "report_id": final_report.id}


@app.get("/api/reports/{session_id}", response_class=JSONResponse)
async def get_report(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")

    answers = db.query(Answer).filter(Answer.session_id == session_id).order_by(Answer.id).all()
    full_video = None
    for extension in ("webm", "mp4"):
        candidate = UPLOAD_DIR / f"full_interview_{session_id}.{extension}"
        if candidate.exists():
            full_video = f"/uploads/{candidate.name}"
            break

    return {
        "id": report.id,
        "session_id": report.session_id,
        "candidate_name": report.interview_session.candidate_name,
        "vacancy_title": report.interview_session.vacancy.title,
        "overall_score": report.overall_score,
        "recommendation": report.recommendation,
        "summary": report.summary,
        "strengths": report.strengths or [],
        "weaknesses": report.weaknesses or [],
        "detected_skills": report.detected_skills or [],
        "areas_to_check": report.areas_to_check or [],
        "risk_factors": report.risk_factors or [],
        "full_video_path": full_video,
        "answers": [
            {
                "id": answer.id,
                "question": answer.question_text,
                "transcript": answer.transcript_corrected or answer.transcript_raw,
                "transcript_raw": answer.transcript_raw,
                "score": answer.score,
                "audio_path": _web_upload_path(answer.audio_path),
                "analysis": answer.llm_analysis,
            }
            for answer in answers
        ],
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
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
    report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    return templates.TemplateResponse(
        "report.html",
        {"request": request, "report": report, "session_id": session_id},
    )


if __name__ == "__main__":
    import uvicorn

    # HTTPS certificates are optional. Localhost works with getUserMedia over HTTP;
    # remote deployments should terminate TLS in a reverse proxy or provide certs.
    key_path = BASE_DIR / "key.pem"
    cert_path = BASE_DIR / "cert.pem"
    kwargs = {"host": "0.0.0.0", "port": 8000}
    if key_path.exists() and cert_path.exists():
        kwargs.update({"ssl_keyfile": str(key_path), "ssl_certfile": str(cert_path)})
    uvicorn.run(app, **kwargs)
