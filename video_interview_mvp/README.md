# 🎥 AI Video Interview Platform

Асинхронные технические видеоинтервью: vacancy → question pool → candidate interview → transcript/evidence → AI report → HR review → hiring-manager final decision.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

Откройте `http://localhost:8000`.

Без LLM/Deepgram ключей приложение остаётся проходимым в mock-режиме.

Для локального запуска без Docker:

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

> Запускайте именно `app:app`: это gateway с новой авторизацией и прокторингом. `main.py` остаётся business-layer приложения и монтируется внутрь gateway.

## Авторизация в MVP

Общих `HR_INVITE_TOKEN` / `MANAGER_INVITE_TOKEN` больше нет.

1. На пустой базе первый зарегистрированный пользователь становится HR-владельцем workspace.
2. После этого свободная регистрация закрывается.
3. HR в workspace нажимает **«Пригласить коллегу»** и выбирает роль.
4. Backend создаёт случайную одноразовую ссылку, действующую 48 часов.
5. Роль зафиксирована в invitation record и не выбирается приглашённым пользователем.

После login backend создаёт случайный opaque session token. В SQLite хранится только его SHA-256 hash, а браузер получает token через `HttpOnly + SameSite=Lax` cookie. Пароль не попадает в `localStorage` или JavaScript.

Пароли хранятся как `PBKDF2-HMAC-SHA256` с индивидуальной солью. Старые plaintext-пароли из предыдущей версии MVP автоматически мигрируют в hash после первого успешного login.

Logout отзывает server-side session. Session TTL сейчас 8 часов.

## Browser proctoring

Во время интервью кандидат заранее видит уведомление о базовом прокторинге. После старта браузер фиксирует только технические integrity-signals:

- скрытие/возврат вкладки и длительность;
- потерю/возврат фокуса окна;
- copy / cut / paste **без содержимого буфера обмена**;
- вход/выход из fullscreen;
- offline / online;
- остановку camera/microphone tracks.

События батчатся в `/api/interviews/{session_token}/proctor-events`. HR и hiring manager видят агрегаты в отчёте.

**Важно:** сигналы прокторинга не входят в technical score, не являются доказательством нарушения и предназначены только для human review.

## Основной flow

### HR

- создаёт вакансию из raw text;
- получает suggested question pool и утверждает базовый набор;
- для конкретного кандидата может менять/выключать вопросы и добавлять свои до старта интервью;
- создаёт candidate link;
- получает video/audio/transcript/evidence-based AI report;
- делает первый approve / reject / needs review;
- управляет HR lifecycle (`active / hold / rejected / hired`).

### Candidate

- открывает персональную ссылку;
- проверяет camera/mic;
- видит предупреждение о прокторинге;
- отвечает на вопросы в chat-style UI;
- после ответа проверяет ASR transcript;
- система пишет непрерывное full interview video и отдельный audio каждого ответа.

### Hiring manager

- видит только кандидатов после явного HR approve;
- читает AI report, evidence, media и HR comment;
- принимает финальное approve/reject решение.

## Media

Browser `MediaRecorder` → backend → `ffmpeg/ffprobe` normalization. Full video хранится непрерывно, а после интервью backend строит per-answer clips по `start_ms/end_ms`. Report API возвращает duration/size/playable metadata, поэтому битый `0:00` файл не скрывается от пользователя.

## Stack

- FastAPI / Python 3.12
- SQLite for MVP
- Vanilla JS + HTML/CSS
- MediaRecorder
- ffmpeg / ffprobe
- Deepgram API or mock ASR
- Qwen/OpenRouter-compatible LLM API or mock evaluator
- browser SpeechSynthesis

## Environment

```env
LLM_API_KEY=
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=qwen/qwen-2.5-72b-instruct
DEEPGRAM_API_KEY=
```

Auth session/invite tokens are generated randomly at runtime and are not shared environment secrets.

## Smoke tests

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

GitHub Actions запускает эти проверки для изменений `video_interview_mvp/**`.

## Ограничения MVP

- SQLite/local media storage вместо PostgreSQL/S3;
- один workspace без полноценной organization model;
- нет email delivery invitation links;
- нет password reset / MFA / SSO;
- browser proctoring — только evidence signal, не автоматический anti-cheat classifier;
- нейросетевой gaze/audio proctoring намеренно вынесен в следующий этап после отдельной проверки технологий.
