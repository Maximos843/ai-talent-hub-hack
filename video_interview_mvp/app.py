"""Secure-ish MVP gateway around the existing FastAPI application.

The legacy application still owns the interview/business routes. This gateway
adds server-side auth sessions and proctoring without a risky rewrite of the
working hackathon flow. For authenticated legacy routes it injects an internal
Basic header only after a valid HttpOnly session cookie has been resolved.
Browser code never stores user passwords anymore.
"""
from __future__ import annotations

import base64
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Template
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import database
import mvp_models  # noqa: F401 - registers additive SQLAlchemy tables before create_all
from database import InterviewSession, User, Vacancy, get_db
from mvp_models import ProctorEvent, WorkspaceInvite
from services.auth_service import (
    INVITE_TTL_HOURS,
    SESSION_COOKIE,
    SESSION_TTL_HOURS,
    consume_invite,
    create_invite,
    create_session,
    hash_password,
    resolve_session,
    revoke_session,
    verify_password,
)

# Import after mvp_models so main.init_db() creates the additive tables as well.
import main as legacy_main


database.init_db()
legacy_app = legacy_main.app
BASE_DIR = Path(__file__).parent

app = FastAPI(title="Talent Interview MVP", version="1.5.0")


class LoginPayload(BaseModel):
    username: str
    password: str


