# syntax=docker/dockerfile:1
# Build:  docker build --build-arg GIT_SHA=$(git rev-parse HEAD) --build-arg VERSION=0.1.0 -t hike-api api
# The build args become the HIKE_GIT_SHA / HIKE_VERSION env vars the app reads (all settings use the HIKE_ prefix).
FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM debian:bookworm-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=manual \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/opt/python
WORKDIR /app
# The interpreter is the uv-managed CPython named by .python-version (the one CI uses), not the base image's.
COPY .python-version pyproject.toml uv.lock ./
RUN uv python install "$(cat .python-version)"
# Dependencies first so this layer is cached until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM debian:bookworm-slim AS runtime
ARG GIT_SHA=unknown
ARG VERSION=0.0.0-dev
ENV HIKE_GIT_SHA=${GIT_SHA} \
    HIKE_VERSION=${VERSION} \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
# The venv's python is a symlink into /opt/python, so it must be copied to the same path.
COPY --from=builder /opt/python /opt/python
COPY --from=builder /app/.venv /app/.venv
COPY .python-version ./
RUN echo 3.12.0 > .python-version  # DELIBERATE BREAK (revert follows)
COPY app ./app
# Drift guard: the build fails unless the interpreter is exactly the pinned, uv-managed one and the app's import
# guard accepts its expat (require_alloc_tracker raises on an expat without the allocation tracker).
RUN python -I -c "import sys, pyexpat; want = open('.python-version').read().strip(); got = '%d.%d.%d' % sys.version_info[:3]; print('python', got, 'expat', pyexpat.EXPAT_VERSION, sys.base_prefix); sys.exit(f'interpreter is {got}, .python-version pins {want}') if got != want else None; sys.exit('interpreter is not the uv-managed build under /opt/python') if not sys.base_prefix.startswith('/opt/python/') else None"  && python -c "import app.routes.parse, httpx"
USER 10001
EXPOSE 8080
# Shell form via `sh -c` so ${PORT} (set by Cloud Run) is expanded; `exec` keeps uvicorn as PID 1
# so it receives SIGTERM directly and shuts down gracefully.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
