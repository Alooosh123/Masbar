FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

COPY backend ./backend
COPY data ./data
COPY scripts/railway-entrypoint.sh /usr/local/bin/railway-entrypoint.sh

# The app normally runs as UID 10001. Railway mounts volumes as root; when
# RAILWAY_RUN_UID=0 is set, the entrypoint fixes the mounted session directory
# and immediately drops privileges before starting FastAPI.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /nonexistent --shell /usr/sbin/nologin app \
    && mkdir -p /app/data/sessions /app/data/cache/tts \
    && chown -R app:app /app/data \
    && chmod 0755 /usr/local/bin/railway-entrypoint.sh

WORKDIR /app/backend

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health')"

ENTRYPOINT ["/usr/local/bin/railway-entrypoint.sh"]
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
