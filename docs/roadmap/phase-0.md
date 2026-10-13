# Phase 0 — Setup checklist

## 0.1 Repo and tooling

- [ ] Create the GitHub repo (private to start) and decide on a license
- [ ] Top-level layout: `api/`, `web/`, `.github/workflows/`, `docs/`
- [ ] `.gitignore` covering Python, Node, `.env*`, IDE folders, Playwright output
- [ ] `.editorconfig` (indent, line endings, final newline)
- [ ] `api/`: `uv init`, pin Python 3.12 in `pyproject.toml` and `.python-version`
- [ ] API runtime deps: fastapi, uvicorn\[standard\], pydantic, pydantic-settings
- [ ] API dev deps: pytest, pytest-cov, httpx, respx, pytest-socket, ruff, mypy
- [ ] `web/`: `pnpm create vite web --template react-ts`; `pnpm-workspace.yaml` at the root
- [ ] `.pre-commit-config.yaml` hooks: ruff lint, ruff format, mypy, ESLint, Prettier, end-of-file fixer, trailing whitespace, check-yaml, detect-private-key
- [ ] `justfile` (or Makefile) targets: `install`, `dev-api`, `dev-web`, `test`, `lint`, `gen-api`
- [ ] README: prerequisites, setup, run, test, deploy
- [ ] `.github/pull_request_template.md` with checklist (tests added, CI green, docs updated)
- [ ] `.github/dependabot.yml`: Python (uv), npm, GitHub Actions; weekly; grouped minor/patch updates
- [ ] Repo settings: secret scanning and push protection on
- [ ] `.github/workflows/ci.yml` with the `lint` job running `pre-commit run --all-files`
- [ ] Verify: fresh clone into a temp folder, run both apps in ≤ 3 commands each
- [ ] Verify: committing a fake API key is blocked

## 0.2 FastAPI skeleton

- [ ] `api/app/main.py` with a `create_app()` factory
- [ ] `api/app/config.py` — `Settings` (pydantic-settings): `env`, `cors_origins`, `version`, `git_sha`, `open_meteo_base_url`, `log_level`
- [ ] `api/app/routers/health.py` — `GET /health`
- [ ] `HealthResponse` model: `status`, `version`, `git_sha`, `env`
- [ ] CORS middleware fed from `settings.cors_origins`
- [ ] Request-ID middleware; JSON logging with the request ID on every line
- [ ] mypy strict config in `pyproject.toml`; Pydantic mypy plugin enabled
- [ ] pytest config: `testpaths`, `--cov=app --cov-fail-under=85`, `--disable-socket`
- [ ] `tests/conftest.py` — `settings` override fixture and `client` fixture
- [ ] Test: `test_health_returns_200`
- [ ] Test: `test_health_has_version_and_sha`
- [ ] Test: `test_settings_env_override`
- [ ] Test: `test_cors_allowed_origin_gets_headers`
- [ ] Test: `test_cors_unknown_origin_gets_none`
- [ ] `api/Dockerfile`: multi-stage with uv, non-root user, `uvicorn app.main:create_app --factory`; `GIT_SHA` build arg
- [ ] `api/.dockerignore`
- [ ] CI: `api-test` job — setup-uv, `uv sync --frozen`, ruff, mypy, pytest
- [ ] CI: `.github/workflows/codeql.yml` for Python
- [ ] Verify: `/health` < 50 ms locally (`hey` or a quick httpx loop)

## 0.3 React app

- [ ] `tsconfig.json`: `strict`, `noUncheckedIndexedAccess`, `noUnusedLocals`
- [ ] Deps: react-router, @tanstack/react-query
- [ ] Dev deps: vitest, @testing-library/react, @testing-library/user-event, jsdom, msw, @playwright/test, eslint (typescript-eslint, react-hooks plugin), prettier, size-limit
- [ ] `src/main.tsx` — `QueryClientProvider` and router
- [ ] Route `/` — Home page showing API status and version
- [ ] `src/api/client.ts` — base URL from `VITE_API_URL`
- [ ] `.env.development` and `.env.production`
- [ ] App-level error boundary and a reusable error state component
- [ ] `vitest.config.ts` and `src/test/setup.ts` starting an MSW server
- [ ] Test: renders version from mocked `/health`
- [ ] Test: shows error state when `/health` returns 500
- [ ] Test: shows loading state
- [ ] `playwright.config.ts` — `webServer` starts API and web; projects: desktop Chromium, Pixel 7, iPhone 14 (WebKit)
- [ ] `e2e/smoke.spec.ts` — page loads and shows the API version
- [ ] `.size-limit.json` — 200 KB gzipped budget
- [ ] CI: `web-test` job — pnpm install (cached), ESLint, `tsc --noEmit`, Vitest with coverage, build, size-limit
- [ ] CI: `e2e` job — Playwright browsers cached, runs all three projects, uploads the HTML report as an artifact on failure
- [ ] CI: add JavaScript/TypeScript to CodeQL