class RegisterPayload(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    invite_code: Optional[str] = ""
    role: Optional[str] = "hr"  # only used for the first bootstrap account


class InvitePayload(BaseModel):
    role: str


class ProctorEventPayload(BaseModel):
    type: str
    client_ts_ms: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProctorBatchPayload(BaseModel):
    events: List[ProctorEventPayload] = Field(default_factory=list, max_length=30)


PUBLIC_LEGACY_API = {
    ("POST", "/api/interviews/submit-answer"),
    ("POST", "/api/interviews/correct-transcript"),
}


def _looks_like_candidate_api(method: str, path: str) -> bool:
    if (method, path) in PUBLIC_LEGACY_API:
        return True
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3 or parts[:2] != ["api", "interviews"]:
        return False
    tail = parts[2:]
    # GET /api/interviews/{uuid}; POST .../{uuid}/start
    if method == "GET" and len(tail) == 1 and "-" in tail[0]:
        return True
    if method == "POST" and len(tail) == 2 and "-" in tail[0] and tail[1] == "start":
        return True
    # POST /api/interviews/{numeric_session}/full-video|complete
    if method == "POST" and len(tail) == 2 and tail[0].isdigit() and tail[1] in {"full-video", "complete"}:
        return True
    return False


def _session_user(request: Request, db: Session) -> Optional[User]:
    session = resolve_session(db, request.cookies.get(SESSION_COOKIE))
    return session.user if session else None


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Сессия истекла. Войдите снова.")
    return user


def require_hr(user: User = Depends(require_user)) -> User:
    if user.role != "hr":
        raise HTTPException(status_code=403, detail="Действие доступно только HR")
    return user


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def _inject_internal_basic(request: Request, user: User) -> None:
    """Satisfy legacy HTTPBasic dependencies without exposing credentials.

    The header exists only inside this ASGI request after the opaque session has
    already been authenticated by this gateway.
    """
    raw = f"{user.username}:{user.password_hash}".encode("utf-8")
    value = b"Basic " + base64.b64encode(raw)
    headers = [(key, val) for key, val in request.scope.get("headers", []) if key.lower() != b"authorization"]
    headers.append((b"authorization", value))
    request.scope["headers"] = headers


@app.middleware("http")
async def session_gateway(request: Request, call_next):
    path = request.url.path
    method = request.method.upper()
    db = database.SessionLocal()
    try:
        user = _session_user(request, db)
        if user:
            _inject_internal_basic(request, user)
        elif path.startswith("/api/"):
            is_outer_public = path.startswith("/api/auth/") or "/proctor-events" in path
            if not is_outer_public and not _looks_like_candidate_api(method, path):
                return JSONResponse({"detail": "Требуется авторизация"}, status_code=401)
        return await call_next(request)
    finally:
        db.close()


@app.get("/api/auth/bootstrap-status")
async def bootstrap_status(db: Session = Depends(get_db)):
    return {"bootstrap_required": db.query(User).count() == 0}


@app.post("/api/auth/login")
async def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    valid, upgraded = verify_password(payload.password, user.password_hash)
    if not valid:
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    if upgraded:
        user.password_hash = upgraded
        db.commit()
        db.refresh(user)

    token, _ = create_session(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ip_hint=request.client.host if request.client else "",
    )
    response = JSONResponse({"username": user.username, "role": user.role, "full_name": user.full_name})
    _set_session_cookie(response, token, request)
    return response


@app.get("/api/auth/me")
async def me(user: User = Depends(require_user)):
    return {"username": user.username, "role": user.role, "full_name": user.full_name}


@app.post("/api/auth/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    revoke_session(db, request.cookies.get(SESSION_COOKIE))
    response = JSONResponse({"message": "Сессия завершена"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.post("/api/auth/register")
async def register(payload: RegisterPayload, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Логин должен содержать минимум 3 символа")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    first_user = db.query(User).count() == 0
    invite: Optional[WorkspaceInvite] = None
    if first_user:
        role = "hr"
    else:
        invite = consume_invite(db, (payload.invite_code or "").strip())
        if not invite:
            raise HTTPException(status_code=403, detail="Приглашение недействительно, использовано или истекло")
        role = invite.role

    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    user = User(
        username=username,
        password_hash=password_hash,
        role=role,
        full_name=(payload.full_name or "").strip(),
    )
    db.add(user)
    db.flush()
    if invite:
        invite.used_at = datetime.utcnow()
        invite.used_by_id = user.id
    db.commit()
    db.refresh(user)

    token, _ = create_session(
        db,
        user,
        user_agent=request.headers.get("user-agent", ""),
        ip_hint=request.client.host if request.client else "",
    )
    response = JSONResponse({"username": user.username, "role": user.role, "full_name": user.full_name})
    _set_session_cookie(response, token, request)
    return response


@app.post("/api/auth/invitations")
async def new_invitation(payload: InvitePayload, request: Request, user: User = Depends(require_hr), db: Session = Depends(get_db)):
    if payload.role not in {"hr", "hiring_manager"}:
        raise HTTPException(status_code=400, detail="Выберите HR или нанимающего менеджера")
    token, invite = create_invite(db, payload.role, user.id)
    base = str(request.base_url).rstrip("/")
    return {
        "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
        "expires_in_hours": INVITE_TTL_HOURS,
        "invite_url": f"{base}/register?invite={token}",
    }


ALLOWED_PROCTOR_EVENTS = {
    "tab_hidden",
    "tab_visible",
    "window_blur",
    "window_focus",
    "clipboard_copy",
    "clipboard_cut",
    "clipboard_paste",
    "fullscreen_enter",
    "fullscreen_exit",
    "network_offline",
    "network_online",
    "camera_ended",
    "microphone_ended",
}


def _clean_proctor_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Whitelist non-content metadata. Never accept clipboard text or keystrokes."""
    clean: dict[str, Any] = {}
    for key in ("duration_ms", "question_index", "answer_recording", "visibility_state"):
        if key not in data:
            continue
        value = data[key]
        if key in {"duration_ms", "question_index"}:
            try:
                clean[key] = max(0, min(int(value), 3_600_000))
            except (TypeError, ValueError):
                continue
        elif key == "answer_recording":
            clean[key] = bool(value)
        elif key == "visibility_state":
            clean[key] = str(value)[:30]
    return clean


@app.post("/api/interviews/{session_token}/proctor-events")
async def save_proctor_events(session_token: str, payload: ProctorBatchPayload, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Интервью не найдено")
    if not session.started_at or session.final_report:
        # The client can race with /start or /complete; silently ignore rather than
        # break the interview for a non-critical telemetry feature.
        return {"accepted": 0}

    accepted = 0
    for event in payload.events[:30]:
        if event.type not in ALLOWED_PROCTOR_EVENTS:
            continue
        db.add(
            ProctorEvent(
                session_id=session.id,
                event_type=event.type,
                client_ts_ms=event.client_ts_ms,
                metadata_json=_clean_proctor_metadata(event.metadata),
            )
        )
        accepted += 1
    if accepted:
        db.commit()
    return {"accepted": accepted}


def _proctor_summary(session_id: int, db: Session) -> dict[str, Any]:
    events = (
        db.query(ProctorEvent)
        .filter(ProctorEvent.session_id == session_id)
        .order_by(ProctorEvent.created_at, ProctorEvent.id)
        .all()
    )
    counts = Counter(event.event_type for event in events)
    hidden_ms = sum(
        int((event.metadata_json or {}).get("duration_ms") or 0)
        for event in events
        if event.event_type == "tab_visible"
    )
    blur_ms = sum(
        int((event.metadata_json or {}).get("duration_ms") or 0)
        for event in events
        if event.event_type == "window_focus"
    )
    return {
        "total_events": len(events),
        "tab_switches": counts["tab_hidden"],
        "tab_hidden_duration_ms": hidden_ms,
        "window_blurs": counts["window_blur"],
        "window_blur_duration_ms": blur_ms,
        "clipboard_pastes": counts["clipboard_paste"],
        "clipboard_copies": counts["clipboard_copy"],
        "fullscreen_exits": counts["fullscreen_exit"],
        "network_interruptions": counts["network_offline"],
        "media_interruptions": counts["camera_ended"] + counts["microphone_ended"],
        "disclaimer": "Сигналы прокторинга не являются доказательством нарушения и не влияют на технический score.",
        "events": [
            {
                "type": event.event_type,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "metadata": event.metadata_json or {},
            }
            for event in events[-100:]
        ],
    }


@app.get("/api/proctoring/{session_id}/summary")
async def proctoring_summary(session_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    session = db.query(InterviewSession).join(Vacancy).filter(InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    if user.role == "hr" and session.vacancy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Кандидат не найден")
    if user.role == "hiring_manager" and not legacy_main._manager_can_view(session):
        raise HTTPException(status_code=404, detail="Кандидат ещё не передан нанимающему менеджеру")
    return _proctor_summary(session_id, db)


def _html_with_bridge(path: Path, user: User) -> str:
    text = path.read_text(encoding="utf-8")
    bootstrap = (
        "<script>"
        "localStorage.setItem('auth','cookie-session');"
        f"localStorage.setItem('user',JSON.stringify({json.dumps({'username': user.username, 'role': user.role, 'full_name': user.full_name}, ensure_ascii=False)}));"
        "</script>"
    )
    text = text.replace("</head>", bootstrap + "</head>", 1)
    return text.replace("</body>", '<script src="/static/session_bridge.js"></script></body>', 1)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _session_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(_html_with_bridge(BASE_DIR / "templates" / "dashboard.html", user))


@app.get("/report/{session_id}", response_class=HTMLResponse)
async def report_page(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _session_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
    if not session or not session.final_report:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    if user.role == "hr" and session.vacancy.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    if user.role == "hiring_manager" and not legacy_main._manager_can_view(session):
        raise HTTPException(status_code=404, detail="Отчёт не найден")
    return HTMLResponse(_html_with_bridge(BASE_DIR / "templates" / "report.html", user))


@app.get("/interview/{session_token}", response_class=HTMLResponse)
async def candidate_interview(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Интервью не найдено")
    source = (BASE_DIR / "templates" / "interview.html").read_text(encoding="utf-8")
    notice = """
    <div id="proctorNotice" style="margin:14px 0 0;padding:13px 14px;border:1px solid #e5e1ff;background:#faf9ff;border-radius:14px;font-size:12px;line-height:1.55;color:#5f6072">
      <b style="color:#3e3f4c">Во время интервью включён базовый прокторинг.</b>
      Мы фиксируем переключение/скрытие вкладки, потерю фокуса окна, clipboard actions, выход из полноэкранного режима и технические разрывы камеры/сети. Содержимое буфера обмена и нажатия клавиш не записываются. Эти сигналы видит человек и они не входят в технический score.
    </div>
    """
    source = source.replace("</div></div></section>\n<section id=\"device\"", notice + "</div></div></section>\n<section id=\"device\"", 1)
    injection = (
        f"<script>window.__INTERVIEW_TOKEN__={json.dumps(session_token)};</script>"
        '<script src="/static/proctor.js"></script>'
    )
    source = source.replace("</body>", injection + "</body>", 1)
    return HTMLResponse(
        Template(source).render(
            session_token=session_token,
            candidate_name=session.candidate_name,
            vacancy_title=session.vacancy.title,
        )
    )


# Keep all existing business routes and static mounts as a fallback.
app.mount("/", legacy_app)
