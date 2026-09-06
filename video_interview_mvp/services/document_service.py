"""Разбор документов рекрутера: текст вакансии и резюме кандидата.

Вынесено отдельно от ``llm_service``, который активно правит ML-часть команды:
здесь только входные документы рабочего места, конфликтовать с ним не нужно.
"""
from __future__ import annotations

import io
import json
from typing import Any, Dict, List, Optional

from services import llm_service

MAX_DOCUMENT_CHARS = 24000


class DocumentError(ValueError):
    """Файл не удалось прочитать — сообщение показывается рекрутеру как есть."""


def extract_text(payload: bytes, filename: str) -> str:
    """Достаёт текст из PDF или текстового файла."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover
            raise DocumentError("На сервере не установлен pypdf — загрузите текстом") from exc
        try:
            reader = PdfReader(io.BytesIO(payload))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise DocumentError("Не удалось прочитать PDF. Проверьте файл или вставьте текст вручную") from exc
        if not text.strip():
            raise DocumentError("В PDF не нашлось текстового слоя — похоже, это скан. Вставьте текст вручную")
        return text.strip()[:MAX_DOCUMENT_CHARS]

    if name.endswith((".txt", ".md", ".rtf")) or not name:
        try:
            return payload.decode("utf-8", errors="ignore").strip()[:MAX_DOCUMENT_CHARS]
        except Exception as exc:
            raise DocumentError("Не удалось прочитать файл как текст") from exc

    if name.endswith(".docx"):
        raise DocumentError("DOCX пока не поддерживается — сохраните в PDF или вставьте текст")

    raise DocumentError("Поддерживаются PDF и текстовые файлы")


def _weighted(items: Any) -> List[Dict[str, Any]]:
    """Нормализует требование в {skill, weight 1..3, evidence}."""
    result: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str) and item.strip():
            result.append({"skill": item.strip()[:160], "weight": 2, "evidence": ""})
            continue
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or item.get("requirement") or "").strip()
        if not skill:
            continue
        try:
            weight = int(item.get("weight", 2))
        except (TypeError, ValueError):
            weight = 2
        result.append(
            {
                "skill": skill[:160],
                "weight": min(3, max(1, weight)),
                "evidence": str(item.get("evidence") or "").strip()[:400],
            }
        )
    return result[:20]


def _strings(items: Any, limit: int = 12) -> List[str]:
    return [str(item).strip()[:220] for item in (items if isinstance(items, list) else []) if str(item).strip()][:limit]


async def parse_vacancy(vacancy_text: str) -> Dict[str, Any]:
    """Разбирает текст вакансии в структуру с весами требований.

    Веса нужны, чтобы промах по обязательному навыку не выглядел «зоной роста» —
    это прямой вывод из разбора baseline заказчика.
    """
    prompt = f"""Ты опытный технический рекрутер. Разбери текст вакансии в структуру.

ТЕКСТ ВАКАНСИИ:
{vacancy_text[:MAX_DOCUMENT_CHARS]}

Правила:
1. Обязательное требование — то, без чего кандидата не возьмут. Желательное — плюс, но не блокер.
2. weight: 3 — критично и указан продакшн-опыт, 2 — обязательно, 1 — упомянуто вскользь.
3. evidence — короткая цитата из текста вакансии, подтверждающая требование.
4. Ничего не выдумывай: если грейд или срок опыта не указан, оставь пустым.
5. stop_factors — обязательно проверь текст на внутренние противоречия и выпиши их:
   - грейд не сходится с требуемым стажем (например, "Middle" и "опыт от 5 лет");
   - разные сроки опыта в разных местах текста;
   - требование заявлено обязательным, но нигде не раскрыто в обязанностях;
   - взаимоисключающие требования.
   Если противоречий нет — верни пустой список. Не выдумывай их.

6. tags — КОРОТКИЕ нормализованные названия технологий и навыков для поиска
   вопросов. Строго 1-2 слова, нижний регистр, латиница где это принято.
   Правильно: "react", "typescript", "next.js", "rest api", "postgresql", "английский".
   Неправильно: "Сильный React: функциональные компоненты, хуки, контекст",
   "5+ лет коммерческого опыта". Одно требование может дать несколько тегов.
   Не включай в теги общие слова вроде "разработка", "опыт", "продакшен".

