# Recipes must stay valid in both POSIX sh and cmd.exe (plain `cd X && cmd`; no quoting tricks, `>&2` or $VAR):
# on Windows cmd.exe always exists, whereas sh needs Git's usr\bin on PATH and bash can resolve to WSL.
set windows-shell := ["cmd.exe", "/c"]

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
    pnpm --filter web --fail-if-no-match dev

# Run every test suite; fails if any suite fails
test:
    cd api && uv run --frozen pytest
    pnpm --filter web --fail-if-no-match test

# Run the Playwright e2e suite (all projects; starts API and web servers)
e2e:
    pnpm --filter web --fail-if-no-match e2e

# Run all pre-commit hooks on all files
lint:
    pre-commit run --all-files --show-diff-on-failure

# Regenerate api/openapi.json and the web API client (web/src/api/schema.d.ts) from FastAPI
gen-api:
    pnpm --filter web --fail-if-no-match gen:api
