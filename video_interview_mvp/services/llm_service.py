"""LLM helpers for answer evaluation, report generation and question selection."""
import json
from typing import Any, Dict, List

import httpx

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, SCORE_MAX, SCORE_MIN


class LLMService:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Talent Interview MVP",
        }

    async def _call_llm(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        if not self.api_key:
            return self._get_mock_response(messages)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2400,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    def _get_mock_response(self, messages: List[Dict[str, str]]) -> str:
        last_message = messages[-1]["content"] if messages else ""
        lowered = last_message.lower()
        if "оцени ответ" in lowered:
            return json.dumps(
                {
                    "score": 7.0,
                    "technical_correctness": 3,
                    "depth": 2,
                    "practical_example": 2,
                    "personal_contribution": 2,
                    "scale_and_metrics": 1,
                    "analysis": "Ответ показывает понимание темы, но практические детали и измеримый результат раскрыты не полностью.",
                    "strengths": ["Корректно описаны основные концепции"],
                    "weaknesses": ["Недостаточно конкретики по личному вкладу и метрикам"],
                    "covered_must_have": [],
                    "covered_nice_to_have": [],
                    "detected_red_flags": [],
                    "evidence_quotes": ["mock: ответ кандидата доступен только в demo-режиме"],
                    "confidence": 0.75,
                },
                ensure_ascii=False,
            )
        if "итоговый отчет" in lowered or "сформируй заключение" in lowered:
            return json.dumps(
                {
                    "overall_score": 7.0,
                    "recommendation": "требуется дополнительная проверка",
                    "summary": "Кандидат демонстрирует рабочее понимание основных тем. Для уверенного решения не хватает нескольких подтверждённых практических деталей.",
                    "strengths": ["Понимание ключевых технических концепций"],
                    "weaknesses": ["Не во всех ответах достаточно конкретных примеров и метрик"],
                    "detected_skills": ["Python", "Backend"],
                    "areas_to_check": ["Практический опыт и масштаб задач"],
                    "risk_factors": [],
                },
                ensure_ascii=False,
            )
        return "OK"

    @staticmethod
    def _parse_json(response: str) -> Dict[str, Any]:
        start = response.find("{")
        end = response.rfind("}") + 1
        return json.loads(response[start:end] if start >= 0 and end > start else response)

    async def analyze_answer(
        self,
        question: str,
        reference_answer: str,
        must_have: List[str],
        nice_to_have: List[str],
        red_flags: List[str],
        candidate_transcript: str,
    ) -> Dict[str, Any]:
        prompt = f"""Ты технический эксперт. ОЦЕНИ ответ кандидата строго по содержанию ответа.

ВОПРОС:
{question}

ОРИЕНТИР СИЛЬНОГО ОТВЕТА:
{reference_answer}

MUST-HAVE СИГНАЛЫ:
{chr(10).join(f'- {item}' for item in must_have) or '- нет'}

NICE-TO-HAVE СИГНАЛЫ:
{chr(10).join(f'- {item}' for item in nice_to_have) or '- нет'}

КРАСНЫЕ ФЛАГИ:
{chr(10).join(f'- {item}' for item in red_flags) or '- нет'}

ОТВЕТ КАНДИДАТА:
{candidate_transcript}

Правила оценки:
1. Не додумывай опыт и знания, которых кандидат не озвучил.
2. Не штрафуй за навык, который этим вопросом не проверяется.
3. Теоретическое упоминание термина не равно практическому опыту.
4. Отличай корректность, глубину, реальный пример, личный вклад и масштаб/метрики.
5. Все существенные выводы подкрепи короткими фрагментами из ответа кандидата.
6. Если информации мало, понижай confidence, а не выдумывай вывод.

Верни ТОЛЬКО JSON:
{{
  "score": <0..10>,
  "technical_correctness": <0..4>,
  "depth": <0..4>,
  "practical_example": <0..4>,
  "personal_contribution": <0..4>,
  "scale_and_metrics": <0..4>,
  "analysis": "<2-4 предложения>",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "covered_must_have": ["..."],
  "covered_nice_to_have": ["..."],
  "detected_red_flags": ["..."],
  "evidence_quotes": ["короткая дословная цитата кандидата"],
  "confidence": <0..1>
}}"""
        try:
            result = self._parse_json(await self._call_llm([{"role": "user", "content": prompt}], temperature=0.1))
            result["score"] = max(SCORE_MIN, min(SCORE_MAX, float(result.get("score", 5))))
            result["confidence"] = max(0.0, min(1.0, float(result.get("confidence", 0.5))))
            for field in ("technical_correctness", "depth", "practical_example", "personal_contribution", "scale_and_metrics"):
                result[field] = max(0, min(4, int(result.get(field, 0))))
            for field in (
                "strengths",
                "weaknesses",
                "covered_must_have",
                "covered_nice_to_have",
                "detected_red_flags",
                "evidence_quotes",
            ):
                if not isinstance(result.get(field), list):
                    result[field] = []
            return result
        except Exception as exc:
            return {
                "score": 5.0,
                "technical_correctness": 0,
                "depth": 0,
                "practical_example": 0,
                "personal_contribution": 0,
                "scale_and_metrics": 0,
                "analysis": f"Не удалось надёжно разобрать LLM-оценку: {exc}",
                "strengths": [],
                "weaknesses": [],
                "covered_must_have": [],
                "covered_nice_to_have": [],
                "detected_red_flags": [],
                "evidence_quotes": [],
                "confidence": 0.0,
            }

    async def generate_final_report(
        self,
        vacancy_title: str,
        vacancy_requirements: str,
        answers_data: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        answer_blocks = []
        numeric_scores = []
        critical_flags = []
        for index, answer in enumerate(answers_data, 1):
            if answer.get("score") is not None:
                numeric_scores.append(float(answer["score"]))
            critical_flags.extend(answer.get("detected_red_flags", []) or [])
            answer_blocks.append(
                f"""Вопрос {index}: {answer.get('question', '')}
Ответ: {answer.get('transcript', '')}
Оценка: {answer.get('score', 'N/A')}/10
Анализ: {answer.get('analysis', '')}
Сильные стороны: {', '.join(answer.get('strengths', []) or [])}
Слабые стороны: {', '.join(answer.get('weaknesses', []) or [])}
Покрытые must-have: {', '.join(answer.get('covered_must_have', []) or [])}
Red flags: {', '.join(answer.get('detected_red_flags', []) or [])}
---"""
            )

        base_score = sum(numeric_scores) / len(numeric_scores) if numeric_scores else 5.0
        prompt = f"""Ты технический эксперт, формирующий ИТОГОВЫЙ ОТЧЕТ после асинхронного интервью.

ВАКАНСИЯ: {vacancy_title}

ИСХОДНЫЙ ТЕКСТ ВАКАНСИИ:
{vacancy_requirements}

РЕЗУЛЬТАТЫ ОТВЕТОВ:
{chr(10).join(answer_blocks)}

Средняя числовая оценка ответов, рассчитанная системой: {base_score:.2f}/10.

Правила:
1. Отчёт должен опираться только на ответы и исходный текст вакансии.
2. Не превращай отсутствие упоминания навыка в доказательство отсутствия навыка.
3. Не называй навык подтверждённым, если он не подкреплён ответом.
4. Разделяй реальные сильные стороны и темы, которые нужно проверить дополнительно.
5. Не делай выводов по внешности, голосу, акценту или иным нерелевантным признакам.
6. Итоговая рекомендация — рекомендация AI, а не финальное решение о найме.
7. overall_score должен быть близок к средней оценке ответов; отклонение больше 1.0 допустимо только при явных технических red flags.

СФОРМИРУЙ итоговый отчет и верни ТОЛЬКО JSON:
{{
  "overall_score": <0..10>,
  "recommendation": "подходит" | "не подходит" | "требуется дополнительная проверка",
  "summary": "<2-4 предложения>",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "detected_skills": ["только навыки, подтверждённые ответами"],
  "areas_to_check": ["..."],
  "risk_factors": ["только риски, имеющие основание в ответах"]
}}"""
        try:
            result = self._parse_json(await self._call_llm([{"role": "user", "content": prompt}], temperature=0.1))
            model_score = max(0.0, min(10.0, float(result.get("overall_score", base_score))))
            if not critical_flags and abs(model_score - base_score) > 1.0:
                model_score = base_score
            result["overall_score"] = round(model_score, 2)

            # Recommendation is derived deterministically after the LLM has written
            # the qualitative report. This makes repeated runs more reproducible.
            if critical_flags or model_score < 5.0:
                result["recommendation"] = "не подходит"
            elif model_score >= 7.5:
                result["recommendation"] = "подходит"
            else:
                result["recommendation"] = "требуется дополнительная проверка"

            for field in ("strengths", "weaknesses", "detected_skills", "areas_to_check", "risk_factors"):
                if not isinstance(result.get(field), list):
                    result[field] = []
            return result
        except Exception as exc:
            if critical_flags or base_score < 5.0:
                recommendation = "не подходит"
            elif base_score >= 7.5:
                recommendation = "подходит"
            else:
                recommendation = "требуется дополнительная проверка"
            return {
                "overall_score": round(base_score, 2),
                "recommendation": recommendation,
                "summary": f"Числовой результат рассчитан по ответам. Текстовый AI-отчёт не удалось сформировать надёжно: {exc}",
                "strengths": [],
                "weaknesses": [],
                "detected_skills": [],
                "areas_to_check": ["Проверить ответы вручную"],
                "risk_factors": critical_flags,
            }

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
            if question["id"] in seen:
                continue
            seen.add(question["id"])
            result.append(question)
            if len(result) >= limit:
                break
        return result


llm_service = LLMService()
