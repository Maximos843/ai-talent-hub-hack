"""
Основное приложение FastAPI
"""
import uuid
import shutil
import os
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

import database
from database import get_db, User, Vacancy, Question, SessionQuestion, InterviewSession, Answer, FinalReport
from config import UPLOAD_DIR, MAX_QUESTIONS_PER_INTERVIEW, ANSWER_TIME_LIMIT_SECONDS
from services import llm_service, asr_service, tts_service

# Инициализация БД
database.init_db()

app = FastAPI(title="Video Interview MVP", version="1.0.0")

# Монтирование статических файлов и шаблонов
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

templates = Jinja2Templates(directory="templates")

# Безопасность (простая HTTP Basic Auth для MVP)
security = HTTPBasic()

# Токены доступа из переменных окружения
HR_INVITE_TOKEN = os.getenv("HR_INVITE_TOKEN", "hr_master_key_2024")
MANAGER_INVITE_TOKEN = os.getenv("MANAGER_INVITE_TOKEN", "manager_master_key_2024")


# ==================== Модели Pydantic ====================

class UserRegister(BaseModel):
    username: str
    password: str
    role: str  # 'hr' или 'hiring_manager'
    full_name: Optional[str] = None
    invite_code: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str  # 'hr' или 'hiring_manager'
    full_name: Optional[str] = None
    invite_code: Optional[str] = None


class VacancyCreate(BaseModel):
    title: str
    description: str
    requirements: str
    grade: Optional[str] = "middle"


class QuestionBulkAdd(BaseModel):
    question_ids: List[int]


class InterviewStart(BaseModel):
    vacancy_id: int
    candidate_name: str


class AnswerSubmit(BaseModel):
    session_id: int
    question_id: int
    transcript: str
    score: float
    analysis: dict


class TranscriptCorrection(BaseModel):
    answer_id: int
    corrected_transcript: str


# ==================== Константы ====================

INVITE_CODES = {
    "hr": ["hr_master_key_2024", "hr_invite_2024"],
    "hiring_manager": ["manager_master_key_2024", "hm_invite_2024"]
}

