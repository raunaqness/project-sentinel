FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY src ./src
COPY knowledge_base ./knowledge_base
RUN uv sync --frozen --no-dev

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000
# Access logging is done by the app (JSON, with request_id), so uvicorn's is off.
CMD ["uvicorn", "sentinel.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
