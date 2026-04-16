# Playwright 공식 이미지 — Chromium + 시스템 의존성 포함
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SETTINGS_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 의존성 먼저 복사 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 소스
COPY . .

# settings.json 영속 볼륨
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

CMD ["python", "main.py"]
