"""MVP gateway for server-side auth and interview proctoring.

The original FastAPI application still owns the business/interview routes. This
gateway keeps that stable flow intact while adding opaque cookie sessions,
one-time workspace invitations and non-scoring proctor signals.
"""
from __future__ import annotations

import base64
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Template
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import database
import mvp_models  # noqa: F401 - register additive SQLAlchemy tables before create_all
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
    inspect_invite,
    resolve_session,
    revoke_session,
    verify_password,
)

# Import after mvp_models so main.init_db() creates additive tables as well.
import main as legacy_main
from services.tts_service import TTSUnavailable, media_type_for, synthesize


database.init_db()
legacy_app = legacy_main.app
BASE_DIR = Path(__file__).parent
# Сборка React-рабочего места. Пока её нет, работают legacy-шаблоны.
SPA_INDEX = BASE_DIR / "static" / "app" / "index.html"

app = FastAPI(title="Talent Interview MVP", version="1.6.0")


class LoginPayload(BaseModel):
    username: str
    password: str


class RegisterPayload(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    invite_code: Optional[str] = ""
    role: Optional[str] = "hr"  # used only for first workspace bootstrap


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
    if method == "GET" and len(tail) == 1 and "-" in tail[0]:
        return True
    if method == "POST" and len(tail) == 2 and "-" in tail[0] and tail[1] in {"start", "consent"}:
        return True
    # «Ответить заново»: кандидат без авторизации удаляет свой неподтверждённый ответ.
    if method == "DELETE" and len(tail) == 2 and tail[0] == "answers" and tail[1].isdigit():
        return True
    if method == "POST" and len(tail) == 2 and tail[0].isdigit() and tail[1] in {"full-video", "complete"}:
        return True
    # Озвучка вопроса: кандидат не авторизован, но токен сессии его опознаёт.
    if method == "GET" and len(tail) == 2 and "-" in tail[0] and tail[1] == "speak":
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
    """Satisfy legacy HTTPBasic dependencies after cookie auth succeeded."""
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


@app.get("/api/auth/invite-status")
async def invite_status(token: str = "", db: Session = Depends(get_db)):
    invite = inspect_invite(db, token.strip())
    if not invite:
        return {"valid": False, "role": None, "expires_at": None}
    return {"valid": True, "role": invite.role, "expires_at": invite.expires_at.isoformat()}


@app.post("/api/auth/login")
async def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="Введите логин и пароль")
    user = db.query(User).filter(User.username == username).first()
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
            raise HTTPException(status_code=403, detail="Ссылка приглашения недействительна, уже использована или истекла")
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
    "vision_ready",
    "vision_unavailable",
    "face_missing",
    "face_returned",
    "multiple_faces",
    "single_face_returned",
    "head_away",
    "head_returned",
    "gaze_away",
    "gaze_returned",
}


