"""Additive MVP tables for authentication, media metadata and browser proctoring.

They intentionally live outside database.py so the current hackathon database can
be upgraded with create_all() and without destructive migrations.
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from database import Base


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_agent = Column(String)
    ip_hint = Column(String)
    revoked_at = Column(DateTime)

    user = relationship("User")


class WorkspaceInvite(Base):
    __tablename__ = "workspace_invites"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False)  # hr / hiring_manager
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime)
    used_by_id = Column(Integer, ForeignKey("users.id"))

    created_by = relationship("User", foreign_keys=[created_by_id])
    used_by = relationship("User", foreign_keys=[used_by_id])


class FullInterviewMedia(Base):
    """Durable metadata for the continuous interview recording.

    Browser MediaRecorder containers may not expose duration reliably to ffprobe.
    We therefore persist the best duration known at upload time and remember
    whether it came from a server probe or the browser timeline. This is a
    technical playback hint only; it is never an authenticity judgment.
    """

    __tablename__ = "full_interview_media"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), unique=True, nullable=False, index=True)
    path = Column(String, nullable=False)
    duration_ms = Column(Integer)
    size_bytes = Column(Integer)
    duration_source = Column(String, nullable=False, default="unknown")  # server_probe / client_reported / answer_timeline / unknown
    normalized = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    interview_session = relationship("InterviewSession")


class ProctorEvent(Base):
    """Low-risk browser integrity signal.

    Events are evidence for human review only. They never alter the technical
    score or automatically classify a candidate as cheating.
    """

    __tablename__ = "proctor_events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("interview_sessions.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    client_ts_ms = Column(Integer)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    interview_session = relationship("InterviewSession")
