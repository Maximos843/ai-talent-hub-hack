import asyncio
import unittest

from sqlalchemy import inspect

import database
from main import app
from services.llm_service import LLMService


class ApplicationSmokeTests(unittest.TestCase):
    def test_critical_routes_are_registered(self):
        paths = {route.path for route in app.routes}
        expected = {
            "/api/candidates",
            "/api/interviews/{session_id}/questions",
            "/api/reviews/{session_id}/hr",
            "/api/reviews/{session_id}/manager",
            "/api/reports/{session_id}",
        }
        self.assertTrue(expected.issubset(paths))

    def test_new_workflow_tables_exist(self):
        database.init_db()
        table_names = set(inspect(database.engine).get_table_names())
        self.assertIn("interview_questions", table_names)
        self.assertIn("review_decisions", table_names)

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
        self.assertIn(report["recommendation"], {"подходит", "не подходит", "требуется дополнительная проверка"})
        self.assertGreaterEqual(report["overall_score"], 0)
        self.assertLessEqual(report["overall_score"], 10)


if __name__ == "__main__":
    unittest.main()
