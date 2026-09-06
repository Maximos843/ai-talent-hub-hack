import asyncio
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import inspect

import database
import main
from app import app
from database import CandidateLifecycle, InterviewSession, User, Vacancy
from mvp_models import AuthSession, FullInterviewMedia
from services.auth_service import hash_password
from services.llm_logging import install_llm_logging
from services.llm_service import LLMService


class MediaLlmHrGuardrailTests(unittest.TestCase):
    def test_canonical_guardrail_routes_exist_once(self):
        pairs = [
            (getattr(route, "path", None), getattr(route, "methods", set()) or set())
            for route in main._legacy_app.routes
        ]
        self.assertEqual(sum(p == "/api/interviews/{session_id}/full-video" and "POST" in m for p, m in pairs), 1)
        self.assertEqual(sum(p == "/api/reports/{session_id}" and "GET" in m for p, m in pairs), 1)
        self.assertEqual(sum(p == "/api/candidates/{session_id}/status" and "PATCH" in m for p, m in pairs), 1)

    def test_full_interview_media_table_exists(self):
        database.init_db()
        self.assertIn("full_interview_media", set(inspect(database.engine).get_table_names()))

    def test_full_video_client_duration_is_persisted_when_probe_cannot_validate(self):
        db = database.SessionLocal()
        vacancy = Vacancy(title="Media test", owner_id=None)
        db.add(vacancy)
        db.flush()
        session = InterviewSession(
            vacancy_id=vacancy.id,
            candidate_name="Media Candidate",
            session_token=str(uuid.uuid4()),
            status="in_progress",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id
        db.close()

        client = TestClient(app)
        try:
            response = client.post(
                f"/api/interviews/{session_id}/full-video",
                data={"client_duration_ms": "4200"},
                files={"file": ("interview.webm", b"x" * 2048, "video/webm")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertTrue(payload["playable"])
            self.assertEqual(payload["duration_ms"], 4200)
            self.assertEqual(payload["duration_source"], "client_reported")
            self.assertEqual(payload["technical_status"], "available")

            db = database.SessionLocal()
            stored = db.query(FullInterviewMedia).filter(FullInterviewMedia.session_id == session_id).first()
            self.assertIsNotNone(stored)
            self.assertEqual(stored.duration_ms, 4200)
            self.assertEqual(stored.duration_source, "client_reported")
            db.close()
        finally:
            db = database.SessionLocal()
            db.query(FullInterviewMedia).filter(FullInterviewMedia.session_id == session_id).delete(synchronize_session=False)
            session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
            if session:
                vacancy_id = session.vacancy_id
                db.delete(session)
                db.flush()
                db.query(Vacancy).filter(Vacancy.id == vacancy_id).delete(synchronize_session=False)
            db.commit()
            db.close()
            for path in main.legacy_main.UPLOAD_DIR.glob(f"full_interview_{session_id}*"):
                path.unlink(missing_ok=True)

    def test_llm_calls_emit_safe_explicit_logs(self):
        service = LLMService(api_key="")
        install_llm_logging(service)
        with self.assertLogs("talent_interview.llm", level="INFO") as captured:
            result = asyncio.run(
                service.analyze_answer(
                    question="Технический вопрос",
                    reference_answer="",
                    must_have=[],
                    nice_to_have=[],
                    red_flags=[],
                    candidate_transcript="Ответ",
                    question_id="safe-log-test",
                    competency="backend",
                )
            )
        joined = "\n".join(captured.output)
        self.assertIn("LLM request start mode=MOCK", joined)
        self.assertIn("LLM request ok mode=MOCK", joined)
        self.assertNotIn("Ответ", joined)
        self.assertEqual(result["score_0_10"], 7)

    def test_hr_cannot_mark_candidate_hired_without_manager_final_approval(self):
        suffix = uuid.uuid4().hex[:10]
        username = f"hr_guard_{suffix}"
        db = database.SessionLocal()
        hr = User(
            username=username,
            password_hash=hash_password("guard-password-123"),
            role="hr",
            full_name="Guard HR",
        )
        db.add(hr)
        db.flush()
        vacancy = Vacancy(title="Guard vacancy", owner_id=hr.id)
        db.add(vacancy)
        db.flush()
        session = InterviewSession(
            vacancy_id=vacancy.id,
            candidate_name="Guard Candidate",
            session_token=str(uuid.uuid4()),
            status="pending",
        )
        db.add(session)
        db.flush()
        db.add(CandidateLifecycle(session_id=session.id, status="active", note=""))
        db.commit()
        db.refresh(hr)
        db.refresh(session)
        hr_id, vacancy_id, session_id = hr.id, vacancy.id, session.id
        db.close()

        client = TestClient(app)
        try:
            login = client.post("/api/auth/login", json={"username": username, "password": "guard-password-123"})
            self.assertEqual(login.status_code, 200, login.text)
            response = client.patch(
                f"/api/candidates/{session_id}/status",
                json={"status": "hired", "note": "manual override"},
            )
            self.assertEqual(response.status_code, 403, response.text)
            self.assertIn("нанимающего менеджера", response.json()["detail"])

            db = database.SessionLocal()
            lifecycle = db.query(CandidateLifecycle).filter(CandidateLifecycle.session_id == session_id).first()
            self.assertEqual(lifecycle.status, "active")
            db.close()
        finally:
            db = database.SessionLocal()
            db.query(AuthSession).filter(AuthSession.user_id == hr_id).delete(synchronize_session=False)
            db.query(InterviewSession).filter(InterviewSession.id == session_id).delete(synchronize_session=False)
            db.query(Vacancy).filter(Vacancy.id == vacancy_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == hr_id).delete(synchronize_session=False)
            db.commit()
            db.close()


if __name__ == "__main__":
    unittest.main()
