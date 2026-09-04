"""
Сервисы для TTS (Text-to-Speech) с использованием Edge-TTS
"""
import asyncio
import edge_tts
from pathlib import Path
from typing import Optional
from config import TTS_VOICE, TTS_RATE, TTS_VOLUME, UPLOAD_DIR


class TTSService:
    """Сервис для синтеза речи с использованием Edge-TTS"""
    
    def __init__(self, voice: str = None, rate: str = None, volume: str = None):
        self.voice = voice or TTS_VOICE
        self.rate = rate or TTS_RATE
        self.volume = volume or TTS_VOLUME
    
    async def generate_speech(self, text: str, output_path: str) -> bool:
        """
        Генерация аудио из текста
        
        Args:
            text: Текст для озвучивания
            output_path: Путь для сохранения аудиофайла
        
        Returns:
            True если успешно, False иначе
        """
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume
            )
            
            await communicate.save(output_path)
            return True
        except Exception as e:
            print(f"Ошибка TTS: {e}")
            return False
    
    async def generate_speech_bytes(self, text: str) -> Optional[bytes]:
        """
        Генерация аудио из текста в байты
        
        Args:
            text: Текст для озвучивания
        
        Returns:
            Байты аудиофайла или None при ошибке
        """
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                volume=self.volume
            )
            
            audio_data = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            return audio_data
        except Exception as e:
            print(f"Ошибка TTS: {e}")
            return None


tts_service = TTSService()
