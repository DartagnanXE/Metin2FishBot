# Minimal hardened image for the telemetry API.
# - python:3.12-slim base
# - runs as a NON-root user
# - only server/app + requirements copied
# - read-only-friendly: writes ONLY to the DB volume (/data)
# - EXPOSE the internal port (compose binds it to 127.0.0.1; never published)
# - HEALTHCHECK on /health
# No secrets are baked in (ADMIN_TOKEN/IP_HASH_SALT come from the env at runtime).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_PORT=8081 \
    DB_PATH=/data/telemetry.db

# Create a non-root user + the writable data dir up front.
RUN addgroup --system app && adduser --system --ingroup app --home /app app \
    && mkdir -p /data && chown -R app:app /data

WORKDIR /app

# Install deps first (layer cache). Only the server requirements.
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy only what the service needs (app package). The CLI is importable too.
COPY server/app /app/server/app
COPY server/cli.py /app/server/cli.py
COPY server/__init__.py /app/server/__init__.py

USER app

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os,sys; \
        url='http://127.0.0.1:'+os.environ.get('APP_PORT','8081')+'/health'; \
        sys.exit(0 if urllib.request.urlopen(url,timeout=3).status==200 else 1)" \
        || exit 1

# uvicorn serves the factory app. Workers=1 keeps the sqlite connection simple;
# scale via multiple containers behind nginx or switch to postgres (see DEPLOY).
CMD ["sh", "-c", "uvicorn server.app.main:app --host 0.0.0.0 --port ${APP_PORT} --workers 1"]
