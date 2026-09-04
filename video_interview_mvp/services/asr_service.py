"""
Сервисы для ASR (Automatic Speech Recognition) с использованием DeepGram API
"""
import httpx
from typing import Optional, Dict, Any
from config import DEEPGRAM_API_KEY


class ASRService:
    """Сервис для распознавания речи с использованием DeepGram API"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or DEEPGRAM_API_KEY
        self.base_url = "https://api.deepgram.com/v1/listen"
    
    async def transcribe_audio(self, audio_data: bytes, language: str = "ru") -> Dict[str, Any]:
        """
        Транскрибация аудиофайла
        
        Args:
            audio_data: Байты аудиофайла
            language: Язык распознавания (по умолчанию русский)
        
        Returns:
            Словарь с результатами транскрибации
        """
        if not self.api_key:
            # Для тестирования без ключа возвращаем заглушку
            return self._get_mock_transcription()
        
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/*"  # DeepGram автоматически определяет формат
        }
        
        params = {
            "model": "nova-2",  # Высокоточная модель
            "language": language,
            "punctuate": "true",
            "smart_format": "true",
            "utterances": "false"
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.base_url,
                    headers=headers,
                    params=params,
                    content=audio_data
                )
                response.raise_for_status()
                data = response.json()
                
                # Извлекаем транскрипт
                transcript = ""
                if "results" in data and "channels" in data["results"]:
                    channels = data["results"]["channels"]
                    if channels and "alternatives" in channels[0]:
                        transcript = channels[0]["alternatives"][0].get("transcript", "")
                
                return {
                    "success": True,
                    "transcript": transcript,
                    "confidence": data.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("confidence", 0),
                    "raw_data": data
                }
        except Exception as e:
            return {
                "success": False,
                "transcript": "",
                "error": str(e)
            }
    
    async def transcribe_audio_file(self, file_path: str, language: str = "ru") -> Dict[str, Any]:
        """
        Транскрибация аудиофайла из пути
        
        Args:
            file_path: Путь к аудиофайлу
            language: Язык распознавания
        
        Returns:
            Словарь с результатами транскрибации
        """
        try:
            with open(file_path, 'rb') as f:
                audio_data = f.read()
            return await self.transcribe_audio(audio_data, language)
        except Exception as e:
            return {
                "success": False,
                "transcript": "",
                "error": str(e)
            }
    
    def _get_mock_transcription(self) -> Dict[str, Any]:
        """Заглушка для тестирования без API ключа"""
        return {
            "success": True,
            "transcript": "Это пример транскрибации ответа кандидата. В реальном режиме здесь будет распознанный текст ответа на вопрос интервью.",
            "confidence": 0.95,
            "raw_data": {}
        }


asr_service = ASRService()
