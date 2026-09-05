# 🎥 AI Video Interview Platform

Асинхронные технические видеоинтервью: vacancy → questions → candidate interview → transcript/evidence → AI report → HR review → hiring-manager final decision.

## Быстрый старт

### Docker
```bash
cp .env.example .env
docker compose up --build
```

### Локально
```bash
pip install -r requirements.txt
python main.py
```

или:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Откройте `http://localhost:8000`.

**`main.py` — единственная публичная точка запуска.** Никаких `app:app`, master-key или специальных режимов знать не нужно.

Без LLM/Deepgram ключей приложение остаётся проходимым в mock-режиме.

## Авторизация

Для существующего пользователя всё просто:

1. открыть `/login`;
2. ввести обычные логин и пароль;
3. после входа открыть `/dashboard`.

Сессия хранится на сервере, браузер получает только HttpOnly cookie. Старые plaintext-пароли автоматически мигрируют в PBKDF2 после успешного входа, включая старые короткие пароли.

Если база пустая, `/login` предложит создать первый HR-аккаунт. После этого новые сотрудники добавляются только через **«Пригласить коллегу»** в HR workspace. Invite одноразовый, действует 48 часов, роль уже закреплена в ссылке.

## Прокторинг

Во время интервью фиксируются браузерные сигналы: уход со вкладки, потеря фокуса, copy/cut/paste без содержимого clipboard, fullscreen, offline/online и остановка camera/microphone tracks.

MediaPipe Face Landmarker локально анализирует тот же webcam stream, который уже используется интервью, без второго `getUserMedia`. На backend отправляются только события: отсутствие лица, несколько лиц, длительный поворот головы и длительный взгляд в сторону. Кадры и landmarks не отправляются.

Если MediaPipe недоступен, интервью продолжает работать. Прокторинг не влияет на technical score и показывается только как evidence для ручной проверки.

## Media

Browser `MediaRecorder` → backend → `ffmpeg/ffprobe` normalization. Full video хранится непрерывно, после интервью строятся per-answer clips по `start_ms/end_ms`.

## Stack

- FastAPI / Python 3.12
- SQLite for MVP
- Vanilla JS + HTML/CSS
- MediaRecorder + MediaPipe Face Landmarker
- ffmpeg / ffprobe
- Deepgram API or mock ASR
- Qwen/OpenRouter-compatible LLM API or mock evaluator
- browser SpeechSynthesis

## Проверки

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

GitHub Actions дополнительно проверяет browser JS и canonical `main:app` entrypoint.