def _clean_proctor_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Whitelist non-content metadata. Images, clipboard text and keys are rejected."""
    clean: dict[str, Any] = {}
    numeric = {"duration_ms", "question_index", "face_count", "sample_fps"}
    booleans = {"answer_recording"}
    strings = {"visibility_state", "reason", "direction", "delegate"}
    for key in numeric | booleans | strings:
        if key not in data:
            continue
        value = data[key]
        if key in numeric:
            try:
                ceiling = 3_600_000 if key == "duration_ms" else 100
                clean[key] = max(0, min(int(value), ceiling))
            except (TypeError, ValueError):
                continue
        elif key in booleans:
            clean[key] = bool(value)
        else:
            clean[key] = str(value)[:80]
    return clean


@app.post("/api/interviews/{session_token}/proctor-events")
async def save_proctor_events(session_token: str, payload: ProctorBatchPayload, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Интервью не найдено")
    if not session.started_at or session.final_report:
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


def _duration_for(events: list[ProctorEvent], event_type: str) -> int:
    return sum(
        int((event.metadata_json or {}).get("duration_ms") or 0)
        for event in events
        if event.event_type == event_type
    )


def _proctor_summary(session_id: int, db: Session) -> dict[str, Any]:
    events = (
        db.query(ProctorEvent)
        .filter(ProctorEvent.session_id == session_id)
        .order_by(ProctorEvent.created_at, ProctorEvent.id)
        .all()
    )
    counts = Counter(event.event_type for event in events)
    vision_available = counts["vision_ready"] > 0 and counts["vision_unavailable"] == 0
    return {
        "total_events": len(events),
        "tab_switches": counts["tab_hidden"],
        "tab_hidden_duration_ms": _duration_for(events, "tab_visible"),
        "window_blurs": counts["window_blur"],
        "window_blur_duration_ms": _duration_for(events, "window_focus"),
        "clipboard_pastes": counts["clipboard_paste"],
        "clipboard_copies": counts["clipboard_copy"],
        "fullscreen_exits": counts["fullscreen_exit"],
        "network_interruptions": counts["network_offline"],
        "media_interruptions": counts["camera_ended"] + counts["microphone_ended"],
        "vision_available": vision_available,
        "vision_unavailable": counts["vision_unavailable"],
        "face_missing_episodes": counts["face_missing"],
        "face_missing_duration_ms": _duration_for(events, "face_returned"),
        "multiple_faces_episodes": counts["multiple_faces"],
        "multiple_faces_duration_ms": _duration_for(events, "single_face_returned"),
        "head_away_episodes": counts["head_away"],
        "head_away_duration_ms": _duration_for(events, "head_returned"),
        "gaze_away_episodes": counts["gaze_away"],
        "gaze_away_duration_ms": _duration_for(events, "gaze_returned"),
        "disclaimer": "Прокторинг — вспомогательные сигналы для ручной проверки. Они не доказывают нарушение и не влияют на технический score.",
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
    """Старый маршрут ведёт в новое рабочее место.

    Обе роли работают в React-приложении, а legacy-шаблон остаётся только как
    фолбэк на случай, если сборка фронтенда недоступна.
    """
    user = _session_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if SPA_INDEX.is_file():
        return RedirectResponse("/app", status_code=303)
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
    if SPA_INDEX.is_file():
        return RedirectResponse(f"/app/reports/{session_id}", status_code=303)
    return HTMLResponse(_html_with_bridge(BASE_DIR / "templates" / "report.html", user))


@app.get("/interview/{session_token}", response_class=HTMLResponse)
async def candidate_interview(session_token: str, db: Session = Depends(get_db)):
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Интервью не найдено")
    source = (BASE_DIR / "templates" / "interview.html").read_text(encoding="utf-8")
    notice = """
    <div id="proctorNotice" style="margin:14px 0 0;padding:13px 14px;border:1px solid #e5e1ff;background:#faf9ff;border-radius:14px;font-size:12px;line-height:1.55;color:#5f6072">
      <b style="color:#3e3f4c">Во время интервью включён прокторинг.</b>
      Мы фиксируем уход со вкладки, clipboard actions, разрывы камеры/сети и локально анализируем видеопоток через MediaPipe: наличие лица, второе лицо, длительный поворот головы и длительный взгляд в сторону. Кадры и face landmarks на сервер не отправляются. Эти сигналы не входят в технический score.
    </div>
    """
    source = source.replace("</div></div></section>\n<section id=\"device\"", notice + "</div></div></section>\n<section id=\"device\"", 1)
    injection = (
        f"<script>window.__INTERVIEW_TOKEN__={json.dumps(session_token)};</script>"
        '<script src="/static/proctor.js"></script>'
        '<script type="module" src="/static/mediapipe_proctor.js"></script>'
    )
    source = source.replace("</body>", injection + "</body>", 1)
    return HTMLResponse(
        Template(source).render(
            session_token=session_token,
            candidate_name=session.candidate_name,
            vacancy_title=session.vacancy.title,
        )
    )


@app.get("/app", response_class=HTMLResponse)
@app.get("/app/{spa_path:path}", response_class=HTMLResponse)
async def workspace_spa(request: Request, spa_path: str = "", db: Session = Depends(get_db)):
    """React-рабочее место рекрутера. Все внутренние маршруты отдают один index.html."""
    user = _session_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not SPA_INDEX.is_file():
        raise HTTPException(status_code=503, detail="Сборка рабочего места не найдена: выполните npm run build в frontend/")
    text = SPA_INDEX.read_text(encoding="utf-8")
    bootstrap = (
        "<script>window.__USER__="
        + json.dumps(
            {"username": user.username, "role": user.role, "full_name": user.full_name},
            ensure_ascii=False,
        )
        + ";</script>"
    )
    return HTMLResponse(text.replace("</head>", bootstrap + "</head>", 1))


@app.get("/api/interviews/{session_token}/speak")
async def speak_question(session_token: str, text: str = "", db: Session = Depends(get_db)):
    """Озвучивает реплику интервьюера живым голосом.

    Синтез кэшируется по тексту, поэтому один и тот же вопрос считается один
    раз на всех кандидатов вакансии. Если Cartesia недоступна, отдаём 503 —
    страница кандидата тихо откатится на браузерный голос.
    """
    session = db.query(InterviewSession).filter(InterviewSession.session_token == session_token).first()
    if not session:
        raise HTTPException(status_code=404, detail="Интервью не найдено")
    try:
        audio = await synthesize(text)
    except TTSUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # no-store: URL зависит только от текста, поэтому при смене голоса или модели
    # браузер иначе сутки играл бы прежнюю запись. Диск отдаёт файл за миллисекунды.
    return FileResponse(audio, media_type=media_type_for(audio), headers={"Cache-Control": "no-store"})


# Keep all existing business routes and static mounts as a fallback.
app.mount("/", legacy_app)
