# Hike Prep App

A mobile app that builds hike packing checklists from a GPX route and the weather forecast.
React PWA + FastAPI first, then React Native / Expo, same backend throughout. MIT licensed.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you)
- [Node.js](https://nodejs.org/) 24 and [pnpm](https://pnpm.io/) (version pinned in `package.json`; `corepack enable` works)
- [just](https://github.com/casey/just)
- [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit==4.7.0`)
- On Windows, run everything from Git Bash.

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

## Test and lint

```sh
just test         # api pytest + web vitest; fails if either fails
just lint         # pre-commit run --all-files (ruff, mypy, ESLint, Prettier, file hygiene)
just gen-api      # not implemented until step 0.4
```

## Deploy

Deployment arrives in step 0.5.

## Troubleshooting

- **Windows: port 8000 still busy after stopping `just dev-api`.** Killing `uv run uvicorn --factory --reload` can leave
  the child Python process listening. Find and kill it:
  `netstat -ano | grep :8000` then `taskkill //PID <pid> //F`.
- **`just` not found in Git Bash.** Reopen the shell after installing; on Windows `winget install Casey.Just`.
