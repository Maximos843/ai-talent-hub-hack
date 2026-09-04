"""
Инициализация пакета сервисов
"""
from .llm_service import llm_service, LLMService
from .tts_service import tts_service, TTSService
from .asr_service import asr_service, ASRService

__all__ = [
    'llm_service', 'LLMService',
    'tts_service', 'TTSService', 
    'asr_service', 'ASRService'
]