def get_current_user(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    """Получение текущего пользователя"""
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or user.password_hash != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def hash_password(password: str) -> str:
    """Хеширование пароля (для MVP просто возвращаем как есть)"""
    # В продакшене использовать bcrypt или argon2
    return password


# ==================== API Endpoints ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница - лендинг"""
    return templates.TemplateResponse("landing.html", {"request": {}})


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Страница входа"""
    return templates.TemplateResponse("login.html", {"request": {}})


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    """Страница регистрации"""
    return templates.TemplateResponse("login.html", {"request": {}})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Панель управления (требует авторизации)"""
    return templates.TemplateResponse("dashboard.html", {"request": {}})


@app.post("/api/auth/login")
async def login(credentials: HTTPBasicCredentials = Depends(security), db: Session = Depends(get_db)):
    """Вход в систему"""
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or user.password_hash != credentials.password:
        raise HTTPException(status_code=401, detail="Неверные учетные данные")

    return {
        "username": user.username,
        "role": user.role,
        "full_name": user.full_name
    }


@app.post("/api/auth/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Регистрация нового пользователя с проверкой пригласительного кода"""
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    
    # Проверка пригласительного кода
    if not user_data.invite_code:
        raise HTTPException(status_code=400, detail="Необходимо ввести пригласительный код")
    
    valid_codes = INVITE_CODES.get(user_data.role, [])
    if user_data.invite_code not in valid_codes:
        raise HTTPException(status_code=403, detail="Неверный пригласительный код")
    
    new_user = User(
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        role=user_data.role,
        full_name=user_data.full_name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {"message": "Пользователь успешно создан", "username": new_user.username}


@app.get("/api/vacancies", response_class=JSONResponse)
async def get_vacancies(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Получение списка вакансий"""
    vacancies = db.query(Vacancy).filter(Vacancy.owner_id == current_user.id).all()
    return [
        {
            "id": v.id,
            "title": v.title,
            "grade": v.grade,
            "detected_tags": v.detected_tags,
            "created_at": v.created_at.isoformat(),
            "is_active": v.is_active,
            "sessions_count": len(v.interview_sessions)
        }
        for v in vacancies
    ]


@app.post("/api/vacancies", response_class=JSONResponse)
async def create_vacancy(
    vacancy_data: VacancyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание новой вакансии с авто-подбором вопросов"""
    # Извлекаем теги из описания
    detected_tags = await llm_service.extract_tags_from_vacancy(
        vacancy_data.description,
        vacancy_data.requirements
    )

    # Создаем вакансию
    new_vacancy = Vacancy(
        title=vacancy_data.title,
        description=vacancy_data.description,
        requirements=vacancy_data.requirements,
        grade=vacancy_data.grade,
        detected_tags=detected_tags,
        owner_id=current_user.id
    )
    db.add(new_vacancy)
    db.commit()
    db.refresh(new_vacancy)

    # Загружаем вопросы из JSON файла
    questions_file = Path("data/questions.json")
    available_questions = []
    if questions_file.exists():
        import json
        with open(questions_file, 'r', encoding='utf-8') as f:
            available_questions = json.load(f)

    # Подбираем вопросы
    suggested_questions = await llm_service.suggest_questions_for_vacancy(
        detected_tags=detected_tags,
        grade=vacancy_data.grade,
        available_questions=available_questions,
        limit=MAX_QUESTIONS_PER_INTERVIEW
    )

    # Добавляем вопросы к вакансии
    for idx, q in enumerate(suggested_questions):
        # Проверяем, есть ли вопрос уже в БД
        existing_question = db.query(Question).filter(Question.question_text == q['question']).first()
        if not existing_question:
            existing_question = Question(
                question_text=q['question'],
                tags=q.get('tags', []),
                competency=q.get('competency', ''),
                reference_answer=q.get('reference_answer', ''),
                must_have=q.get('must_have', []),
                nice_to_have=q.get('nice_to_have', []),
                red_flags=q.get('red_flags', [])
            )
            db.add(existing_question)
            db.commit()
            db.refresh(existing_question)

        session_question = SessionQuestion(
            vacancy_id=new_vacancy.id,
            question_id=existing_question.id,
            order_index=idx
        )
        db.add(session_question)

    db.commit()

    return {
        "id": new_vacancy.id,
        "title": new_vacancy.title,
        "detected_tags": detected_tags,
        "suggested_questions_count": len(suggested_questions)
    }


@app.get("/api/vacancies/{vacancy_id}", response_class=JSONResponse)
async def get_vacancy_details(
    vacancy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Детали вакансии с вопросами"""
    vacancy = db.query(Vacancy).filter(Vacancy.id == vacancy_id).first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    session_questions = db.query(SessionQuestion).filter(
        SessionQuestion.vacancy_id == vacancy_id
    ).order_by(SessionQuestion.order_index).all()

    questions = []
    for sq in session_questions:
        q = db.query(Question).filter(Question.id == sq.question_id).first()
        questions.append({
            "session_question_id": sq.id,
            "id": q.id,
            "question": q.question_text,
            "tags": q.tags,
            "competency": q.competency
        })

    # Получаем сессии (кандидатов) для этой вакансии
    sessions = db.query(InterviewSession).filter(
        InterviewSession.vacancy_id == vacancy_id
    ).all()
    
    sessions_data = [
        {
            "id": s.id,
            "candidate_name": s.candidate_name,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None
        }
        for s in sessions
    ]

    return {
        "id": vacancy.id,
        "title": vacancy.title,
        "description": vacancy.description,
        "requirements": vacancy.requirements,
        "grade": vacancy.grade,
        "detected_tags": vacancy.detected_tags,
        "questions": questions,
        "sessions": sessions_data
    }


@app.post("/api/vacancies/{vacancy_id}/approve-questions", response_class=JSONResponse)
async def approve_vacancy_questions(
    vacancy_id: int,
    question_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Аппрув финального списка вопросов для вакансии"""
    vacancy = db.query(Vacancy).filter(Vacancy.id == vacancy_id).first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    # Обновляем список вопросов (удаляем старые, добавляем новые)
    db.query(SessionQuestion).filter(SessionQuestion.vacancy_id == vacancy_id).delete()

    for idx, q_id in enumerate(question_ids):
        session_question = SessionQuestion(
            vacancy_id=vacancy_id,
            question_id=q_id,
            order_index=idx,
            is_approved=True
        )
        db.add(session_question)

    db.commit()

    return {"message": "Вопросы успешно аппрувлены", "count": len(question_ids)}


@app.post("/api/interviews/create", response_class=JSONResponse)
async def create_interview_session(
    interview_data: InterviewStart,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание сессии интервью для кандидата"""
    vacancy = db.query(Vacancy).filter(Vacancy.id == interview_data.vacancy_id).first()
    if not vacancy:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    # Генерируем уникальный токен
    session_token = str(uuid.uuid4())

    new_session = InterviewSession(
        vacancy_id=interview_data.vacancy_id,
        candidate_name=interview_data.candidate_name,
        session_token=session_token,
        status="pending"
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Формируем ссылку для кандидата
    interview_url = f"/interview/{session_token}"

    return {
        "session_id": new_session.id,
        "session_token": session_token,
        "interview_url": interview_url,
        "candidate_name": interview_data.candidate_name
    }


@app.get("/api/interviews/{session_token}", response_class=JSONResponse)
async def get_interview_session(session_token: str, db: Session = Depends(get_db)):
    """Получение информации о сессии интервью (для кандидата)"""
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    if session.status == "completed":
        raise HTTPException(status_code=400, detail="Интервью уже завершено")

    # Получаем вопросы для этой сессии
    session_questions = db.query(SessionQuestion).filter(
        SessionQuestion.vacancy_id == session.vacancy_id
    ).order_by(SessionQuestion.order_index).all()

    questions = []
    for sq in session_questions:
        q = db.query(Question).filter(Question.id == sq.question_id).first()
        questions.append({
            "session_question_id": sq.id,
            "question": q.question_text
        })

    return {
        "session_id": session.id,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title,
        "questions": questions,
        "time_limit": ANSWER_TIME_LIMIT_SECONDS
    }


@app.post("/api/interviews/{session_token}/start", response_class=JSONResponse)
async def start_interview(session_token: str, db: Session = Depends(get_db)):
    """Начало интервью"""
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session.status = "in_progress"
    session.started_at = datetime.utcnow()
    db.commit()

    return {"message": "Интервью начато", "session_id": session.id}


@app.post("/api/interviews/submit-answer", response_class=JSONResponse)
async def submit_answer(
    session_id: int,
    question_id: int,
    transcript: str,
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    """Отправка ответа кандидата (видео + транскрипт)"""
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    # Сохраняем файл если есть
    video_path = None
    audio_path = None
    if file:
        file_extension = Path(file.filename).suffix if file.filename else ".webm"
        video_filename = f"answer_{session_id}_{question_id}{file_extension}"
        video_path = str(UPLOAD_DIR / video_filename)

        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Для MVP считаем что видео содержит и аудио
        audio_path = video_path

    # Находим session_question
    session_question = db.query(SessionQuestion).filter(
        SessionQuestion.id == question_id,
        SessionQuestion.vacancy_id == session.vacancy_id
    ).first()

    if not session_question:
        raise HTTPException(status_code=404, detail="Вопрос не найден")

    question = db.query(Question).filter(Question.id == session_question.question_id).first()

    # Создаем запись ответа
    answer = Answer(
        session_id=session_id,
        session_question_id=question_id,
        question_text=question.question_text,
        video_path=video_path,
        audio_path=audio_path,
        transcript_raw=transcript,
        transcript_corrected=transcript,
        is_approved_by_candidate=True
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    # Асинхронно запускаем анализ ответа
    # (в реальном приложении это было бы через Celery/RQ)
    import asyncio
    asyncio.create_task(analyze_answer_background(answer.id, db))

    return {
        "answer_id": answer.id,
        "message": "Ответ сохранен"
    }


async def analyze_answer_background(answer_id: int, db: Session):
    """Фоновый анализ ответа"""
    try:
        answer = db.query(Answer).filter(Answer.id == answer_id).first()
        if not answer:
            return

        # Получаем вопрос
        session_question = db.query(SessionQuestion).filter(
            SessionQuestion.id == answer.session_question_id
        ).first()
        question = db.query(Question).filter(Question.id == session_question.question_id).first()

        # Анализируем ответ
        analysis = await llm_service.analyze_answer(
            question=question.question_text,
            reference_answer=question.reference_answer,
            must_have=question.must_have or [],
            nice_to_have=question.nice_to_have or [],
            red_flags=question.red_flags or [],
            candidate_transcript=answer.transcript_corrected
        )

        # Сохраняем результат
        answer.score = analysis.get('score', 5.0)
        answer.llm_analysis = analysis
        db.commit()

    except Exception as e:
        print(f"Ошибка анализа ответа {answer_id}: {e}")


@app.post("/api/interviews/{session_id}/complete", response_class=JSONResponse)
async def complete_interview(session_id: int, db: Session = Depends(get_db)):
    """Завершение интервью и генерация итогового отчета"""
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    session.status = "completed"
    session.completed_at = datetime.utcnow()
    db.commit()

    # Генерируем итоговый отчет
    answers = db.query(Answer).filter(Answer.session_id == session_id).all()

    answers_data = []
    for ans in answers:
        answers_data.append({
            "question": ans.question_text,
            "transcript": ans.transcript_corrected,
            "score": ans.score,
            "analysis": ans.llm_analysis.get('analysis', '') if ans.llm_analysis else '',
            "strengths": ans.llm_analysis.get('strengths', []) if ans.llm_analysis else [],
            "weaknesses": ans.llm_analysis.get('weaknesses', []) if ans.llm_analysis else []
        })

    report_data = await llm_service.generate_final_report(
        vacancy_title=session.vacancy.title,
        vacancy_requirements=session.vacancy.requirements,
        answers_data=answers_data
    )

    # Создаем отчет
    final_report = FinalReport(
        session_id=session_id,
        overall_score=report_data.get('overall_score', 5.0),
        recommendation=report_data.get('recommendation', 'требуется дополнительная проверка'),
        summary=report_data.get('summary', ''),
        strengths=report_data.get('strengths', []),
        weaknesses=report_data.get('weaknesses', []),
        detected_skills=report_data.get('detected_skills', []),
        areas_to_check=report_data.get('areas_to_check', []),
        risk_factors=report_data.get('risk_factors', [])
    )
    db.add(final_report)
    db.commit()

    return {
        "message": "Интервью завершено, отчет сгенерирован",
        "report_id": final_report.id
    }


@app.get("/api/reports/{session_id}", response_class=JSONResponse)
async def get_report(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение итогового отчета по интервью"""
    report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    # Получаем ответы
    answers = db.query(Answer).filter(Answer.session_id == session_id).all()
    answers_data = []
    for ans in answers:
        answers_data.append({
            "question": ans.question_text,
            "transcript": ans.transcript_corrected,
            "score": ans.score,
            "video_path": f"/{ans.video_path}" if ans.video_path else None,
            "analysis": ans.llm_analysis
        })

    return {
        "id": report.id,
        "session_id": report.session_id,
        "candidate_name": report.interview_session.candidate_name,
        "vacancy_title": report.interview_session.vacancy.title,
        "overall_score": report.overall_score,
        "recommendation": report.recommendation,
        "summary": report.summary,
        "strengths": report.strengths,
        "weaknesses": report.weaknesses,
        "detected_skills": report.detected_skills,
        "areas_to_check": report.areas_to_check,
        "risk_factors": report.risk_factors,
        "answers": answers_data,
        "generated_at": report.generated_at.isoformat()
    }


@app.get("/interview/{session_token}", response_class=HTMLResponse)
async def interview_page(session_token: str, request: Request, db: Session = Depends(get_db)):
    """Страница прохождения интервью для кандидата"""
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    return templates.TemplateResponse("interview.html", {
        "request": request,
        "session_token": session_token,
        "candidate_name": session.candidate_name,
        "vacancy_title": session.vacancy.title
    })


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(current_user: User = Depends(get_current_user)):
    """Дашборд для HR/менеджера"""
    return templates.TemplateResponse("dashboard.html", {
        "request": {},
        "user": current_user
    })


@app.get("/report/{session_id}", response_class=HTMLResponse)
async def report_page(session_id: int, request: Request, db: Session = Depends(get_db)):
    """Страница просмотра отчета"""
    report = db.query(FinalReport).filter(FinalReport.session_id == session_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Отчет не найден")

    return templates.TemplateResponse("report.html", {
        "request": request,
        "report": report,
        "session_id": session_id
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
