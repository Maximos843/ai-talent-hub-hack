"""Озвучка вопросов через Cartesia Sonic.

Браузерный speechSynthesis звучит роботом, а интервью — это разговор: голос
должен быть живым, иначе кандидат воспринимает происходящее как анкету.
Cartesia отдаёт русский голос за ~1.8 секунды на вопрос, и результат кэшируется
на диск: один и тот же вопрос синтезируется однажды на всю вакансию.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import httpx

from config import CARTESIA_API_KEY, CARTESIA_MODEL, CARTESIA_VOICE_ID, UPLOAD_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = Path(UPLOAD_DIR) / "tts"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
API_URL = "https://api.cartesia.ai/tts/bytes"
API_VERSION = "2024-11-13"


class TTSUnavailable(RuntimeError):
    """Синтез недоступен — интерфейс откатится на браузерный голос."""


def _cache_path(text: str, voice_id: str) -> Path:
    digest = hashlib.sha256(f"{voice_id}:{CARTESIA_MODEL}:{text}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{digest}.mp3"


async def synthesize(text: str, voice_id: Optional[str] = None) -> Path:
    """Возвращает путь к mp3 с озвучкой. Повторный вызов берёт файл из кэша."""
    clean = " ".join((text or "").split())
    if not clean:
        raise TTSUnavailable("Пустой текст")
    if not CARTESIA_API_KEY:
        raise TTSUnavailable("Не задан CARTESIA_API_KEY")

    voice = voice_id or CARTESIA_VOICE_ID
    cached = _cache_path(clean, voice)
    if cached.is_file() and cached.stat().st_size > 1000:
        return cached

    payload = {
        "model_id": CARTESIA_MODEL,
        "transcript": clean[:2000],
        "voice": {"mode": "id", "id": voice},
        "language": "ru",
        "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                API_URL,
                headers={
                    "X-API-Key": CARTESIA_API_KEY,
                    "Cartesia-Version": API_VERSION,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            audio = response.content
    except Exception as exc:
        logger.warning("Cartesia не ответила: %s", exc)
        raise TTSUnavailable(str(exc)) from exc

    if len(audio) < 1000:
        raise TTSUnavailable("Слишком короткий аудиоответ")
    cached.write_bytes(audio)
    return cached
