# 🎥 AI Video Interview Platform

Асинхронные технические видеоинтервью: vacancy → question pool → candidate interview → transcript/evidence → AI report → HR review → hiring-manager final decision.

## Быстрый старт

### Docker

```bash
cp .env.example .env
docker compose up --build
```

Откройте `http://localhost:8000`.

### Локально

```bash
pip install -r requirements.txt
python main.py
```

или эквивалентно:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

**`main.py` — единственная публичная точка запуска приложения.** Никаких `app:app`, master-key или специальных режимов знать не нужно.

Без LLM/Deepgram ключей приложение остаётся проходимым в mock-режиме.

## Вход в workspace

Для уже существующего пользователя всё просто:

1. открыть `/login`;
2. ввести обычные логин и пароль;
3. после успешного входа перейти в `/dashboard`.

Backend создаёт server-side session, а браузер получает только `HttpOnly + SameSite=Lax` cookie. Пароль и session token не сохраняются в localStorage.

Старые аккаунты из предыдущего MVP продолжают работать: plaintext-пароль при первом успешном входе автоматически мигрирует в `PBKDF2-HMAC-SHA256`, в том числе если старый пароль короче текущего требования в 8 символов.

### Первый запуск

Если таблица пользователей пустая, `/login` явно предложит создать первый HR-аккаунт. Это единственный случай свободной регистрации.

### Новый коллега

После создания первого HR новые пользователи добавляются только так:

1. HR входит в workspace;
2. нажимает **«Пригласить коллегу»**;
3. выбирает `HR` или `Нанимающий менеджер`;
4. отправляет полученную одноразовую ссылку;
5. приглашённый открывает её и создаёт свой аккаунт.

Роль уже закреплена в invitation link. Ссылка действует 48 часов и одноразовая.

## Прокторинг

Во время интервью кандидат заранее видит уведомление. После старта фиксируются браузерные integrity-signals:

- скрытие/возврат вкладки и длительность;
- потеря/возврат фокуса окна;
- copy / cut / paste без содержимого буфера обмена;
- вход/выход из fullscreen;
- offline / online;
- остановка camera/microphone tracks.

Дополнительно client-side MediaPipe Face Landmarker анализирует тот же webcam stream, который уже используется интервью. Второй доступ к камере не открывается. На backend отправляются только агрегированные события:

- лицо долго отсутствует;
- в кадре несколько лиц;
- длительный поворот головы;
- длительный взгляд в сторону.

Кадры и face landmarks на сервер не отправляются. Если MediaPipe не загрузился, интервью продолжает работать без ML-прокторинга.

**Прокторинг не входит в technical score** и показывается только как evidence для ручной проверки.

## Основной flow

### HR

- создаёт вакансию из raw text;
- получает suggested question pool и утверждает базовый набор;
- до старта персонализирует вопросы кандидата;
- создаёт candidate link;
- получает video/audio/transcript/evidence-based AI report;
- делает approve / reject / needs review;
- управляет HR lifecycle кандидата.

### Candidate

- открывает персональную ссылку;
- проверяет camera/mic;
- проходит техническое интервью;
- проверяет ASR transcript каждого ответа;
- система сохраняет full interview video и отдельное audio каждого ответа.

### Hiring manager

- видит кандидата только после явного HR approve;
- читает report, evidence, media и HR comment;
- принимает финальное approve/reject решение.

## Media

Browser `MediaRecorder` → backend → `ffmpeg/ffprobe` normalization. Full video хранится непрерывно, после интервью строятся per-answer clips по `start_ms/end_ms`.

## Stack

- FastAPI / Python 3.12
- SQLite for MVP
- Vanilla JS + HTML/CSS
- MediaRecorder
- MediaPipe Face Landmarker
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

Auth session/invite tokens генерируются случайно на runtime и не являются shared secrets.

## Проверки

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

GitHub Actions также проверяет синтаксис browser JS и обе поддерживаемые формы импорта приложения.

## Ограничения MVP

- SQLite/local media storage вместо PostgreSQL/S3;
- один workspace без полноценной organization model;
- нет email delivery invitation links;
- нет password reset / MFA / SSO;
- proctoring — evidence signal, а не автоматический anti-cheat verdict.
