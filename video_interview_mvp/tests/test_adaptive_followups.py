import asyncio
import json
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

import database
from adaptive_models import (
    AdaptiveProbeDecision,
    AnswerQuestionLink,
    InterviewQuestionProbeConfig,
    QuestionProbeConfig,
)
from app import app, legacy_app
from database import (
    Answer,
    AnswerMedia,
    CandidateLifecycle,
    FinalReport,
    InterviewQuestion,
    InterviewSession,
    Question,
    SessionQuestion,
    User,
    Vacancy,
)
from mvp_models import AuthSession
from question_bank_routes import load_question_bank_snapshot
from services import llm_service
from services.auth_service import hash_password
from services.llm_service import LLMService


BASE_DIR = Path(__file__).resolve().parents[1]


def route_count(path, method):
    return sum(
        1
        for route in legacy_app.routes
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set())
    )


class AdaptiveFollowUpContractTests(unittest.TestCase):
    def test_adaptive_tables_and_canonical_routes_exist_once(self):
        database.init_db()
        tables = set(inspect(database.engine).get_table_names())
        for name in {
            "question_probe_configs",
            "interview_question_probe_configs",
            "answer_question_links",
            "adaptive_probe_decisions",
        }:
            self.assertIn(name, tables)

        self.assertEqual(route_count("/api/interviews/{session_token}", "GET"), 1)
        self.assertEqual(route_count("/api/interviews/submit-answer", "POST"), 1)
        self.assertEqual(route_count("/api/interviews/correct-transcript", "POST"), 1)

    def test_current_question_json_extra_hints_are_seeded_into_db_snapshot(self):
        bank = load_question_bank_snapshot()
        ci_cd = next(item for item in bank if item["question"] == "Как настроить CI/CD?")
        self.assertGreaterEqual(len(ci_cd.get("possible_extra_questions", [])), 1)
        self.assertIn(
            "В чем разница между Continuous Delivery и Continuous Deployment?",
            ci_cd["possible_extra_questions"],
        )

    def test_follow_up_llm_contract_normalizes_and_enforces_max(self):
        service = LLMService(api_key="test-key")

        async def fake_call(messages, temperature=0.1, **kwargs):
            return json.dumps(
                {
                    "ask_follow_up": True,
                    "follow_up_question": "Как это решение поведёт себя при падении сети?",
                    "follow_up_must_have": ["a", "b", "c", "d", "e"],
                    "reason": "Нужно проверить отказоустойчивость.",
                    "focus": "Поведение при partial failure",
                    "source": "generated",
                    "resolved_root_score_0_10": 15,
                    "confidence_0_1": 2,
                },
                ensure_ascii=False,
            )

        service._call_llm = fake_call
        result = asyncio.run(
            service.decide_follow_up(
                root_question_id="1",
                root_question="Как устроена идемпотентность?",
                competency="backend",
                reference_answer="",
                must_have=[],
                nice_to_have=[],
                red_flags=[],
                possible_extra_questions=[],
                turns=[{"question": "q", "transcript": "a", "score_0_10": 7, "summary": "ok"}],
                already_asked_questions=["Как устроена идемпотентность?"],
                follow_up_count=1,
                max_follow_ups=2,
            )
        )
        self.assertTrue(result["ask_follow_up"])
        self.assertEqual(result["resolved_root_score_0_10"], 10.0)
        self.assertEqual(result["confidence_0_1"], 1.0)
        self.assertEqual(result["follow_up_must_have"], ["a", "b", "c", "d"])

        at_limit = asyncio.run(
            service.decide_follow_up(
                root_question_id="1",
                root_question="Как устроена идемпотентность?",
                competency="backend",
                reference_answer="",
                must_have=[],
                nice_to_have=[],
                red_flags=[],
                possible_extra_questions=[],
                turns=[],
                already_asked_questions=[],
                follow_up_count=2,
                max_follow_ups=2,
            )
        )
        self.assertFalse(at_limit["ask_follow_up"])
        self.assertIsNone(at_limit["follow_up_question"])
        self.assertEqual(at_limit["source"], "none")

    def test_final_average_does_not_double_weight_follow_up_answers(self):
        service = LLMService(api_key="test-key")
        captured = {}

        async def fake_call(messages, temperature=0.1, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return json.dumps(
                {
                    "recommendation": "подходит",
                    "overall_score_0_10": 7,
                    "confidence_0_1": 0.8,
                    "summary": "Достаточно данных.",
                    "competencies": [],
                    "vacancy_coverage": {"must_have": [], "nice_to_have": []},
                    "strengths": [],
                    "issues": [],
                    "uncovered_vacancy_topics": [],
                },
                ensure_ascii=False,
            )

        service._call_llm = fake_call
        result = asyncio.run(
            service.generate_final_report(
                vacancy_title="Backend",
                vacancy_requirements="Python",
                answers_data=[
                    {
                        "question_id": "root-1",
                        "root_question_id": "root-1",
                        "question_text": "Root 1",
                        "competency": "backend",
                        "transcript": "root",
                        "counts_toward_technical_average": True,
                        "technical_score_0_10": 8,
                        "evaluation": {"score_0_10": 5},
                    },
                    {
                        "question_id": "follow-1",
                        "root_question_id": "root-1",
                        "question_text": "Follow-up",
                        "competency": "backend",
                        "transcript": "follow",
                        "is_follow_up": True,
                        "follow_up_index": 1,
                        "counts_toward_technical_average": False,
                        "technical_score_0_10": 2,
                        "evaluation": {"score_0_10": 2},
                    },
                    {
                        "question_id": "root-2",
                        "root_question_id": "root-2",
                        "question_text": "Root 2",
                        "competency": "backend",
                        "transcript": "root2",
                        "counts_toward_technical_average": True,
                        "technical_score_0_10": 6,
                        "evaluation": {"score_0_10": 6},
                    },
                ],
            )
        )
        self.assertEqual(result["overall_score_0_10"], 7.0)
        self.assertIn('"technical_average_0_10": 7.0', captured["prompt"])
        self.assertIn('"is_follow_up": true', captured["prompt"])
        self.assertIn('"root_question_id": "root-1"', captured["prompt"])

    def test_prompt_and_frontend_contracts_are_present(self):
        prompt = (BASE_DIR / "prompts" / "follow_up_decision.md").read_text(encoding="utf-8")
        final_prompt = (BASE_DIR / "prompts" / "score_interview.md").read_text(encoding="utf-8")
        candidate_ui = (BASE_DIR / "static" / "adaptive_followups.js").read_text(encoding="utf-8")
        report_ui = (BASE_DIR / "static" / "adaptive_followup_report.js").read_text(encoding="utf-8")
        proctor = (BASE_DIR / "static" / "proctor.js").read_text(encoding="utf-8")
        bridge = (BASE_DIR / "static" / "session_bridge.js").read_text(encoding="utf-8")

        for field in {
            '"ask_follow_up"', '"follow_up_question"', '"follow_up_must_have"',
            '"resolved_root_score_0_10"', '"confidence_0_1"', '"possible_extra_questions"',
        }:
            self.assertIn(field, prompt)
        self.assertIn('"is_follow_up"', final_prompt)
        self.assertIn('"root_question_id"', final_prompt)
        self.assertIn("data.follow_up", candidate_ui)
        self.assertIn("уточнение ${current}/${max}", candidate_ui)
        self.assertIn("adaptive_follow_ups", report_ui)
        self.assertIn("/static/adaptive_followups.js", proctor)
        self.assertIn("/static/adaptive_followup_report.js", bridge)


class AdaptiveFollowUpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid.uuid4().hex[:10]
        self.username = f"adaptive_hr_{self.suffix}"
        self.password = "adaptive-password-123"
        self.token = str(uuid.uuid4())

        db = database.SessionLocal()
        user = User(
            username=self.username,
            password_hash=hash_password(self.password),
            role="hr",
            full_name="Adaptive HR",
        )
        db.add(user)
        db.flush()
        vacancy = Vacancy(
            title=f"Adaptive Backend {self.suffix}",
            description="Python, distributed systems",
            requirements="Python, distributed systems",
            grade="middle",
            owner_id=user.id,
        )
        db.add(vacancy)
        db.flush()
        question = Question(
            question_text=f"Как обеспечить идемпотентность {self.suffix}?",
            tags=["backend"],
            competency="backend",
            reference_answer="Idempotency key and durable state",
            must_have=["идемпотентный ключ"],
            nice_to_have=["outbox"],
            red_flags=[],
        )
        db.add(question)
        db.flush()
        db.add(
            QuestionProbeConfig(
                question_id=question.id,
                possible_extra_questions=["Как хранить состояние обработанных запросов?"],
            )
        )
        sq = SessionQuestion(vacancy_id=vacancy.id, question_id=question.id, order_index=0, is_approved=True)
        db.add(sq)
        db.flush()
        session = InterviewSession(
            vacancy_id=vacancy.id,
            candidate_name="Adaptive Candidate",
            session_token=self.token,
            status="in_progress",
        )
        db.add(session)
        db.flush()
        db.add(CandidateLifecycle(session_id=session.id, status="active", note=""))
        root = InterviewQuestion(
            session_id=session.id,
            source_session_question_id=sq.id,
            question_text=question.question_text,
            competency="backend",
            reference_answer=question.reference_answer,
            must_have=question.must_have,
            nice_to_have=question.nice_to_have,
            red_flags=[],
            order_index=0,
            is_active=True,
            is_custom=False,
        )
        db.add(root)
        db.flush()
        db.add(
            InterviewQuestionProbeConfig(
                interview_question_id=root.id,
                possible_extra_questions=["Как хранить состояние обработанных запросов?"],
            )
        )
        db.commit()

        self.user_id = user.id
        self.vacancy_id = vacancy.id
        self.question_id = question.id
        self.session_question_id = sq.id
        self.session_id = session.id
        self.root_id = root.id
        db.close()

        self.original_analyze = llm_service.analyze_answer
        self.original_decide = llm_service.decide_follow_up
        self.original_final = llm_service.generate_final_report
        self.final_input = None

        async def fake_analyze(**kwargs):
            transcript = kwargs.get("candidate_transcript", "")
            score = 6 if "root" in transcript else 7
            return {
                "score_0_10": score,
                "covered_must_have": [],
                "missing_must_have": list(kwargs.get("must_have", [])),
                "covered_nice_to_have": [],
                "red_flags_found": [],
                "evidence_quotes": [],
                "summary": "Нужно проверить глубже.",
                "confidence_0_1": 0.8,
                "score": float(score),
                "analysis": "Нужно проверить глубже.",
                "strengths": [],
                "weaknesses": list(kwargs.get("must_have", [])),
                "detected_red_flags": [],
                "confidence": 0.8,
            }

        async def fake_decide(**kwargs):
            count = kwargs["follow_up_count"]
            questions = [
                "Как хранить состояние обработанных запросов?",
                "Что произойдёт при одновременном повторе одного запроса?",
                "Этот третий вопрос backend обязан заблокировать лимитом",
            ]
            return {
                "ask_follow_up": True,
                "follow_up_question": questions[min(count, 2)],
                "follow_up_must_have": ["конкретный механизм"],
                "reason": f"Нужно уточнение после шага {count}.",
                "focus": "Глубина понимания идемпотентности",
                "source": "generated",
                "resolved_root_score_0_10": [6.5, 8.0, 9.0][min(count, 2)],
                "confidence_0_1": 0.9,
            }

        async def fake_final(vacancy_title, vacancy_requirements, answers_data):
            self.final_input = answers_data
            return {
                "recommendation": "подходит",
                "overall_score_0_10": 9.0,
                "confidence_0_1": 0.8,
                "summary": "Цепочка уточнений позволила проверить тему глубже.",
                "competencies": [],
                "vacancy_coverage": {"must_have": [], "nice_to_have": []},
                "strengths": [],
                "issues": [],
                "uncovered_vacancy_topics": [],
            }

        llm_service.analyze_answer = fake_analyze
        llm_service.decide_follow_up = fake_decide
        llm_service.generate_final_report = fake_final
        self.client = TestClient(app)

    def tearDown(self):
        llm_service.analyze_answer = self.original_analyze
        llm_service.decide_follow_up = self.original_decide
        llm_service.generate_final_report = self.original_final
        db = database.SessionLocal()
        answer_ids = [row[0] for row in db.query(Answer.id).filter(Answer.session_id == self.session_id).all()]
        iq_ids = [row[0] for row in db.query(InterviewQuestion.id).filter(InterviewQuestion.session_id == self.session_id).all()]
        if answer_ids:
            db.query(AdaptiveProbeDecision).filter(AdaptiveProbeDecision.trigger_answer_id.in_(answer_ids)).delete(synchronize_session=False)
            db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id.in_(answer_ids)).delete(synchronize_session=False)
            db.query(AnswerMedia).filter(AnswerMedia.answer_id.in_(answer_ids)).delete(synchronize_session=False)
            db.query(Answer).filter(Answer.id.in_(answer_ids)).delete(synchronize_session=False)
        if iq_ids:
            db.query(InterviewQuestionProbeConfig).filter(InterviewQuestionProbeConfig.interview_question_id.in_(iq_ids)).delete(synchronize_session=False)
            db.query(InterviewQuestion).filter(InterviewQuestion.id.in_(iq_ids)).delete(synchronize_session=False)
        db.query(FinalReport).filter(FinalReport.session_id == self.session_id).delete(synchronize_session=False)
        db.query(CandidateLifecycle).filter(CandidateLifecycle.session_id == self.session_id).delete(synchronize_session=False)
        db.query(InterviewSession).filter(InterviewSession.id == self.session_id).delete(synchronize_session=False)
        db.query(SessionQuestion).filter(SessionQuestion.id == self.session_question_id).delete(synchronize_session=False)
        db.query(QuestionProbeConfig).filter(QuestionProbeConfig.question_id == self.question_id).delete(synchronize_session=False)
        db.query(Question).filter(Question.id == self.question_id).delete(synchronize_session=False)
        db.query(Vacancy).filter(Vacancy.id == self.vacancy_id).delete(synchronize_session=False)
        db.query(AuthSession).filter(AuthSession.user_id == self.user_id).delete(synchronize_session=False)
        db.query(User).filter(User.id == self.user_id).delete(synchronize_session=False)
        db.commit()
        db.close()

    def _submit(self, question_id, transcript):
        response = self.client.post(
            "/api/interviews/submit-answer",
            data={
                "session_id": str(self.session_id),
                "question_id": str(question_id),
                "transcript": transcript,
                "start_ms": "0",
                "end_ms": "1000",
                "client_duration_ms": "1000",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["answer_id"]

    def _confirm(self, answer_id, transcript):
        return self.client.post(
            "/api/interviews/correct-transcript",
            json={"answer_id": answer_id, "corrected_transcript": transcript},
        )

    def test_full_adaptive_chain_is_limited_idempotent_scored_and_reported(self):
        initial = self.client.get(f"/api/interviews/{self.token}")
        self.assertEqual(initial.status_code, 200, initial.text)
        self.assertEqual(len(initial.json()["questions"]), 1)
        self.assertEqual(initial.json()["adaptive_follow_ups"]["max_per_question"], 2)

        root_answer = self._submit(self.root_id, "root ответ")
        db = database.SessionLocal()
        link = db.query(AnswerQuestionLink).filter(AnswerQuestionLink.answer_id == root_answer).first()
        self.assertEqual(link.interview_question_id, self.root_id)
        db.close()

        first = self._confirm(root_answer, "root ответ")
        self.assertEqual(first.status_code, 200, first.text)
        follow1 = first.json()["follow_up"]
        self.assertEqual(follow1["follow_up_index"], 1)
        self.assertEqual(follow1["question"], "Как хранить состояние обработанных запросов?")

        retry = self._confirm(root_answer, "root ответ")
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["follow_up"]["session_question_id"], follow1["session_question_id"])
        changed = self._confirm(root_answer, "изменённый ответ")
        self.assertEqual(changed.status_code, 409, changed.text)

        answer1 = self._submit(follow1["session_question_id"], "первое уточнение")
        second = self._confirm(answer1, "первое уточнение")
        self.assertEqual(second.status_code, 200, second.text)
        follow2 = second.json()["follow_up"]
        self.assertEqual(follow2["follow_up_index"], 2)

        answer2 = self._submit(follow2["session_question_id"], "второе уточнение")
        third = self._confirm(answer2, "второе уточнение")
        self.assertEqual(third.status_code, 200, third.text)
        self.assertIsNone(third.json()["follow_up"])

        db = database.SessionLocal()
        decisions = (
            db.query(AdaptiveProbeDecision)
            .filter(AdaptiveProbeDecision.root_interview_question_id == self.root_id)
            .order_by(AdaptiveProbeDecision.id)
            .all()
        )
        self.assertEqual(len(decisions), 3)
        self.assertEqual(sum(1 for item in decisions if item.ask_follow_up), 2)
        self.assertEqual(decisions[0].source, "possible_extra_questions")
        self.assertFalse(decisions[2].ask_follow_up)
        self.assertEqual(decisions[2].resolved_root_score_0_10, 9.0)
        db.close()

        after = self.client.get(f"/api/interviews/{self.token}")
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(len(after.json()["questions"]), 1)
        self.assertEqual(after.json()["questions"][0]["session_question_id"], self.root_id)

        complete = self.client.post(f"/api/interviews/{self.session_id}/complete")
        self.assertEqual(complete.status_code, 200, complete.text)
        self.assertIsNotNone(self.final_input)
        root_item = next(item for item in self.final_input if not item["is_follow_up"])
        follow_items = [item for item in self.final_input if item["is_follow_up"]]
        self.assertEqual(root_item["technical_score_0_10"], 9.0)
        self.assertTrue(root_item["counts_toward_technical_average"])
        self.assertEqual(len(follow_items), 2)
        self.assertTrue(all(not item["counts_toward_technical_average"] for item in follow_items))

        login = self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})
        self.assertEqual(login.status_code, 200, login.text)
        report = self.client.get(f"/api/reports/{self.session_id}")
        self.assertEqual(report.status_code, 200, report.text)
        chains = report.json()["adaptive_follow_ups"]
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["follow_up_count"], 2)
        self.assertEqual(chains[0]["resolved_root_score_0_10"], 9.0)
        self.assertEqual(chains[0]["follow_ups"][0]["source"], "possible_extra_questions")
        self.assertEqual(chains[0]["follow_ups"][0]["transcript"], "первое уточнение")
        self.assertIn("Нужно уточнение", chains[0]["follow_ups"][0]["reason"])
        self.assertEqual(len([a for a in report.json()["answers"] if a["is_follow_up"]]), 2)

    def test_motivation_question_never_calls_adaptive_probe(self):
        db = database.SessionLocal()
        root = db.query(InterviewQuestion).filter(InterviewQuestion.id == self.root_id).first()
        root.competency = "motivation"
        db.commit()
        db.close()

        async def must_not_be_called(**kwargs):
            raise AssertionError("decide_follow_up must not run for motivation")

        llm_service.decide_follow_up = must_not_be_called
        answer_id = self._submit(self.root_id, "мотивационный ответ")
        response = self._confirm(answer_id, "мотивационный ответ")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["follow_up"])


if __name__ == "__main__":
    unittest.main()
