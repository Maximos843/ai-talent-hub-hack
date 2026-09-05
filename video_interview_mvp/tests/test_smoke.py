import asyncio
import unittest
from pathlib import Path

from sqlalchemy import inspect

import database
from app import ALLOWED_PROCTOR_EVENTS, _clean_proctor_metadata, app, legacy_app
from services.auth_service import hash_password, verify_password
from services.llm_service import LLMService
from services.media_service import media_metadata


BASE_DIR = Path(__file__).resolve().parents[1]


class ApplicationSmokeTests(unittest.TestCase):
    def test_critical_routes_are_registered(self):
        legacy_paths = {route.path for route in legacy_app.routes}
        expected_legacy = {
            "/api/candidates",
            "/api/candidates/{session_id}/status",
            "/api/candidates/{session_id}",
            "/api/interviews/{session_id}/questions",
            "/api/interviews/{session_id}/full-video",
            "/api/interviews/submit-answer",
            "/api/reviews/{session_id}/hr",
            "/api/reviews/{session_id}/manager",
            "/api/reports/{session_id}",
        }
        self.assertTrue(expected_legacy.issubset(legacy_paths))

        gateway_paths = {route.path for route in app.routes}
        expected_gateway = {
            "/api/auth/bootstrap-status",
            "/api/auth/invite-status",
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/me",
            "/api/auth/register",
            "/api/auth/invitations",
            "/api/interviews/{session_token}/proctor-events",
            "/api/proctoring/{session_id}/summary",
            "/dashboard",
            "/interview/{session_token}",
            "/report/{session_id}",
        }
        self.assertTrue(expected_gateway.issubset(gateway_paths))

    def test_workflow_media_auth_and_proctor_tables_exist(self):
        database.init_db()
        table_names = set(inspect(database.engine).get_table_names())
        for table in {
            "interview_questions",
            "review_decisions",
            "candidate_lifecycle",
            "answer_media",
            "auth_sessions",
            "workspace_invites",
            "proctor_events",
        }:
            self.assertIn(table, table_names)

    def test_password_hash_is_not_plaintext_and_verifies(self):
        password = "correct-horse-123"
        encoded = hash_password(password)
        self.assertNotEqual(encoded, password)
        self.assertTrue(encoded.startswith("pbkdf2_sha256$"))
        valid, upgraded = verify_password(password, encoded)
        self.assertTrue(valid)
        self.assertIsNone(upgraded)
        invalid, _ = verify_password("wrong-password", encoded)
        self.assertFalse(invalid)

    def test_legacy_plaintext_password_can_be_upgraded_even_if_short(self):
        # Previous MVP accepted short/plaintext passwords. Login must migrate them
        # instead of applying the new-account length policy and throwing ValueError.
        valid, upgraded = verify_password("old1", "old1")
        self.assertTrue(valid)
        self.assertIsNotNone(upgraded)
        self.assertTrue(upgraded.startswith("pbkdf2_sha256$"))
        valid_after, second_upgrade = verify_password("old1", upgraded)
        self.assertTrue(valid_after)
        self.assertIsNone(second_upgrade)

    def test_face_proctor_events_are_allowed_but_raw_content_is_dropped(self):
        expected = {
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
        self.assertTrue(expected.issubset(ALLOWED_PROCTOR_EVENTS))
        cleaned = _clean_proctor_metadata(
            {
                "duration_ms": 2500,
                "face_count": 2,
                "delegate": "GPU",
                "frame": "base64-image-must-never-survive",
                "landmarks": [1, 2, 3],
                "clipboard_text": "secret",
            }
        )
        self.assertEqual(cleaned["duration_ms"], 2500)
        self.assertEqual(cleaned["face_count"], 2)
        self.assertEqual(cleaned["delegate"], "GPU")
        self.assertNotIn("frame", cleaned)
        self.assertNotIn("landmarks", cleaned)
        self.assertNotIn("clipboard_text", cleaned)

    def test_mediapipe_module_is_non_blocking_and_reuses_interview_video(self):
        source = (BASE_DIR / "static" / "mediapipe_proctor.js").read_text(encoding="utf-8")
        self.assertIn("FaceLandmarker", source)
        self.assertIn("face_landmarker.task", source)
        self.assertIn("document.getElementById('video')", source)
        self.assertIn("detectForVideo", source)
        self.assertIn("vision_unavailable", source)
        self.assertNotIn("getUserMedia(", source)  # must not open a second camera stream

    def test_missing_media_is_explicitly_not_playable(self):
        metadata = media_metadata(None, fallback_duration_ms=1500)
        self.assertFalse(metadata["exists"])
        self.assertFalse(metadata["playable"])
        self.assertEqual(metadata["duration_ms"], 1500)

    def test_mock_answer_and_report_have_expected_shape(self):
        service = LLMService(api_key="")
        answer = asyncio.run(
            service.analyze_answer(
                question="Как обеспечивали идемпотентность consumer?",
                reference_answer="Idempotency key / state table",
                must_have=["идемпотентность"],
                nice_to_have=["DLQ"],
                red_flags=[],
                candidate_transcript="Использовали таблицу состояния и ключ сообщения.",
            )
        )
        self.assertIn("score", answer)
        self.assertIn("evidence_quotes", answer)
        self.assertGreaterEqual(answer["score"], 0)
        self.assertLessEqual(answer["score"], 10)

        report = asyncio.run(
            service.generate_final_report(
                vacancy_title="Python Backend",
                vacancy_requirements="Python, PostgreSQL, Kafka",
                answers_data=[
                    {
                        "question": "Kafka",
                        "transcript": "Использовали таблицу состояния.",
                        "score": answer["score"],
                        "analysis": answer.get("analysis", ""),
                        "strengths": answer.get("strengths", []),
                        "weaknesses": answer.get("weaknesses", []),
                        "covered_must_have": answer.get("covered_must_have", []),
                        "detected_red_flags": answer.get("detected_red_flags", []),
                    }
                ],
            )
        )
        self.assertIn(
            report["recommendation"],
            {"подходит", "не подходит", "требуется дополнительная проверка"},
        )
        self.assertGreaterEqual(report["overall_score"], 0)
        self.assertLessEqual(report["overall_score"], 10)


if __name__ == "__main__":
    unittest.main()
