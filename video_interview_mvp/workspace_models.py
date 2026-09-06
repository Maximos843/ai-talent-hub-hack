"""Аддитивные таблицы рабочего места рекрутера.

Резюме кандидата и разбор вакансии живут отдельно от боевых таблиц интервью,
поэтому существующие базы обновляются обычным ``create_all`` без миграций.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import backref, relationship

from database import Base


class CandidateProfile(Base):
    """Резюме кандидата и его разбор относительно требований вакансии."""

    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), unique=True, nullable=False, index=True)
    resume_filename = Column(String)
    resume_path = Column(String)
    resume_text = Column(Text)
    # Контакты для доставки ссылки на интервью.
    # telegram_username хранится для справки рекрутера; писать боту первым нельзя,
    # поэтому доставка идёт через deep-link: кандидат жмёт Start, бот получает
    # chat_id и дальше сам шлёт ссылку и напоминания.
    email = Column(String)
    telegram_username = Column(String)
    telegram_chat_id = Column(String)
    telegram_linked_at = Column(DateTime)
    # Разбор резюме: должности, годы опыта, стек, ссылки
    parsed = Column(JSON)
    # Соответствие вакансии: 0..10 + обоснование и разбивка по требованиям
    match_score = Column(Float)
    match_summary = Column(Text)
    match_details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    interview_session = relationship("InterviewSession", backref=backref("profile", uselist=False, cascade="all, delete-orphan"))


class VacancyProfile(Base):
    """Структурированный разбор текста вакансии, сделанный LLM.

    Хранится отдельно от ``Vacancy``, потому что рекрутер правит разбор руками:
    исходный текст должен оставаться неизменным для повторного прогона.
    """

    __tablename__ = "vacancy_profiles"

    id = Column(Integer, primary_key=True, index=True)
    vacancy_id = Column(Integer, ForeignKey("vacancies.id"), unique=True, nullable=False, index=True)
    source_filename = Column(String)
    must_have = Column(JSON)      # [{"skill": str, "weight": int, "evidence": str}]
    nice_to_have = Column(JSON)
    stop_factors = Column(JSON)
    responsibilities = Column(JSON)
    summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vacancy = relationship("Vacancy", backref=backref("profile", uselist=False, cascade="all, delete-orphan"))
