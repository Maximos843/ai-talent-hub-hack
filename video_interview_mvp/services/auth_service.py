"""Authentication primitives for the hackathon MVP.

The browser receives only an opaque HttpOnly session id.  Passwords use
PBKDF2-HMAC-SHA256 and invitation/session tokens are stored only as SHA-256
hashes.  The helpers deliberately stay dependency-free so the auth layer is
predictable inside the small FastAPI MVP.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from database import User
from mvp_models import AuthSession, WorkspaceInvite


PASSWORD_ITERATIONS = 310_000
SESSION_TTL_HOURS = 8
INVITE_TTL_HOURS = 48
SESSION_COOKIE = "ti_session"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _encode_password(password: str) -> str:
    """Encode a password without applying new-account policy.

    This is intentionally separate from ``hash_password``.  Old hackathon
    databases may contain plaintext passwords shorter than today's 8-character
    policy.  A successful legacy login must still be able to migrate that
    password to PBKDF2 instead of crashing with ValueError.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("Пароль должен содержать минимум 8 символов")
    return _encode_password(password)


def verify_password(password: str, stored: str) -> tuple[bool, Optional[str]]:
    """Verify a password and optionally return an upgraded hash.

    Existing databases from the previous MVP stored passwords as plaintext.
    They are upgraded transparently after the first successful login, including
    old passwords shorter than the new-account minimum length.
    """
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
            iterations = int(iterations_raw)
            salt = base64.urlsafe_b64decode(salt_raw + "=" * (-len(salt_raw) % 4))
            expected = base64.urlsafe_b64decode(digest_raw + "=" * (-len(digest_raw) % 4))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected), None
        except (ValueError, TypeError):
            return False, None

    if hmac.compare_digest(password, stored):
        return True, _encode_password(password)
    return False, None


def create_session(db: Session, user: User, user_agent: str = "", ip_hint: str = "") -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    session = AuthSession(
        token_hash=_token_hash(token),
        user_id=user.id,
        created_at=now,
        expires_at=now + timedelta(hours=SESSION_TTL_HOURS),
        last_seen_at=now,
        user_agent=(user_agent or "")[:500],
        ip_hint=(ip_hint or "")[:120],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return token, session


def resolve_session(db: Session, token: Optional[str]) -> Optional[AuthSession]:
    if not token:
        return None
    now = datetime.utcnow()
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == _token_hash(token), AuthSession.revoked_at.is_(None))
        .first()
    )
    if not session or session.expires_at <= now:
        return None
    if not session.last_seen_at or (now - session.last_seen_at).total_seconds() > 300:
        session.last_seen_at = now
        db.commit()
    return session


def revoke_session(db: Session, token: Optional[str]) -> None:
    if not token:
        return
    session = db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(token)).first()
    if session and not session.revoked_at:
        session.revoked_at = datetime.utcnow()
        db.commit()


def create_invite(db: Session, role: str, created_by_id: int) -> tuple[str, WorkspaceInvite]:
    if role not in {"hr", "hiring_manager"}:
        raise ValueError("Неизвестная роль")
    token = secrets.token_urlsafe(24)
    now = datetime.utcnow()
    invite = WorkspaceInvite(
        token_hash=_token_hash(token),
        role=role,
        created_by_id=created_by_id,
        created_at=now,
        expires_at=now + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return token, invite


def inspect_invite(db: Session, token: str) -> Optional[WorkspaceInvite]:
    """Return an active invite without consuming it."""
    if not token:
        return None
    now = datetime.utcnow()
    invite = db.query(WorkspaceInvite).filter(WorkspaceInvite.token_hash == _token_hash(token)).first()
    if not invite or invite.used_at or invite.expires_at <= now:
        return None
    return invite


def consume_invite(db: Session, token: str) -> Optional[WorkspaceInvite]:
    return inspect_invite(db, token)
