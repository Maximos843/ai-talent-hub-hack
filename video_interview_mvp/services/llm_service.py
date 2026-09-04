"""
Сервисы для работы с LLM (анализ, скоринг, генерация отчетов)
"""
import json
import httpx
from typing import List, Dict, Any, Optional
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, SCORE_MIN, SCORE_MAX


class LLMService:
    """Сервис для работы с LLM через OpenRouter/Qwen API"""
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Video Interview MVP"
        }
    
    async def _call_llm(self, messages: List[Dict[str, str]], temperature: float = 0.3) -> str:
        """Вызов LLM API"""
        if not self.api_key:
            # Для тестирования без ключа возвращаем заглушку
            return self._get_mock_response(messages)
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2000
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    def _get_mock_response(self, messages: List[Dict[str, str]]) -> str:
        """Заглушка для тестирования без API ключа"""
        last_message = messages[-1]["content"] if messages else ""
        
        if "оцени ответ" in last_message.lower():
            return json.dumps({
                "score": 7,
                "analysis": "Ответ достаточно полный, но требует уточнения некоторых деталей.",
                "strengths": ["Хорошее понимание основных концепций"],
                "weaknesses": ["Недостаточно примеров из практики"],
                "red_flags": []
            }, ensure_ascii=False)
        
        if "итоговый отчет" in last_message.lower() or "сформируй заключение" in last_message.lower():
            return json.dumps({
                "overall_score": 7.5,
                "recommendation": "требуется дополнительная проверка",
                "summary": "Кандидат продемонстрировал хорошие теоретические знания, но практический опыт требует дополнительной проверки.",
                "strengths": [
                    "Глубокое понимание архитектурных принципов",
                    "Знание современных инструментов CI/CD",
                    "Умение работать с контейнеризацией"
                ],
                "weaknesses": [
                    "Недостаточно примеров масштабных проектов",
                    "Слабое знание методов оптимизации производительности"
                ],
                "detected_skills": ["Python", "Docker", "CI/CD", "REST API"],
                "areas_to_check": [
                    "Опыт работы с высоконагруженными системами",
                    "Практика оптимизации баз данных"
                ],
                "risk_factors": [
                    "Возможно отсутствие опыта управления командой"
                ]
            }, ensure_ascii=False)
        
        return "OK"
    
    async def analyze_answer(
        self,
        question: str,
        reference_answer: str,
        must_have: List[str],
        nice_to_have: List[str],
        red_flags: List[str],
        candidate_transcript: str
    ) -> Dict[str, Any]:
        """Анализ ответа кандидата на вопрос"""
        
        prompt = f"""Ты технический эксперт, оценивающий ответы кандидата на собеседовании.

ВОПРОС: {question}

ЭТАЛОННЫЙ ОТВЕТ: {reference_answer}

ОБЯЗАТЕЛЬНЫЕ ТЕМЫ (must-have):
{chr(10).join(f'- {item}' for item in must_have)}

ЖЕЛАТЕЛЬНЫЕ ТЕМЫ (nice-to-have):
{chr(10).join(f'- {item}' for item in nice_to_have)}

КРАСНЫЕ ФЛАГИ (red flags):
{chr(10).join(f'- {item}' for item in red_flags)}

ОТВЕТ КАНДИДАТА:
{candidate_transcript}

ОЦЕНИ ответ кандидата по шкале от 0 до 10 и предоставь анализ в формате JSON:
{{
    "score": <число от 0 до 10>,
    "analysis": "<краткий анализ ответа>",
    "strengths": [<сильные стороны ответа>],
    "weaknesses": [<слабые стороны ответа>],
    "covered_must_have": [<какие must-have темы покрыты>],
    "covered_nice_to_have": [<какие nice-to-have темы покрыты>],
    "detected_red_flags": [<какие red flags обнаружены>]
}}

Верни ТОЛЬКО JSON без дополнительного текста."""

        messages = [{"role": "user", "content": prompt}]
        response = await self._call_llm(messages)
        
        try:
            # Пытаемся извлечь JSON из ответа
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                result = json.loads(json_str)
            else:
                result = json.loads(response)
            
            # Валидация и нормализация
            result['score'] = max(SCORE_MIN, min(SCORE_MAX, float(result.get('score', 5))))
            
            return result
        except Exception as e:
            return {
                "score": 5.0,
                "analysis": f"Ошибка анализа: {str(e)}",
                "strengths": [],
                "weaknesses": [],
                "covered_must_have": [],
                "covered_nice_to_have": [],
                "detected_red_flags": []
            }
    
    async def generate_final_report(
        self,
        vacancy_title: str,
        vacancy_requirements: str,
        answers_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Генерация итогового отчета по всем ответам"""
        
        answers_summary = []
        for i, ans in enumerate(answers_data, 1):
            answers_summary.append(f"""
Вопрос {i}: {ans.get('question', 'N/A')}
Ответ кандидата: {ans.get('transcript', 'N/A')}
Оценка: {ans.get('score', 'N/A')}/10
Анализ: {ans.get('analysis', 'N/A')}
Сильные стороны: {', '.join(ans.get('strengths', []))}
Слабые стороны: {', '.join(ans.get('weaknesses', []))}
---
""")
        
        prompt = f"""Ты технический эксперт, формирующий итоговое заключение по кандидату.

ВАКАНСИЯ: {vacancy_title}

ТРЕБОВАНИЯ:
{vacancy_requirements}

РЕЗУЛЬТАТЫ ИНТЕРВЬЮ:
{chr(10).join(answers_summary)}

СФОРМИРУЙ итоговое заключение в формате JSON:
{{
    "overall_score": <средняя оценка от 0 до 10>,
    "recommendation": "<одна из: 'подходит', 'не подходит', 'требуется дополнительная проверка'>",
    "summary": "<общее резюме по кандидату на 2-3 предложения>",
    "strengths": [<сильные стороны кандидата>],
    "weaknesses": [<зоны роста кандидата>],
    "detected_skills": [<выявленные навыки и технологии>],
    "areas_to_check": [<вопросы для дополнительной проверки на следующем этапе>],
    "risk_factors": [<потенциальные риски при найме>]
}}

Критерии рекомендации:
- "подходит": overall_score >= 7.5 и нет критических red flags
- "не подходит": overall_score < 5 или есть критические red flags
- "требуется дополнительная проверка": все остальные случаи

Верни ТОЛЬКО JSON без дополнительного текста."""

        messages = [{"role": "user", "content": prompt}]
        response = await self._call_llm(messages, temperature=0.2)
        
        try:
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                result = json.loads(json_str)
            else:
                result = json.loads(response)
            
            # Валидация
            result['overall_score'] = max(0, min(10, float(result.get('overall_score', 5))))
            
            valid_recommendations = ["подходит", "не подходит", "требуется дополнительная проверка"]
            if result.get('recommendation') not in valid_recommendations:
                if result['overall_score'] >= 7.5:
                    result['recommendation'] = "подходит"
                elif result['overall_score'] < 5:
                    result['recommendation'] = "не подходит"
                else:
                    result['recommendation'] = "требуется дополнительная проверка"
            
            return result
        except Exception as e:
            return {
                "overall_score": 5.0,
                "recommendation": "требуется дополнительная проверка",
                "summary": f"Ошибка генерации отчета: {str(e)}",
                "strengths": [],
                "weaknesses": [],
                "detected_skills": [],
                "areas_to_check": [],
                "risk_factors": []
            }
    
    async def extract_tags_from_vacancy(self, description: str, requirements: str) -> List[str]:
        """Извлечение тегов из описания вакансии"""
        from config import TAGS_KEYWORDS
        
        text = f"{description} {requirements}".lower()
        detected_tags = []
        
        for tag, keywords in TAGS_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    detected_tags.append(tag)
                    break
        
        return list(set(detected_tags))
    
    async def suggest_questions_for_vacancy(
        self,
        detected_tags: List[str],
        grade: str,
        available_questions: List[Dict[str, Any]],
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Подбор вопросов для вакансии на основе тегов и грейда"""
        
        # Фильтрация вопросов по тегам
        scored_questions = []
        for q in available_questions:
            q_tags = set(q.get('tags', []))
            matching_tags = q_tags.intersection(set(detected_tags))
            score = len(matching_tags)
            
            # Бонус за совпадение competency с тегами
            if q.get('competency') in detected_tags:
                score += 2
            
            if score > 0:
                scored_questions.append((score, q))
        
        # Сортировка по релевантности
        scored_questions.sort(key=lambda x: x[0], reverse=True)
        
        # Возвращаем топ-N уникальных вопросов
        seen_ids = set()
        result = []
        for score, q in scored_questions:
            if q['id'] not in seen_ids:
                seen_ids.add(q['id'])
                result.append(q)
                if len(result) >= limit:
                    break
        
        return result


llm_service = LLMService()
