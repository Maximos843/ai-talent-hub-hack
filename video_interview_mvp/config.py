"""
Конфигурация приложения
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

# Создаем директории если не существуют
UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)

# Database
DATABASE_URL = "sqlite:///./video_interview.db"

# LLM Configuration (OpenRouter или Qwen)
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct")

# ASR Configuration (DeepGram)
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

# TTS Configuration (Edge-TTS - бесплатный)
TTS_VOICE = "ru-RU-DmitryNeural"  # Русский мужской голос
TTS_RATE = "+0%"
TTS_VOLUME = "+0%"

# Interview settings
MAX_QUESTIONS_PER_INTERVIEW = 10
ANSWER_TIME_LIMIT_SECONDS = 120  # 2 минуты
REVIEW_TIME_LIMIT_SECONDS = 60   # 1 минута на проверку транскрипта

# Scoring
SCORE_MIN = 0
SCORE_MAX = 10

# Tags mapping for vacancy analysis
TAGS_KEYWORDS = {
    "python": ["python", "django", "flask", "fastapi", "pyramid"],
    "docker": ["docker", "контейнер", "container", "image", "образ"],
    "ci_cd": ["ci/cd", "ci cd", "continuous integration", "continuous delivery", "gitlab ci", "github actions", "jenkins"],
    "devops": ["devops", "kubernetes", "k8s", "terraform", "ansible", "helm"],
    "backend": ["backend", "бэкенд", "api", "rest", "graphql", "сервер"],
    "frontend": ["frontend", "фронтенд", "react", "vue", "angular", "javascript", "typescript"],
    "database": ["database", "база данных", "postgresql", "mysql", "mongodb", "redis", "sql", "nosql"],
    "microservices": ["microservices", "микросервисы", "service-oriented", "soa"],
    "cloud": ["cloud", "облако", "aws", "azure", "gcp", "yandex cloud"],
    "testing": ["testing", "тестирование", "unit tests", "integration tests", "pytest", "unittest"],
    "security": ["security", "безопасность", "oauth", "jwt", "encryption", "шифрование"],
    "monitoring": ["monitoring", "мониторинг", "prometheus", "grafana", "logging", "логирование"],
    "agile": ["agile", "scrum", "kanban", "спринт", "итерация"],
    "leadership": ["leadership", "лидерство", "team lead", "тимлид", "management", "управление"],
    "architecture": ["architecture", "архитектура", "design patterns", "паттерны проектирования"]
}

# Grade levels
GRADE_LEVELS = {
    "junior": ["junior", "джуниор", "начинающий", "стажер", "intern"],
    "middle": ["middle", "мидл", "средний", "опытный"],
    "senior": ["senior", "синьор", "старший", "ведущий", "lead"],
    "principal": ["principal", "принципал", "главный", "architect", "архитектор"]
}
