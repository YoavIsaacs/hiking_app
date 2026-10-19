# Hike Prep App

A mobile app that builds hike packing checklists from a GPX route and the weather forecast.
React PWA + FastAPI first, then React Native / Expo, same backend throughout. MIT licensed.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- [Node.js](https://nodejs.org/) 24 and [pnpm](https://pnpm.io/) (version pinned in `package.json`; `corepack enable` works)
- [just](https://github.com/casey/just)
- [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit==4.7.0`)

## Setup

```sh
git clone https://github.com/YoavIsaacs/hiking_app.git && cd hiking_app
just install      # api deps, web deps, and the pre-commit git hook
```

## Run

From a fresh clone, each app is two commands (`just install` is shared):

```sh
just dev-api      # http://127.0.0.1:8000  (GET /health returns 200)
just dev-web      # http://localhost:5173
```

The API reads its settings from `HIKE_`-prefixed environment variables (`HIKE_ENV`, `HIKE_VERSION`, `HIKE_GIT_SHA`,
`HIKE_CORS_ORIGINS`, `HIKE_CORS_FIREBASE_SITE`, `HIKE_OPEN_METEO_BASE_URL`, `HIKE_LOG_LEVEL`); unprefixed names are ignored.
Local dev needs none of them.

## Test and lint

```sh
just test         # api pytest + web vitest; fails if either fails
just lint         # pre-commit run --all-files (ruff, mypy, ESLint, Prettier, file hygiene)
just gen-api      # regenerate api/openapi.json + web/src/api/schema.d.ts; needs uv (API toolchain) even for frontend-only work
```

## Deploy

- Web: https://hike-prep.web.app (Firebase Hosting).
- API: https://hike-api-zr6tmbe2ya-zf.a.run.app (Cloud Run, me-west1).
- Deploys run from `main` via `.github/workflows/deploy-api.yml` and `deploy-web.yml`.
- Each PR gets a Firebase Hosting preview channel, with its URL commented on the PR.
- One-time setup: `docs/runbooks/0.5-gcp-firebase-setup.md`. Decisions: `docs/adr/0002-deployment.md`.

## Troubleshooting

- **Windows: port 8000 still busy after stopping `just dev-api`.** Killing `uv run uvicorn --factory --reload` can leave
  the child Python process listening. Find and kill it:
  `netstat -ano | findstr :8000` then `taskkill /PID <pid> /F` (works in cmd.exe and PowerShell).
- **`just` not found.** Reopen the terminal after installing; on Windows `winget install Casey.Just`.
- **Windows: recipe fails with a shell or `uv`/`pnpm` not found error.** On Windows `just` runs recipes with `cmd.exe`
  (no Git or WSL needed), so make sure `uv`, `pnpm` and `pre-commit` are on your Windows PATH.
