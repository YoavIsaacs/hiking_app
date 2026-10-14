# Works in Git Bash on Windows and on Linux/macOS.
set windows-shell := ["bash", "-uc"]

default:
    @just --list

# Install all dependencies and the pre-commit git hook
install:
    cd api && uv sync --frozen
    pnpm install --frozen-lockfile
    pre-commit install

# Run the API with auto-reload on http://127.0.0.1:8000
dev-api:
    cd api && uv run --frozen uvicorn app.main:create_app --factory --reload

# Run the web app on http://localhost:5173
dev-web:
    pnpm --filter web dev

# Run every test suite; fails if any suite fails
test:
    cd api && uv run --frozen pytest
    pnpm --filter web test

# Run the Playwright e2e suite (all projects; starts API and web servers)
e2e:
    pnpm --filter web e2e

# Run all pre-commit hooks on all files
lint:
    pre-commit run --all-files --show-diff-on-failure

# Regenerate the web API client from OpenAPI (not implemented until step 0.4)
gen-api:
    @echo "gen-api is not implemented until step 0.4" >&2
    @exit 1
