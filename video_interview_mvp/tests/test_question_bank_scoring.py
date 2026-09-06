import asyncio
import json
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

import database
import legacy_main
from app import app, legacy_app
from database import Question, User
from mvp_models import AuthSession
from question_bank_routes import load_question_bank_snapshot
from services.auth_service import hash_password
from services.llm_service import LLMService


BASE_DIR = Path(__file__).resolve().parents[1]


class QuestionBankAndScoringTests(unittest.TestCase):
    def test_canonical_routes_replace_legacy_duplicates(self):
        def count(path, method):
            return sum(
                1
                for route in legacy_app.routes
                if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set())
            )

        self.assertEqual(count("/api/questions", "GET"), 1)
        self.assertEqual(count("/api/interviews/{session_id}/complete", "POST"), 1)
        self.assertEqual(count("/api/reports/{session_id}", "GET"), 1)
        self.assertIs(legacy_main._load_question_bank, load_question_bank_snapshot)

    def test_hr_can_create_search_and_edit_question_bank(self):
        suffix = uuid.uuid4().hex[:10]
        username = f"bank_hr_{suffix}"
        question_text = f"Как устроен idempotency key {suffix}?"
        db = database.SessionLocal()
        user = User(
            username=username,
            password_hash=hash_password("bank-password-123"),
            role="hr",
            full_name="Question Bank HR",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
        db.close()

        client = TestClient(app)
        question_id = None
        try:
            login = client.post("/api/auth/login", json={"username": username, "password": "bank-password-123"})
            self.assertEqual(login.status_code, 200, login.text)

            created = client.post(
                "/api/questions",
                json={
                    "question": question_text,
                    "competency": "distributed_systems",
                    "tags": ["kafka", f"tag-{suffix}"],
                    "reference_answer": "Ключ сообщения сохраняется и повторная обработка не меняет состояние.",
                    "must_have": ["Объяснить дедупликацию, а не только retry."],
                    "nice_to_have": ["Упомянуть transactional outbox."],
                    "red_flags": ["Считать повторную обработку всегда безопасной."],
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            question_id = created.json()["database_id"]

            searched = client.get("/api/questions", params={"tag": f"tag-{suffix}"})
            self.assertEqual(searched.status_code, 200, searched.text)
            self.assertEqual(len(searched.json()), 1)
            self.assertEqual(searched.json()[0]["question"], question_text)

            patched = client.patch(
                f"/api/questions/{question_id}",
                json={
                    "tags": ["kafka", "idempotency"],
                    "must_have": ["Критерий с запятой, который должен остаться одним пунктом."],
                },
            )
            self.assertEqual(patched.status_code, 200, patched.text)
            self.assertEqual(patched.json()["tags"], ["kafka", "idempotency"])
            self.assertEqual(
                patched.json()["must_have"],
                ["Критерий с запятой, который должен остаться одним пунктом."],
            )

            snapshot = load_question_bank_snapshot()
            snap = next(item for item in snapshot if item["id"] == str(question_id))
            self.assertEqual(snap["tags"], ["kafka", "idempotency"])
            self.assertEqual(snap["must_have"], ["Критерий с запятой, который должен остаться одним пунктом."])
        finally:
            db = database.SessionLocal()
            db.query(AuthSession).filter(AuthSession.user_id == user_id).delete(synchronize_session=False)
            if question_id is not None:
                db.query(Question).filter(Question.id == question_id).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_question_scoring_schema_is_strict_and_evidence_grounded(self):
        service = LLMService(api_key="test-key")

        async def fake_call(messages, temperature=0.1, **kwargs):
            return json.dumps(
                {
                    "score_0_10": 12,
                    "covered_must_have": ["must-1", "invented"],
                    "missing_must_have": [],
                    "covered_nice_to_have": ["nice-1", "invented nice"],
                    "red_flags_found": ["red-1", "invented red"],
                    "evidence_quotes": ["точная цитата", "цитаты в ответе нет"],
                    "summary": "Проверка схемы.",
                    "confidence_0_1": 1.4,
                },
                ensure_ascii=False,
            )

        service._call_llm = fake_call
        result = asyncio.run(
            service.analyze_answer(
                question="Вопрос",
                reference_answer="Референс",
                must_have=["must-1", "must-2"],
                nice_to_have=["nice-1"],
                red_flags=["red-1"],
                candidate_transcript="Здесь есть точная цитата и другой текст.",
                question_id="q-1",
                competency="backend",
            )
        )
        self.assertEqual(result["score_0_10"], 10)
        self.assertEqual(result["covered_must_have"], ["must-1"])
        self.assertEqual(result["missing_must_have"], ["must-2"])
        self.assertEqual(result["covered_nice_to_have"], ["nice-1"])
        self.assertEqual(result["red_flags_found"], ["red-1"])
        self.assertEqual(result["evidence_quotes"], ["точная цитата"])
        self.assertEqual(result["confidence_0_1"], 1.0)
        self.assertEqual(result["score"], 10.0)
        self.assertEqual(result["detected_red_flags"], ["red-1"])

    def test_red_flag_is_dropped_without_verbatim_evidence(self):
        service = LLMService(api_key="test-key")

        async def fake_call(messages, temperature=0.1, **kwargs):
            return json.dumps(
                {
                    "score_0_10": 3,
                    "covered_must_have": [],
                    "missing_must_have": [],
                    "covered_nice_to_have": [],
                    "red_flags_found": ["unsafe"],
                    "evidence_quotes": ["invented quote"],
                    "summary": "Проверка.",
                    "confidence_0_1": 0.8,
                }
            )

        service._call_llm = fake_call
        result = asyncio.run(
            service.analyze_answer(
                question="Вопрос",
                reference_answer="",
                must_have=[],
                nice_to_have=[],
                red_flags=["unsafe"],
                candidate_transcript="Нейтральный ответ.",
            )
        )
        self.assertEqual(result["evidence_quotes"], [])
        self.assertEqual(result["red_flags_found"], [])

    def test_final_scoring_uses_nested_answer_score_and_excludes_motivation(self):
        service = LLMService(api_key="test-key")
        captured = {}

        async def fake_call(messages, temperature=0.1, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return json.dumps(
                {
                    "recommendation": "подходит",
                    "overall_score_0_10": 2.0,
                    "confidence_0_1": 0.4,
                    "summary": "Технический ответ сильный, но данных пока недостаточно для уверенного решения.",
                    "competencies": [
                        {
                            "name": "backend",
                            "status": "подтверждена",
                            "avg_score_0_10": 8,
                            "evidence_quotes": ["точная техническая цитата"],
                            "question_ids": ["1"],
                        }
                    ],
                    "vacancy_coverage": {"must_have": [], "nice_to_have": []},
                    "strengths": [
                        {"point": "Сильный ответ", "quote": "точная техническая цитата", "question_id": "1"},
                        {"point": "Галлюцинация", "quote": "нет такой цитаты", "question_id": "1"},
                    ],
                    "issues": [],
                    "uncovered_vacancy_topics": ["Kafka"],
                },
                ensure_ascii=False,
            )

        service._call_llm = fake_call
        result = asyncio.run(
            service.generate_final_report(
                vacancy_title="Backend",
                vacancy_requirements="Python, Kafka",
                answers_data=[
                    {
                        "question_id": "1",
                        "question_text": "Технический вопрос",
                        "competency": "backend",
                        "transcript": "В ответе есть точная техническая цитата.",
                        "evaluation": {
                            "score_0_10": 8,
                            "covered_must_have": [],
                            "missing_must_have": [],
                            "covered_nice_to_have": [],
                            "red_flags_found": [],
                            "evidence_quotes": ["точная техническая цитата"],
                            "summary": "ok",
                            "confidence_0_1": 0.8,
                        },
                    },
                    {
                        "question_id": "2",
                        "question_text": "Почему хотите работать у нас?",
                        "competency": "motivation",
                        "transcript": "Мотивационный ответ.",
                        "evaluation": {
                            "score_0_10": 0,
                            "covered_must_have": [],
                            "missing_must_have": [],
                            "covered_nice_to_have": [],
                            "red_flags_found": [],
                            "evidence_quotes": [],
                            "summary": "motivation",
                            "confidence_0_1": 0.8,
                        },
                    },
                ],
            )
        )
        # 2.0 from the model is >1 away from the technical average of 8.0,
        # therefore backend grounds the score to 8. Motivation score is excluded.
        self.assertEqual(result["overall_score_0_10"], 8.0)
        self.assertEqual(result["recommendation"], "требуется дополнительная проверка")
        self.assertEqual(len(result["strengths"]), 1)
        self.assertEqual(result["strengths"][0]["quote"], "точная техническая цитата")
        self.assertIn('"technical_average_0_10": 8.0', captured["prompt"])
        self.assertIn('"question_text": "Технический вопрос"', captured["prompt"])

    def test_prompt_contracts_and_frontend_hooks_exist(self):
        question_prompt = (BASE_DIR / "prompts" / "score_question.md").read_text(encoding="utf-8")
        interview_prompt = (BASE_DIR / "prompts" / "score_interview.md").read_text(encoding="utf-8")
        bank_ui = (BASE_DIR / "static" / "question_bank_ui.js").read_text(encoding="utf-8")
        bridge = (BASE_DIR / "static" / "session_bridge.js").read_text(encoding="utf-8")

        for field in {
            '"score_0_10"', '"covered_must_have"', '"missing_must_have"',
            '"covered_nice_to_have"', '"red_flags_found"', '"evidence_quotes"', '"confidence_0_1"',
        }:
            self.assertIn(field, question_prompt)
        for field in {'"overall_score_0_10"', '"confidence_0_1"', '"vacancy_coverage"', '"competencies"'}:
            self.assertIn(field, interview_prompt)
        self.assertIn("split(/\\n/)", bank_ui)
        self.assertIn("split(/,|\\n/)", bank_ui)
        self.assertIn("/static/question_bank_ui.js", bridge)
        self.assertIn("/static/scoring_report_ui.js", bridge)


if __name__ == "__main__":
    unittest.main()
