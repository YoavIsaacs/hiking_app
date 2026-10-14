# Progress

Master roadmap: "Hike Prep App — Roadmap" doc. Mirror: `docs/roadmap/overview.md` (checkpoints) and `phase-*.md` (checklists).
The tech lead keeps this file true. A step moves to Done only with checkpoint evidence.

| Step | Title | Status | PR | Checkpoint evidence | Verified on |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Repo and tooling | done (part deferred) | [#3](https://github.com/YoavIsaacs/hiking_app/pull/3) | Fresh clone → `just install` → `just dev-api` / `just dev-web` = 3 commands each, both HTTP 200 (QA, branch); `pre-commit run --all-files` 10/10 hooks pass on `main` @ 4018695 locally and in CI run [38387791812](https://github.com/YoavIsaacs/hiking_app/actions/runs/38387791812); `just test` passes. `lint` required on `main` since 2026-10-14 (ruleset `main`). **Deferred by manager:** secret scanning/push protection and the fake-API-key check. | 2026-10-13 |
| 0.2 | FastAPI skeleton | done | [#6](https://github.com/YoavIsaacs/hiking_app/pull/6) | On `main` @ 77726b0: `uv run pytest` 35 passed, coverage 100% (gate 85%, `--disable-socket`); `mypy app tests` strict → 0 errors (15 files); CodeQL run [38527140518](https://github.com/YoavIsaacs/hiking_app/actions/runs/38527140518) → 0 results, 0 open alerts; `/health` local latency n=300 after warm-up p50 1.20 ms / p95 1.64 ms / max 2.34 ms (< 50 ms). Docker (QA, branch): non-root uid 10001, `/health` returns build `GIT_SHA`/`VERSION`. Required checks on `main` (`gh api …/rules/branches/main`): `lint`, `api-test`, `Analyze (python)` (GitHub Actions). | 2026-10-14 |
| 0.3 | React app | in progress — design (ux-expert next) | | | |
| 0.4 | Generated API client | not started | | | |
| 0.5 | Deployment | not started | | | |
| 0.6 | Pipeline rules | not started | | | |

## Current state (handoff for a fresh session)
Read this, then `docs/steps/<current step>.md`. Nothing here lives only in chat.

- **Current step:** 0.3 React app on branch `step/0.3-react-app`. Brief: `docs/steps/0.3.md`. Stage: briefing.
  `.env` decision made (option A). Next: loop stage "Design" — delegate the Home page spec to `ux-expert`,
  then the frontend contract stub (tech-lead step 4a).
- **`main` protection:** branch ruleset `main` (active, no bypass): required checks `lint`, `api-test`,
  `Analyze (python)`; deletion and force-push blocked. PR-required, linear history etc. arrive in 0.6.
- **Open PRs:** none. Dependabot #4 (`@types/node` 26) and #5 (TypeScript 7) closed by manager decision;
  0.3 adds Dependabot ignore rules so they don't come back.
- **Local leftovers (manager may delete):** temp clones `%TEMP%\tmp.7qIrHpAUnP`, `%TEMP%\tmp.GMVXYXKa6R`;
  Docker images `hike-api:qa`, `hike-api:test`.

### Carry-forward (decided items waiting for their step)
- **0.3:** `.env` option A (decided; see brief). Dependabot ignore rules for `@types/node` majors
  above the Node runtime (24) and TypeScript majors. 0.1 placeholder nits to fold in: explicit `"strict": true`,
  `<title>`, remove leftover Vite template CSS and `web/public/icons.svg`, `toBeTruthy` placeholder test,
  ESLint `defineConfig`.
- **0.4:** operation IDs come only from the custom `generate_unique_id_function` (none hand-set).
- **0.5:** decide an env-var prefix for API settings (ADR) — `ENV`, `VERSION` are collision-prone. Dockerfile
  header comment should show `--build-arg VERSION`. Consider Dependabot `docker` ecosystem for `api/`.
  Secret scanning/push protection (deferred from 0.1) becomes relevant here — re-ask the manager.
- **0.6:** pin CI actions to SHAs; caching (`api-test` already has setup-uv cache); confirm Dependabot handles
  the pnpm 12 lockfile.
- **Before Phase 1 screens:** no visual identity or tokens exist yet (`design/tokens.json`, `docs/design/` absent).
  Phase 1 needs a graphic-designer pass before the first real screen.
- **Windows dev:** stopping `just dev-api` can orphan uvicorn (README troubleshooting). Port 8765 is held by an
  unrelated process on the manager's machine — avoid it.

### Settled technical decisions (so nobody re-litigates them)
- `api/`: no build-system; pytest `pythonpath = ["."]`; `--disable-socket --allow-hosts=127.0.0.1` (Windows
  TestClient loopback; outbound still blocked); `filterwarnings = ["error", <one targeted httpx/Starlette ignore>]`
  — stay on `httpx`; `httpx2` would need an ADR + manager approval.
- API settings: env names = field names upper-cased, no prefix (until 0.5 decides otherwise); `create_app(settings)`
  injection, settings on `app.state`; no module-level `app`.
- Errors: tracebacks in server logs only; responses get a generic 500 with `X-Request-ID`.
- `web/` lint is ESLint (type-aware), not oxlint. Pre-commit runs ruff, mypy, ESLint, Prettier, `tsc`.
- Line endings: `.gitattributes` `* text=auto eol=lf`. Commit attribution: each agent uses the trailer its own
  harness specifies.

### Process rules learned (apply from 0.3)
- **Tests-first vs type-checking hooks.** mypy/`tsc` hooks reject test files that import modules that don't
  exist yet, and `--no-verify` is not allowed. So: (1) the implementer first commits a **typed contract stub**
  (real signatures/exports; bodies `raise NotImplementedError` / `throw new Error("not implemented")`);
  (2) QA commits the failing tests against it (hooks type-check but don't run tests, so red tests commit
  cleanly) and shows they fail on assertions; (3) the implementer fills the stub in.
- **Stage by path.** No agent runs `git add -A`, `git stash`, or repo-wide formatters/fixers over files it
  doesn't own (happened in 0.1 and 0.2). Delegation prompts say this explicitly.
- **Check claims before reporting.** A report must not say something is done that the file doesn't show
  (0.2 devops `VERSION`). The tech lead verifies every report against the diff and reruns the gates.

## Team notes
- 0.1: 2 review rounds (frontend 1: template brought oxlint; devops 1: over-broad `.gitignore`). QA missed the
  `.gitignore` false positives. Devops ran `git stash` touching a file it doesn't own (restored).
- 0.2: 3 review rounds (backend 2: 500 path lost the request ID — reviewer; new duplicate-log filter untested —
  tech lead. devops 1: Dockerfile `VERSION` not exported though its report said it was — QA caught it).
  QA listed the 500 path as "untested" but didn't flag it as a checklist gap. Backend ran `ruff --fix` over
  QA's untracked tests (formatting only).
- **Repeated patterns → changes (manager-approved and applied 2026-10-14):**
  1. QA missed failure-path gaps twice (0.1, 0.2) → `.claude/agents/qa.md`: treat every untested failure path
     of a checklist item as a *finding*, not a follow-up; always probe negatives and false positives
     (errors, 4xx/5xx, ignore rules, invalid input).
  2. Agents touched others' files via broad commands twice (0.1 `git stash`, 0.2 `ruff --fix`) → CLAUDE.md
     Git section: "Stage by path; never run `git stash`, `git add -A`, or formatters/fixers over files you
     don't own."
  3. The tests-first stub sequence above → `.claude/agents/tech-lead.md` step loop, steps 4–5.