Верни ТОЛЬКО JSON:
{{"title": str, "grade": "junior|middle|senior|principal|", "summary": str,
 "must_have": [{{"skill": str, "weight": 1-3, "evidence": str}}],
 "nice_to_have": [{{"skill": str, "weight": 1-3, "evidence": str}}],
 "responsibilities": [str], "stop_factors": [str], "tags": [str]}}"""

    raw = await llm_service._call_llm(
        [
            {"role": "system", "content": "Ты возвращаешь только валидный JSON без пояснений."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    try:
        data = llm_service._parse_json(raw)
    except Exception:
        data = {}

    return {
        "title": str(data.get("title") or "").strip()[:160],
        "grade": str(data.get("grade") or "").strip().lower(),
        "summary": str(data.get("summary") or "").strip()[:900],
        "must_have": _weighted(data.get("must_have")),
        "nice_to_have": _weighted(data.get("nice_to_have")),
        "responsibilities": _strings(data.get("responsibilities")),
        "stop_factors": _strings(data.get("stop_factors"), limit=8),
        "tags": _normalize_tags(data.get("tags")),
    }


MAX_TAG_WORDS = 3
MAX_TAG_CHARS = 28
_TAG_STOPWORDS = {"опыт", "работы", "разработка", "разработки", "знание", "понимание", "лет", "год", "года"}


def _normalize_tags(value: Any) -> List[str]:
    """Приводит теги к короткому виду и отбрасывает фразы.

    Модель регулярно возвращает в tags целые требования. Длинный тег ломает и
    подбор вопросов, и вёрстку, поэтому фильтруем здесь, а не в интерфейсе.
    """
    result: List[str] = []
    for raw in value if isinstance(value, list) else []:
        tag = str(raw).strip().lower().strip(".,;:")
        if not tag or len(tag) > MAX_TAG_CHARS:
            continue
        words = [word for word in tag.split() if word]
        if len(words) > MAX_TAG_WORDS:
            continue
        if all(word in _TAG_STOPWORDS for word in words):
            continue
        if tag not in result:
            result.append(tag)
    return result[:15]


async def match_resume(vacancy_text: str, must_have: List[Dict[str, Any]], resume_text: str) -> Dict[str, Any]:
    """Оценивает резюме относительно требований вакансии.

    Это предварительный фильтр до интервью, а не замена оценке ответов: судим
    только по тому, что кандидат написал сам, и честно помечаем непроверяемое.
    """
    requirements = "\n".join(f"- {item['skill']} (вес {item['weight']})" for item in must_have) or "- не разобраны"
    prompt = f"""Ты технический рекрутер. Оцени резюме кандидата относительно требований вакансии.

ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
{requirements}

ТЕКСТ ВАКАНСИИ:
{vacancy_text[:8000]}

РЕЗЮМЕ КАНДИДАТА:
{resume_text[:MAX_DOCUMENT_CHARS]}

Правила:
1. Оценивай только то, что кандидат заявил в резюме. Не додумывай опыт.
2. status по каждому требованию: "confirmed" — есть подтверждение с деталями,
   "claimed" — упомянуто без подтверждения, "missing" — не найдено.
3. "claimed" и "missing" — разные вещи. Не выдавай отсутствие упоминания за отсутствие навыка.
4. evidence — короткая цитата из резюме.
5. match_score 0..10 — насколько резюме закрывает обязательные требования с учётом весов.

