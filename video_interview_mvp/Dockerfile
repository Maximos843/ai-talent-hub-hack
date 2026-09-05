FROM python:3.12-slim

WORKDIR /app

# ffmpeg/ffprobe are used for durable interview media; curl is used by the
# docker-compose healthcheck.
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/static /app/data

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# app.py wraps the existing business application with HttpOnly sessions,
# one-time invitations and browser proctoring telemetry.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
