# syntax=docker/dockerfile:1
# Build:  docker build --build-arg GIT_SHA=$(git rev-parse HEAD) -t hike-api api
FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so this layer is cached until uv.lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim AS runtime
ARG GIT_SHA=unknown
ARG VERSION=0.0.0-dev
ENV GIT_SHA=${GIT_SHA} \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
USER 10001
EXPOSE 8080
# Shell form via `sh -c` so ${PORT} (set by Cloud Run) is expanded; `exec` keeps uvicorn as PID 1
# so it receives SIGTERM directly and shuts down gracefully.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
