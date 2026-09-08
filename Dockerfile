FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/aftermind.db \
    AFTERMIND_LOG_FORMAT=json \
    AFTERMIND_HOST=0.0.0.0 \
    AFTERMIND_PORT=8000

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY domain ./domain
COPY core ./core
COPY providers ./providers
COPY apps ./apps
COPY integrations ./integrations
COPY sdk ./sdk

RUN pip install --no-cache-dir ".[graph,mcp]"

# SQLite (canonical store) lives on a volume; everything else is derived.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# `aftermind worker` runs the sync worker as its own container instead.
CMD ["aftermind", "serve"]
