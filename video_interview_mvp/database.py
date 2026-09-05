"""Database models for the AI interview MVP."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from config import DATABASE_URL


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # hr / hiring_manager
    full_name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    vacancies = relationship("Vacancy", back_populates="owner")
    accessed_reports = relationship("FinalReport", back_populates="accessed_by")
    review_decisions = relationship("ReviewDecision", back_populates="reviewer")


class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    requirements = Column(Text)
    grade = Column(String)
    detected_tags = Column(JSON)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    owner = relationship("User", back_populates="vacancies")
    session_questions = relationship("SessionQuestion", back_populates="vacancy")
    interview_sessions = relationship("InterviewSession", back_populates="vacancy")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    question_text = Column(Text, nullable=False)
    tags = Column(JSON)
    competency = Column(String)
    reference_answer = Column(Text)
    must_have = Column(JSON)
    nice_to_have = Column(JSON)
    red_flags = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    session_questions = relationship("SessionQuestion", back_populates="question")


class SessionQuestion(Base):
    """Vacancy-level question pool.

    This is the reusable default pool for all candidates on a vacancy. HR can
    approve/reject entries here. Candidate-specific copies live in
    ``InterviewQuestion`` and can diverge safely from this pool.
    """

    __tablename__ = "session_questions"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    order_index = Column(Integer, default=0)
    is_approved = Column(Boolean, default=True)

    vacancy = relationship("Vacancy", back_populates="session_questions")
    question = relationship("Question", back_populates="session_questions")
    answers = relationship("Answer", back_populates="session_question")
    interview_questions = relationship("InterviewQuestion", back_populates="source_session_question")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"))
    candidate_name = Column(String)
    session_token = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="pending")
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    vacancy = relationship("Vacancy", back_populates="interview_sessions")
    answers = relationship("Answer", back_populates="interview_session")
    final_report = relationship("FinalReport", uselist=False, back_populates="interview_session")
    interview_questions = relationship(
        "InterviewQuestion",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        order_by="InterviewQuestion.order_index",
    )
    review_decisions = relationship(
        "ReviewDecision",
        back_populates="interview_session",
        cascade="all, delete-orphan",
        order_by="ReviewDecision.reviewed_at",
    )


class InterviewQuestion(Base):
    """Frozen/editable question set for one candidate interview."""

    __tablename__ = "interview_questions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    source_session_question_id = Column(Integer, ForeignKey("session_questions.id"), nullable=True)
    question_text = Column(Text, nullable=False)
    competency = Column(String)
    reference_answer = Column(Text)
    must_have = Column(JSON)
    nice_to_have = Column(JSON)
    red_flags = Column(JSON)
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_custom = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    interview_session = relationship("InterviewSession", back_populates="interview_questions")
    source_session_question = relationship("SessionQuestion", back_populates="interview_questions")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"))
    session_question_id = Column(Integer, ForeignKey("session_questions.id"), nullable=True)
    question_text = Column(Text)
    video_path = Column(String)
    audio_path = Column(String)
    transcript_raw = Column(Text)
    transcript_corrected = Column(Text)
    score = Column(Float)
    llm_analysis = Column(JSON)
    is_approved_by_candidate = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    interview_session = relationship("InterviewSession", back_populates="answers")
    session_question = relationship("SessionQuestion", back_populates="answers")


class FinalReport(Base):
    __tablename__ = "final_reports"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), unique=True)
    overall_score = Column(Float)
    recommendation = Column(String)
    summary = Column(Text)
    strengths = Column(JSON)
    weaknesses = Column(JSON)
    detected_skills = Column(JSON)
    areas_to_check = Column(JSON)
    risk_factors = Column(JSON)
    generated_at = Column(DateTime, default=datetime.utcnow)

    interview_session = relationship("InterviewSession", back_populates="final_report")
    accessed_by_id = Column(Integer, ForeignKey("users.id"))
    accessed_by = relationship("User", back_populates="accessed_reports")


class ReviewDecision(Base):
    """Human approval chain for an interview result.

    HR always reviews first. A hiring manager can make the final decision only
    after HR has explicitly approved the candidate for the next stage.
    """

    __tablename__ = "review_decisions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewer_role = Column(String, nullable=False)
    decision = Column(String, nullable=False)  # approve / reject / needs_review
    comment = Column(Text)
    reviewed_at = Column(DateTime, default=datetime.utcnow)

    interview_session = relationship("InterviewSession", back_populates="review_decisions")
    reviewer = relationship("User", back_populates="review_decisions")


# New functionality is stored in new tables, so create_all is enough and does
# not require a destructive migration for existing hackathon SQLite databases.
def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
