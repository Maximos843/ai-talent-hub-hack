"""
Модели базы данных
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

from config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """Пользователи системы (HR и нанимающие менеджеры)"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'hr' или 'hiring_manager'
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    vacancies = relationship("Vacancy", back_populates="owner")
    accessed_reports = relationship("FinalReport", back_populates="accessed_by")


class Vacancy(Base):
    """Вакансии"""
    __tablename__ = "vacancies"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    grade = Column(String)  # junior, middle, senior, principal
    detected_tags = Column(JSON)  # Список обнаруженных тегов
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # Связи
    owner = relationship("User", back_populates="vacancies")
    session_questions = relationship("SessionQuestion", back_populates="vacancy")
    interview_sessions = relationship("InterviewSession", back_populates="vacancy")


class Question(Base):
    """Банк вопросов"""
    __tablename__ = "questions"
    
    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    tags = Column(JSON)  # Список тегов
    competency = Column(String)
    reference_answer = Column(Text)
    must_have = Column(JSON)
    nice_to_have = Column(JSON)
    red_flags = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    session_questions = relationship("SessionQuestion", back_populates="question")


class SessionQuestion(Base):
    """Вопросы для конкретной вакансии (после аппрува HR)"""
    __tablename__ = "session_questions"
    
    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    order_index = Column(Integer, default=0)
    is_approved = Column(Boolean, default=True)
    
    # Связи
    vacancy = relationship("Vacancy", back_populates="session_questions")
    question = relationship("Question", back_populates="session_questions")
    answers = relationship("Answer", back_populates="session_question")


class InterviewSession(Base):
    """Сессия интервью кандидата"""
    __tablename__ = "interview_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    candidate_name = Column(String)
    session_token = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="pending")  # pending, in_progress, completed, reviewed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    vacancy = relationship("Vacancy", back_populates="interview_sessions")
    answers = relationship("Answer", back_populates="interview_session")
    final_report = relationship("FinalReport", uselist=False, back_populates="interview_session")


class Answer(Base):
    """Ответы кандидата на вопросы"""
    __tablename__ = "answers"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"))
    session_question_id = Column(Integer, ForeignKey("session_questions.id"))
    question_text = Column(Text)
    video_path = Column(String)
    audio_path = Column(String)
    transcript_raw = Column(Text)
    transcript_corrected = Column(Text)
    score = Column(Float)
    llm_analysis = Column(JSON)
    is_approved_by_candidate = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    interview_session = relationship("InterviewSession", back_populates="answers")
    session_question = relationship("SessionQuestion", back_populates="answers")


class FinalReport(Base):
    """Итоговый отчет по интервью"""
    __tablename__ = "final_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), unique=True)
    overall_score = Column(Float)
    recommendation = Column(String)  # "подходит", "не подходит", "требуется дополнительная проверка"
    summary = Column(Text)
    strengths = Column(JSON)
    weaknesses = Column(JSON)
    detected_skills = Column(JSON)
    areas_to_check = Column(JSON)
    risk_factors = Column(JSON)
    generated_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    interview_session = relationship("InterviewSession", back_populates="final_report")
    accessed_by_id = Column(Integer, ForeignKey("users.id"))
    accessed_by = relationship("User", back_populates="accessed_reports")


# Создание таблиц
def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