Верни ТОЛЬКО JSON:
{{"match_score": 0-10, "summary": str, "years_experience": str, "current_role": str,
 "details": [{{"requirement": str, "status": "confirmed|claimed|missing", "evidence": str}}],
 "detected_skills": [str], "to_verify": [str]}}"""

    raw = await llm_service._call_llm(
        [
            {"role": "system", "content": "Ты возвращаешь только валидный JSON без пояснений."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    try:
        data = llm_service._parse_json(raw)
    except Exception:
        data = {}

    try:
        score = round(min(10.0, max(0.0, float(data.get("match_score", 0)))), 1)
    except (TypeError, ValueError):
        score = 0.0

    details = []
    for item in data.get("details") if isinstance(data.get("details"), list) else []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        details.append(
            {
                "requirement": str(item.get("requirement") or "").strip()[:200],
                "status": status if status in {"confirmed", "claimed", "missing"} else "missing",
                "evidence": str(item.get("evidence") or "").strip()[:400],
            }
        )

    return {
        "match_score": score,
        "summary": str(data.get("summary") or "").strip()[:900],
        "details": details[:20],
        "parsed": {
            "years_experience": str(data.get("years_experience") or "").strip()[:80],
            "current_role": str(data.get("current_role") or "").strip()[:160],
            "detected_skills": _strings(data.get("detected_skills"), limit=25),
            "to_verify": _strings(data.get("to_verify"), limit=10),
        },
    }


async def generate_questions(
    vacancy_text: str,
    grade: str,
    skills: List[str],
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Достраивает вопросы под навыки, которых нет в банке.

    Рамка продукта описывает гибридную схему: база знаний даёт ядро по
    компетенциям, LLM закрывает остальное. Без этой достройки редкий стек
    остаётся непроверенным, и промах по нему невозможно отличить от зоны роста.
    Формат совпадает с банком, поэтому дальше вопрос живёт как обычный.
    """
    skills = [skill for skill in skills if skill][:8]
    if not skills:
        return []

    prompt = f"""Ты технический интервьюер. Составь вопросы для устного интервью по навыкам,
которых нет в нашем банке вопросов.

ГРЕЙД КАНДИДАТА: {grade or 'middle'}

НАВЫКИ, КОТОРЫЕ НУЖНО ПРОВЕРИТЬ:
{chr(10).join(f'- {skill}' for skill in skills)}

КОНТЕКСТ ВАКАНСИИ:
{vacancy_text[:6000]}

Правила:
1. Не более {limit} вопросов суммарно.
2. КАЖДЫЙ вопрос посвящён СВОЕМУ навыку из списка выше. Не прицепляй одну и ту же
   технологию ко всем вопросам: если в списке есть React, TypeScript и Sentry, то
   вопрос про Sentry не должен начинаться со слов "в проекте на React".
   Идти по списку сверху вниз, по одному вопросу на навык.
3. Не повторяй одну и ту же формулировку. Меняй заход: где-то про принятое решение,
   где-то про инцидент и его разбор, где-то про выбор между вариантами.
4. Вопрос устный, на него отвечают голосом 1-2 минуты. Никакого кода и вычислений в уме.
5. Спрашивай про личный опыт и принятые решения, а не про определения из учебника:
   не "что такое хук useMemo", а "расскажите, где вы применяли мемоизацию и что она дала".
6. must_have — сигналы, без которых ответ считается слабым. nice_to_have — что усиливает ответ.
7. red_flags — конкретные фактические ошибки или тревожные признаки в ответе.
8. reference_answer — краткий ориентир сильного ответа, 2-3 предложения.
9. possible_extra_questions — 1-2 уточнения, если ответ окажется поверхностным.
10. competency — имя навыка, под который написан вопрос, латиницей через подчёркивание.
    Ровно один навык, без склеек вида next_js_sentry.

Верни ТОЛЬКО JSON:
{{"questions": [{{"question": str, "competency": str, "tags": [str],
 "reference_answer": str, "must_have": [str], "nice_to_have": [str],
 "red_flags": [str], "possible_extra_questions": [str]}}]}}"""

    raw = await llm_service._call_llm(
        [
            {"role": "system", "content": "Ты возвращаешь только валидный JSON без пояснений."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    try:
        data = llm_service._parse_json(raw)
    except Exception:
        return []

    known = [skill.lower() for skill in skills]
    known_set = set(known)

    def _resolve_tags(item: Dict[str, Any], text: str, index: int) -> List[str]:
        """Определяет навык вопроса. Раньше при промахе брались два случайных
        навыка из множества, и вопрос про React уезжал с тегами typescript."""
        tags = [tag for tag in _normalize_tags(item.get("tags")) if tag in known_set]
        if tags:
            return tags
        # competency модель возвращает через подчёркивание: next_js -> next.js
        competency = str(item.get("competency") or "").strip().lower()
        for skill in known:
            if competency and competency.replace("_", "") == skill.replace(".", "").replace(" ", ""):
                return [skill]
        # иначе ищем навык прямо в тексте вопроса
        lowered = text.lower()
        mentioned = [skill for skill in known if skill in lowered]
        if mentioned:
            return mentioned[:2]
        # последний рубеж — порядок: промпт требует идти по списку сверху вниз
        return [known[index]] if index < len(known) else []

    result: List[Dict[str, Any]] = []
    for index, item in enumerate(data.get("questions") if isinstance(data.get("questions"), list) else []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        if len(text) < 15:
            continue
        tags = _resolve_tags(item, text, index)
        result.append(
            {
                "question": text[:600],
                "competency": (str(item.get("competency") or "generated").strip().lower() or "generated")[:60],
                "tags": tags,
                "reference_answer": str(item.get("reference_answer") or "").strip()[:900],
                "must_have": _strings(item.get("must_have"), limit=6),
                "nice_to_have": _strings(item.get("nice_to_have"), limit=6),
                "red_flags": _strings(item.get("red_flags"), limit=6),
                "possible_extra_questions": _strings(item.get("possible_extra_questions"), limit=2),
                "generated": True,
            }
        )
    return result[:limit]


async def enrich_question(
    question_text: str,
    vacancy_text: str,
    grade: str,
    known_skills: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Достраивает рубрику под вопрос, который рекрутер написал сам.

    Без must-have сигналов и красных флагов вопрос нечем оценивать: пайплайн
    сравнивает ответ именно с ними. Поэтому свой вопрос нельзя просто положить
    в список — к нему нужна та же структура, что у банковских.
    """
    skills = ", ".join(known_skills or []) or "не заданы"
    prompt = f"""Ты технический интервьюер. Приведи вопрос рекрутера в рабочий вид
и составь рубрику оценки ответа.

ВОПРОС РЕКРУТЕРА:
{question_text}

ГРЕЙД КАНДИДАТА: {grade or 'middle'}
НАВЫКИ ВАКАНСИИ: {skills}

КОНТЕКСТ ВАКАНСИИ:
{vacancy_text[:6000]}

СНАЧАЛА приведи формулировку в порядок — поле question:
- Вопрос прозвучит голосом, кандидат услышит его от интервьюера. Он должен быть
  грамотным и законченным: заглавная буква, знак вопроса, никакого сленга.
- Смысл и уровень сложности не меняй. Не добавляй требований, которых в исходном
  вопросе не было, и не сужай его.
- Разверни телеграфную запись в полноценный вопрос: "как работает ивент луп" ->
  "Расскажите, как устроен event loop в JavaScript и как он обеспечивает
  неблокирующую обработку в однопоточной среде."
- Технические термины пиши общепринято: "ивент луп" -> "event loop", "промисы" ->
  "промисы (Promise)".
- Если вопрос уже сформулирован нормально, верни его без изменений.
- rewritten = true, только если формулировка реально изменилась.

ЗАТЕМ определи тип вопроса:
- ТЕХНИЧЕСКИЙ — проверяет знания, инструменты, инженерные решения.
- МОТИВАЦИОННЫЙ — про причины ухода, ожидания от работы, интерес к компании, планы.

Для МОТИВАЦИОННОГО вопроса действуют отдельные правила:
- НЕ требуй упоминания конкретных технологий из вакансии. Ответ кандидата о причинах
  ухода не обязан содержать названия фреймворков — это вопрос не про стек.
- competency = "motivation", tags = ["мотивация"].
- must_have формулируй через содержательность ответа: конкретность причины, связь с
  собственными целями, отсутствие противоречий с резюме.
- red_flags — только то, что действительно тревожит: обвинение бывших коллег без фактов,
  противоречие ранее сказанному, уклонение от прямого ответа. Недовольство зарплатой
  красным флагом НЕ является.
- reference_answer опиши от третьего лица: "сильный ответ содержит…", а не от лица кандидата.

Общие правила:
1. must_have — 2-4 сигнала, без которых ответ считается слабым. Формулируй проверяемо:
   не "хорошо разбирается", а "называет конкретный инструмент замера и приводит цифру".
2. nice_to_have — 2-3 сигнала, которые усиливают ответ, но не обязательны.
3. red_flags — 1-3 конкретные фактические ошибки или тревожные признаки.
4. reference_answer — ориентир сильного ответа, 2-3 предложения, от третьего лица.
5. possible_extra_questions — 1-2 уточнения на случай поверхностного ответа.
6. competency — одно короткое имя компетенции латиницей через подчёркивание.
7. tags — 1-3 коротких тега в нижнем регистре.
8. Ничего не придумывай сверх того, что вопрос реально проверяет.
9. Пиши по-русски, без вставок английских слов внутри русских предложений.

Верни ТОЛЬКО JSON:
{{"question": str, "rewritten": true|false,
 "competency": str, "tags": [str], "reference_answer": str,
 "must_have": [str], "nice_to_have": [str], "red_flags": [str],
 "possible_extra_questions": [str]}}"""

    raw = await llm_service._call_llm(
        [
            {"role": "system", "content": "Ты возвращаешь только валидный JSON без пояснений."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    try:
        data = llm_service._parse_json(raw)
    except Exception:
        data = {}

    tags = _normalize_tags(data.get("tags"))
    competency = (str(data.get("competency") or "").strip().lower() or "custom")[:60]
    original = question_text.strip()[:600]
    polished = str(data.get("question") or "").strip()[:600] or original
    # Модель иногда отвечает "rewritten": true, ничего не изменив, и наоборот —
    # верим фактическому тексту, а не флагу.
    rewritten = polished != original
    return {
        "question": polished,
        "original_question": original,
        "rewritten": rewritten,
        "competency": competency,
        "tags": tags or [competency.replace("_", " ")],
        "reference_answer": str(data.get("reference_answer") or "").strip()[:900],
        "must_have": _strings(data.get("must_have"), limit=5),
        "nice_to_have": _strings(data.get("nice_to_have"), limit=4),
        "red_flags": _strings(data.get("red_flags"), limit=4),
        "possible_extra_questions": _strings(data.get("possible_extra_questions"), limit=2),
    }


async def polish_transcript(raw: str, question: str, keyterms: Optional[List[str]] = None) -> str:
    """Приводит сырой транскрипт в читаемый вид, не меняя смысла.

    ASR слышит «вентлуп» вместо «event loop» и не ставит абзацев. Чинить это
    правилами бесполезно — нужен контекст вопроса. Работает на быстрой модели,
    потому что кандидат ждёт результат прямо во время интервью.
    """
    text = " ".join((raw or "").split())
    if len(text) < 15:
        return text

    hints = ", ".join(dict.fromkeys(keyterms or []))[:600]
    prompt = f"""Приведи расшифровку устного ответа в читаемый вид.

ВОПРОС, НА КОТОРЫЙ ОТВЕЧАЛИ:
{question[:600]}

ТЕРМИНЫ, КОТОРЫЕ МОГЛИ ПРОЗВУЧАТЬ:
{hints or 'не заданы'}

РАСШИФРОВКА:
{text[:6000]}

Правила:
1. НЕ добавляй, не убирай и не переформулируй мысли. Это расшифровка, а не пересказ.
2. Исправь только то, что распознано неверно на слух: "вентлуп" -> "event loop",
   "постгрес" -> "PostgreSQL", "докер компоуз" -> "docker compose".
3. Расставь знаки препинания и раздели на абзацы по смыслу.
4. Слова-паразиты и запинки ("э-э", "ну", "как бы", повторы) убери.
5. Разговорный стиль сохрани: человек говорил, а не писал.
6. Если расшифровка бессвязна, верни её почти как есть — не додумывай.

Верни ТОЛЬКО исправленный текст, без пояснений и кавычек."""

    try:
        cleaned = await llm_service._call_llm(
            [{"role": "user", "content": prompt}], temperature=0.1, fast=True
        )
    except Exception:
        return text
    cleaned = cleaned.strip().strip('"').strip()
    # Защита от галлюцинаций: длина не должна уезжать в разы.
    if not cleaned or not (0.4 * len(text) <= len(cleaned) <= 2.2 * len(text)):
        return text
    return cleaned
