"""LLM helpers for answer evaluation, final interview evaluation and question selection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import httpx

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


BASE_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = BASE_DIR / "prompts"
RECOMMENDATIONS = {"подходит", "не подходит", "требуется дополнительная проверка"}
COMPETENCY_STATUSES = {"подтверждена", "частично подтверждена", "не проверена", "есть риск"}
COVERAGE_STATUSES = {"подтверждено", "частично подтверждено", "не проверено", "есть риск"}
ISSUE_TYPES = {"риск", "противоречие", "зона роста"}


class LLMService:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost:8000",
            "X-Title": "Talent Interview MVP",
        }

    async def _call_llm(self, messages: List[Dict[str, str]], temperature: float = 0.1) -> str:
        if not self.api_key:
            return self._get_mock_response(messages)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 3600,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(response: str) -> Dict[str, Any]:
        start = response.find("{")
        end = response.rfind("}") + 1
        parsed = json.loads(response[start:end] if start >= 0 and end > start else response)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response must be a JSON object")
        return parsed

    @staticmethod
    def _load_prompt(name: str, input_data: dict) -> str:
        template = (PROMPTS_DIR / name).read_text(encoding="utf-8")
        return template.replace("{{INPUT_JSON}}", json.dumps(input_data, ensure_ascii=False, indent=2))

    @staticmethod
    def _strings(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            if isinstance(item, str) and item.strip() and item.strip() not in result:
                result.append(item.strip())
        return result

    @staticmethod
    def _subset(value: Any, allowed: List[str]) -> List[str]:
        allowed_set = set(allowed or [])
        return [item for item in LLMService._strings(value) if item in allowed_set]

    @staticmethod
    def _quotes(value: Any, transcripts: List[str]) -> List[str]:
        result = []
        for quote in LLMService._strings(value):
            if any(quote in (text or "") for text in transcripts) and quote not in result:
                result.append(quote)
        return result

    def _get_mock_response(self, messages: List[Dict[str, str]]) -> str:
        text = messages[-1]["content"] if messages else ""
        if '"candidate_answers"' in text and '"vacancy_coverage"' in text:
            return json.dumps({
                "recommendation": "требуется дополнительная проверка",
                "overall_score_0_10": 7.0,
                "confidence_0_1": 0.72,
                "summary": "Ответы показывают рабочее понимание части проверенных технических тем. Непроверенные требования вакансии следует подтвердить на следующем этапе.",
                "competencies": [],
                "vacancy_coverage": {"must_have": [], "nice_to_have": []},
                "strengths": [],
                "issues": [],
                "uncovered_vacancy_topics": [],
            }, ensure_ascii=False)
        return json.dumps({
            "score_0_10": 7,
            "covered_must_have": [],
            "missing_must_have": [],
            "covered_nice_to_have": [],
            "red_flags_found": [],
            "evidence_quotes": [],
            "summary": "Ответ содержит релевантные технические элементы, но часть критериев требует дополнительного подтверждения.",
            "confidence_0_1": 0.7,
        }, ensure_ascii=False)

    async def analyze_answer(
        self,
        question: str,
        reference_answer: str,
        must_have: List[str],
        nice_to_have: List[str],
        red_flags: List[str],
        candidate_transcript: str,
        question_id: str = "",
        competency: str = "",
    ) -> Dict[str, Any]:
        input_data = {
            "question_id": str(question_id or ""),
            "question": question,
            "competency": competency or "general",
            "reference_answer": reference_answer or "",
            "must_have": list(must_have or []),
            "nice_to_have": list(nice_to_have or []),
            "red_flags": list(red_flags or []),
            "transcript": candidate_transcript or "",
        }
        try:
            raw = self._parse_json(await self._call_llm([
                {"role": "user", "content": self._load_prompt("score_question.md", input_data)}
            ]))
            covered = self._subset(raw.get("covered_must_have"), input_data["must_have"])
            missing = [item for item in input_data["must_have"] if item not in covered]
            result = {
                "score_0_10": max(0, min(10, int(round(float(raw.get("score_0_10", 5)))))),
                "covered_must_have": covered,
                "missing_must_have": missing,
                "covered_nice_to_have": self._subset(raw.get("covered_nice_to_have"), input_data["nice_to_have"]),
                "red_flags_found": self._subset(raw.get("red_flags_found"), input_data["red_flags"]),
                "evidence_quotes": self._quotes(raw.get("evidence_quotes"), [input_data["transcript"]]),
                "summary": str(raw.get("summary") or "Оценка требует ручной проверки.").strip(),
                "confidence_0_1": max(0.0, min(1.0, float(raw.get("confidence_0_1", 0.5)))),
            }
        except Exception as exc:
            result = {
                "score_0_10": 5,
                "covered_must_have": [],
                "missing_must_have": list(input_data["must_have"]),
                "covered_nice_to_have": [],
                "red_flags_found": [],
                "evidence_quotes": [],
                "summary": f"Не удалось надёжно разобрать LLM-оценку; нужна ручная проверка: {exc}",
                "confidence_0_1": 0.0,
            }

        # Compatibility aliases for existing report UI/storage while the canonical
        # schema above remains the single source for scoring semantics.
        result.update({
            "score": float(result["score_0_10"]),
            "analysis": result["summary"],
            "strengths": result["covered_must_have"] + result["covered_nice_to_have"],
            "weaknesses": result["missing_must_have"],
            "detected_red_flags": result["red_flags_found"],
            "confidence": result["confidence_0_1"],
        })
        return result

    @staticmethod
    def _normalize_competencies(value: Any, transcripts: List[str]) -> List[dict]:
        result = []
        if not isinstance(value, list):
            return result
        for item in value:
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                continue
            status = item.get("status") if item.get("status") in COMPETENCY_STATUSES else "не проверена"
            try:
                score = max(0.0, min(10.0, float(item.get("avg_score_0_10", 0))))
            except (TypeError, ValueError):
                score = 0.0
            result.append({
                "name": str(item["name"]).strip(),
                "status": status,
                "avg_score_0_10": round(score, 2),
                "evidence_quotes": LLMService._quotes(item.get("evidence_quotes"), transcripts),
                "question_ids": LLMService._strings(item.get("question_ids")),
            })
        return result

    @staticmethod
    def _normalize_coverage(value: Any, transcripts: List[str]) -> dict:
        source = value if isinstance(value, dict) else {}
        result = {"must_have": [], "nice_to_have": []}
        for group in result:
            items = source.get(group, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not str(item.get("topic", "")).strip():
                    continue
                status = item.get("status") if item.get("status") in COVERAGE_STATUSES else "не проверено"
                result[group].append({
                    "topic": str(item["topic"]).strip(),
                    "status": status,
                    "evidence_quotes": LLMService._quotes(item.get("evidence_quotes"), transcripts),
                    "question_ids": LLMService._strings(item.get("question_ids")),
                })
        return result

    @staticmethod
    def _normalize_strengths(value: Any, transcripts: List[str]) -> List[dict]:
        result = []
        if not isinstance(value, list):
            return result
        for item in value:
            if not isinstance(item, dict) or not str(item.get("point", "")).strip():
                continue
            quote = str(item.get("quote", "")).strip()
            if not quote or not any(quote in (text or "") for text in transcripts):
                continue
            result.append({
                "point": str(item["point"]).strip(),
                "quote": quote,
                "question_id": str(item.get("question_id", "")).strip(),
            })
        return result

    @staticmethod
    def _normalize_issues(value: Any, transcripts: List[str]) -> List[dict]:
        result = []
        if not isinstance(value, list):
            return result
        for item in value:
            if not isinstance(item, dict) or not str(item.get("point", "")).strip():
                continue
            issue_type = item.get("type") if item.get("type") in ISSUE_TYPES else "зона роста"
            quote = item.get("quote")
            if quote is not None:
                quote = str(quote).strip() or None
                if quote and not any(quote in (text or "") for text in transcripts):
                    quote = None
            result.append({
                "point": str(item["point"]).strip(),
                "type": issue_type,
                "quote": quote,
                "question_id": str(item.get("question_id")).strip() if item.get("question_id") is not None else None,
            })
        return result

    async def generate_final_report(
        self,
        vacancy_title: str,
        vacancy_requirements: str,
        answers_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized_answers = []
        scores = []
        transcripts = []
        for index, answer in enumerate(answers_data, 1):
            score = answer.get("score_0_10", answer.get("score"))
            if score is not None:
                try:
                    scores.append(max(0.0, min(10.0, float(score))))
                except (TypeError, ValueError):
                    pass
            transcript = str(answer.get("transcript") or "")
            transcripts.append(transcript)
            evaluation = answer.get("evaluation") if isinstance(answer.get("evaluation"), dict) else {
                "score_0_10": answer.get("score_0_10", answer.get("score", 5)),
                "covered_must_have": answer.get("covered_must_have", []),
                "missing_must_have": answer.get("missing_must_have", answer.get("weaknesses", [])),
                "covered_nice_to_have": answer.get("covered_nice_to_have", []),
                "red_flags_found": answer.get("red_flags_found", answer.get("detected_red_flags", [])),
                "evidence_quotes": answer.get("evidence_quotes", []),
                "summary": answer.get("summary", answer.get("analysis", "")),
                "confidence_0_1": answer.get("confidence_0_1", answer.get("confidence", 0.5)),
            }
            normalized_answers.append({
                "question_id": str(answer.get("question_id") or index),
                "question_text": answer.get("question_text", answer.get("question", "")),
                "competency": answer.get("competency", "general"),
                "transcript": transcript,
                "evaluation": evaluation,
            })

        technical_average = sum(scores) / len(scores) if scores else 5.0
        input_data = {
            "vacancy_requirements": vacancy_requirements or vacancy_title,
            "technical_average_0_10": round(technical_average, 2),
            "candidate_answers": normalized_answers,
        }
        try:
            raw = self._parse_json(await self._call_llm([
                {"role": "user", "content": self._load_prompt("score_interview.md", input_data)}
            ]))
            try:
                model_score = max(0.0, min(10.0, float(raw.get("overall_score_0_10", technical_average))))
            except (TypeError, ValueError):
                model_score = technical_average
            if abs(model_score - technical_average) > 1.0:
                model_score = technical_average
            confidence = max(0.0, min(1.0, float(raw.get("confidence_0_1", 0.5))))
            recommendation = raw.get("recommendation") if raw.get("recommendation") in RECOMMENDATIONS else "требуется дополнительная проверка"
            if confidence < 0.55:
                recommendation = "требуется дополнительная проверка"
            result = {
                "recommendation": recommendation,
                "overall_score_0_10": round(model_score, 2),
                "confidence_0_1": confidence,
                "summary": str(raw.get("summary") or "Недостаточно данных для надёжного итогового вывода.").strip(),
                "competencies": self._normalize_competencies(raw.get("competencies"), transcripts),
                "vacancy_coverage": self._normalize_coverage(raw.get("vacancy_coverage"), transcripts),
                "strengths": self._normalize_strengths(raw.get("strengths"), transcripts),
                "issues": self._normalize_issues(raw.get("issues"), transcripts),
                "uncovered_vacancy_topics": self._strings(raw.get("uncovered_vacancy_topics")),
            }
        except Exception as exc:
            result = {
                "recommendation": "требуется дополнительная проверка",
                "overall_score_0_10": round(technical_average, 2),
                "confidence_0_1": 0.0,
                "summary": f"Числовой результат рассчитан по ответам, но итоговый LLM-отчёт требует ручной проверки: {exc}",
                "competencies": [],
                "vacancy_coverage": {"must_have": [], "nice_to_have": []},
                "strengths": [],
                "issues": [],
                "uncovered_vacancy_topics": [],
            }

        # Storage compatibility: existing DB columns are reused without a destructive
        # migration, but they now carry the canonical structured evaluation.
        result.update({
            "overall_score": result["overall_score_0_10"],
            "weaknesses": result["issues"],
            "detected_skills": result["competencies"],
            "areas_to_check": result["uncovered_vacancy_topics"],
            "risk_factors": {
                "confidence_0_1": result["confidence_0_1"],
                "vacancy_coverage": result["vacancy_coverage"],
            },
        })
        return result

    async def extract_tags_from_vacancy(self, description: str, requirements: str) -> List[str]:
        from config import TAGS_KEYWORDS

        text = f"{description} {requirements}".lower()
        detected = []
        for tag, keywords in TAGS_KEYWORDS.items():
            if any(keyword.lower() in text for keyword in keywords):
                detected.append(tag)
        return list(dict.fromkeys(detected))

    async def suggest_questions_for_vacancy(
        self,
        detected_tags: List[str],
        grade: str,
        available_questions: List[Dict[str, Any]],
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        detected = set(detected_tags)
        scored = []
        for question in available_questions:
            tags = set(question.get("tags", []))
            score = len(tags & detected)
            if question.get("competency") in detected:
                score += 2
            if score > 0:
                scored.append((score, question))
        scored.sort(key=lambda item: item[0], reverse=True)
        result = []
        seen = set()
        for _, question in scored:
            key = str(question.get("id") or question.get("question"))
            if key in seen:
                continue
            seen.add(key)
            result.append(question)
            if len(result) >= limit:
                break
        return result


llm_service = LLMService()
