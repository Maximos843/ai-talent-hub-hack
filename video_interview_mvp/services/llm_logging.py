"""Safe observability for LLM calls.

Never logs API keys, prompts, transcripts, model responses or candidate PII.
"""
from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger("talent_interview.llm")


def install_llm_logging(service) -> None:
    if getattr(service, "_observability_installed", False):
        return
    service._observability_installed = True

    original_call = service._call_llm

    @wraps(original_call)
    async def logged_call(messages, temperature=0.1):
        mode = "LIVE" if service.api_key else "MOCK"
        started = time.perf_counter()
        logger.info(
            "LLM request start mode=%s model=%s base=%s messages=%d temperature=%.2f",
            mode,
            service.model,
            service.base_url,
            len(messages or []),
            float(temperature),
        )
        try:
            result = await original_call(messages, temperature=temperature)
        except Exception as exc:
            logger.exception(
                "LLM request failed mode=%s model=%s elapsed_ms=%d error_type=%s",
                mode,
                service.model,
                int((time.perf_counter() - started) * 1000),
                type(exc).__name__,
            )
            raise
        logger.info(
            "LLM request ok mode=%s model=%s elapsed_ms=%d",
            mode,
            service.model,
            int((time.perf_counter() - started) * 1000),
        )
        return result

    service._call_llm = logged_call

    original_probe = service.decide_follow_up

    @wraps(original_probe)
    async def logged_probe(*args, **kwargs):
        result = await original_probe(*args, **kwargs)
        logger.info(
            "LLM adaptive decision root_question_id=%s ask=%s confidence=%.2f source=%s follow_up_count=%s",
            kwargs.get("root_question_id", ""),
            bool(result.get("ask_follow_up")),
            float(result.get("confidence_0_1", 0.0) or 0.0),
            result.get("source", "none"),
            kwargs.get("follow_up_count", ""),
        )
        return result

    service.decide_follow_up = logged_probe

    logger.info(
        "LLM service initialized mode=%s model=%s base=%s",
        "LIVE" if service.api_key else "MOCK",
        service.model,
        service.base_url,
    )
