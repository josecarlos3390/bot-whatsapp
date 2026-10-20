# syntax=docker/dockerfile:1

FROM node:22-slim AS web
WORKDIR /web
COPY admin-web/package.json admin-web/pnpm-lock.yaml ./
RUN npm install --no-audit --no-fund
COPY admin-web/ ./
RUN npm run build:console

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY knowledge ./knowledge
COPY --from=web /web/dist ./admin-web/dist
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
