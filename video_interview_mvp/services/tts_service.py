"""Озвучка вопросов через OpenAI-совместимый /audio/speech.

Браузерный speechSynthesis звучит роботом, а интервью — это разговор: голос
должен быть живым, иначе кандидат воспринимает происходящее как анкету.
Синтез занимает около секунды на вопрос, и результат кэшируется на диск: один
и тот же вопрос озвучивается однажды на всю вакансию.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import httpx

from config import TTS_API_KEY, TTS_BASE_URL, TTS_INSTRUCTIONS, TTS_VOICE, UPLOAD_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = Path(UPLOAD_DIR) / "tts"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class TTSUnavailable(RuntimeError):
    """Синтез недоступен — интерфейс откатится на браузерный голос."""


def _digest(text: str) -> str:
    # Голос и стиль входят в ключ: иначе после их смены отдавалась бы старая озвучка.
    key = f"{TTS_VOICE}:{TTS_INSTRUCTIONS}:{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _cached(text: str) -> Optional[Path]:
    """Формат зависит от модели и голоса, поэтому ищем оба расширения."""
    for suffix in (".mp3", ".wav"):
        path = CACHE_DIR / f"{_digest(text)}{suffix}"
        if path.is_file() and path.stat().st_size > 1000:
            return path
    return None


def media_type_for(path: Path) -> str:
    return "audio/wav" if path.suffix == ".wav" else "audio/mpeg"


async def synthesize(text: str) -> Path:
    """Возвращает путь к аудиофайлу с озвучкой. Повторный вызов берёт его из кэша."""
    clean = " ".join((text or "").split())
    if not clean:
        raise TTSUnavailable("Пустой текст")
    if not TTS_API_KEY:
        raise TTSUnavailable("Не задан TTS_API_KEY")

    cached = _cached(clean)
    if cached:
        return cached

    # Кап провайдера — 5000 символов на вызов, лимит считается по их числу.
    payload = {"input": clean[:5000], "voice": TTS_VOICE}
    if TTS_INSTRUCTIONS:
        payload["instructions"] = TTS_INSTRUCTIONS

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{TTS_BASE_URL.rstrip('/')}/audio/speech",
                headers={"Authorization": f"Bearer {TTS_API_KEY}"},
                # Поле model намеренно не передаётся: с ним провайдер переключается
                # на другой движок и голос звучит иначе, чем при запросе с одним voice.
                json=payload,
            )
            response.raise_for_status()
            audio = response.content
    except Exception as exc:
        logger.warning("Синтез речи не удался: %s", exc)
        raise TTSUnavailable(str(exc)) from exc

    if len(audio) < 1000:
        raise TTSUnavailable("Слишком короткий аудиоответ")

    # response_format здесь не гарантирован: с параметром voice сервер отдаёт wav,
    # поэтому формат определяем по содержимому, а не по тому, что просили.
    suffix = ".wav" if audio[:4] == b"RIFF" else ".mp3"
    path = CACHE_DIR / f"{_digest(clean)}{suffix}"
    path.write_bytes(audio)
    return path