## 0.4 Generated API client

- [ ] `api/app/export_openapi.py` — writes `openapi.json` without starting a server
- [ ] Custom `generate_unique_id_function` so operation IDs are clean (`parseRoute`, `createChecklist`)
- [ ] Web deps: openapi-typescript and openapi-fetch
- [ ] `pnpm gen:api` script: export schema → generate `web/src/api/schema.d.ts`
- [ ] Commit the generated file; mark it generated in `.gitattributes`
- [ ] `web/src/api/client.ts` uses openapi-fetch typed by `schema.d.ts`
- [ ] ESLint `no-restricted-syntax` rule: no raw `fetch` to the API outside `src/api/`
- [ ] `web/src/api/__typecheck__.ts` — calls every endpoint so `tsc` breaks on contract drift
- [ ] CI: `api-contract` job — export, generate, `git diff --exit-code`
- [ ] Verify: change a response field in FastAPI without regenerating → job fails

## 0.5 Deployment

- [ ] GCP project; enable Cloud Run, Artifact Registry, Secret Manager, IAM Credentials APIs
- [ ] Artifact Registry Docker repository in a region near you (e.g. `me-west1`)
- [ ] Deploy service account: `run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser` only
- [ ] Runtime service account for the Cloud Run service (Secret Manager access only)
- [ ] Workload Identity pool and provider, restricted to this repo and `main`
- [ ] Cloud Run service: min instances 0, max 3, 512 MiB, concurrency 80, env vars set
- [ ] Firebase project linked to the GCP project; `firebase.json` with SPA rewrite and cache headers (hashed assets immutable, `index.html` no-cache)
- [ ] GitHub Environment `production` with its secrets and variables
- [ ] `.github/workflows/deploy-api.yml` (on push to `main`, `api/**`): auth via WIF → build with `GIT_SHA` → push tagged with the SHA → deploy with `--no-traffic --tag candidate`
- [ ] Smoke test the candidate URL: `/health` returns the expected `git_sha`
- [ ] On success: shift 100% traffic to the new revision; on failure: leave traffic on the old one and fail the job
- [ ] `.github/workflows/deploy-web.yml`: build with production `VITE_API_URL`, deploy to Firebase Hosting
- [ ] Post-deploy: Playwright smoke against the live URL
- [ ] `.github/workflows/preview.yml`: Firebase preview channel per PR, URL commented on the PR
- [ ] Verify on phone over mobile data: < 5 s cold, < 1 s warm
- [ ] Verify: push a deliberately broken build → production keeps serving the old revision

## 0.6 Pipeline rules

- [ ] Ruleset on `main`: PRs required, no force pushes, linear history, applies to admins too
- [ ] Required checks: `lint`, `api-test`, `web-test`, `e2e`, `api-contract`, CodeQL
- [ ] dorny/paths-filter job so each job runs only when its area changed (but required jobs still report success when skipped)
- [ ] Caching: setup-uv cache, pnpm store cache, Playwright browsers cache
- [ ] `concurrency: { group: ${{ github.ref }}, cancel-in-progress: true }` on PR workflows
- [ ] PR title check for Conventional Commits (amannn/action-semantic-pull-request), since release-please depends on it
- [ ] `release-please-config.json` and workflow
- [ ] `.github/workflows/nightly.yml`: cron, full suite, opens a GitHub issue on failure
- [ ] Verify: a PR with a failing test can't be merged
- [ ] Verify: PR pipeline < 5 min; merge to live < 10 min
