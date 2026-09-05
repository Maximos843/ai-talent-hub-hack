"""Additive persistence for adaptive follow-up interview questions."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text

from database import Base


class QuestionProbeConfig(Base):
    __tablename__ = "question_probe_configs"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), unique=True, nullable=False, index=True)
    possible_extra_questions = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InterviewQuestionProbeConfig(Base):
    __tablename__ = "interview_question_probe_configs"

    id = Column(Integer, primary_key=True, index=True)
    interview_question_id = Column(Integer, ForeignKey("interview_questions.id"), unique=True, nullable=False, index=True)
    possible_extra_questions = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class AnswerQuestionLink(Base):
    __tablename__ = "answer_question_links"

    id = Column(Integer, primary_key=True, index=True)
    answer_id = Column(Integer, ForeignKey("answers.id"), unique=True, nullable=False, index=True)
    interview_question_id = Column(Integer, ForeignKey("interview_questions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AdaptiveProbeDecision(Base):
    __tablename__ = "adaptive_probe_decisions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    root_interview_question_id = Column(Integer, ForeignKey("interview_questions.id"), nullable=False, index=True)
    trigger_answer_id = Column(Integer, ForeignKey("answers.id"), unique=True, nullable=False, index=True)
    follow_up_question_id = Column(Integer, ForeignKey("interview_questions.id"), nullable=True, index=True)
    follow_up_count_before = Column(Integer, nullable=False, default=0)
    ask_follow_up = Column(Boolean, nullable=False, default=False)
    reason = Column(Text)
    focus = Column(Text)
    source = Column(String, nullable=False, default="none")
    resolved_root_score_0_10 = Column(Float)
    confidence_0_1 = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
