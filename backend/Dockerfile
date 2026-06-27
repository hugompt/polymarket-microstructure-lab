# Backend image. Build context MUST be the repo root (compose handles this) so the
# package readme (../README.md) resolves.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PML_DATABASE_URL=postgresql+psycopg://lab:lab@db:5432/lab

WORKDIR /srv
COPY README.md ./README.md
COPY backend ./backend
WORKDIR /srv/backend

RUN pip install --upgrade pip && pip install -e .

EXPOSE 8000

# Run migrations, then serve. (The collector service overrides this command.)
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.api.app:app --host 0.0.0.0 --port 8000"]
