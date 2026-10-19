# Progress

Master roadmap: "Hike Prep App — Roadmap" doc. Mirror: `docs/roadmap/overview.md` (checkpoints) and `phase-*.md` (checklists).
The tech lead keeps this file true. A step moves to Done only with checkpoint evidence.

| Step | Title | Status | PR | Checkpoint evidence | Verified on |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Repo and tooling | done (part deferred) | [#3](https://github.com/YoavIsaacs/hiking_app/pull/3) | Fresh clone → `just install` → `just dev-api` / `just dev-web` = 3 commands each, both HTTP 200 (QA, branch); `pre-commit run --all-files` 10/10 hooks pass on `main` @ 4018695 locally and in CI run [38387791812](https://github.com/YoavIsaacs/hiking_app/actions/runs/38387791812); `just test` passes. `lint` required on `main` since 2026-10-14 (ruleset `main`). **Deferred by manager:** secret scanning/push protection and the fake-API-key check. | 2026-10-13 |
| 0.2 | FastAPI skeleton | done | [#6](https://github.com/YoavIsaacs/hiking_app/pull/6) | On `main` @ 77726b0: `uv run pytest` 35 passed, coverage 100% (gate 85%, `--disable-socket`); `mypy app tests` strict → 0 errors (15 files); CodeQL run [38527140518](https://github.com/YoavIsaacs/hiking_app/actions/runs/38527140518) → 0 results, 0 open alerts; `/health` local latency n=300 after warm-up p50 1.20 ms / p95 1.64 ms / max 2.34 ms (< 50 ms). Docker (QA, branch): non-root uid 10001, `/health` returns build `GIT_SHA`/`VERSION`. Required checks on `main` (`gh api …/rules/branches/main`): `lint`, `api-test`, `Analyze (python)` (GitHub Actions). | 2026-10-14 |
| 0.3 | React app | done | [#7](https://github.com/YoavIsaacs/hiking_app/pull/7) | On `main` @ c4202b1: `tsc -b --noEmit` → 0 errors; size-limit 108.25 kB gzipped (limit 200 kB; gate proven to fail at 50 KB by QA on branch); Vitest 43 passed / 11 files incl. the 3 named tests (render version, 500 error state, loading), coverage 96.34 stmts / 96.36 branches / 98.59 lines (gate 80); Playwright `just e2e` 6 passed (Chromium, Pixel 7, iPhone 14 WebKit); CI run [38560446752](https://github.com/YoavIsaacs/hiking_app/actions/runs/38560446752) lint/api-test/web-test/e2e green; CodeQL run [38560446633](https://github.com/YoavIsaacs/hiking_app/actions/runs/38560446633) green, 0 open alerts. Required on `main`: `lint`, `api-test`, `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`. | 2026-10-14 |
| 0.4 | Generated API client | done | [#9](https://github.com/YoavIsaacs/hiking_app/pull/9) | On `main` @ 3688c57: `grep type Health|interface Health|isHealth web/src` → none (API types only via generated `components['schemas']`); `just gen-api` → tree clean; `tsc -b` 0 errors; API pytest 83 passed, 100% coverage; Vitest 58 passed. Deliberate break (field added without regenerating) → `api-contract` red in run [38565760255](https://github.com/YoavIsaacs/hiking_app/actions/runs/38565760255), reverted → green; `main` CI run [38568116619](https://github.com/YoavIsaacs/hiking_app/actions/runs/38568116619) and CodeQL [38568116652](https://github.com/YoavIsaacs/hiking_app/actions/runs/38568116652) green. `api-contract` required on `main`. | 2026-10-14 |
| 0.5 | Deployment | in progress — build, paused (Open decisions 2–7 pending) | | | |
| 0.6 | Pipeline rules | not started | | | |

## Current state (handoff for a fresh session)
Read this, then `docs/steps/<current step>.md`. Nothing here lives only in chat.

- **Current step:** 0.5 Deployment on branch `step/0.5-deployment`. Brief: `docs/steps/0.5.md`. Stage: see its Status line.
  **Next session starts here:** read the brief's "Session handoff (2026-10-19)". Ask the manager for A1–A3 (`ops/`
  folder, detach consequences, kill switch vs native spend caps) and for the runbook outputs (site ID, `$BUDGET_ID`,
  `hike-api` URL, `gh` checks). Then: CLAUDE.md `ops/` rows → backend stub → qa red → backend build of
  `ops/budget_guard/`; devops `ops-test`; frontend sets the real API URL.
- **GCP:** project `hike-prep` (number 1484623023), region `me-west1`, billing linked, budget 5 ILS/month
  (manager, 2026-10-19). Firebase/Hosting, WIF, service accounts: in progress by the manager (runbook steps 2–10).
- **Roadmap change (2026-10-18, manager):** community pivot — new Phase 3 "Accounts and community", old Phase 3 → 4,
  native → 5–6. Merged to `main` as #10 (6ba84ed); the master doc still needs updating (manager).
  Product rules: free without an account (plan, checklist, save on device, browse, plan from a public hike); account
  for cloud save, publish, rate, report, block. First version: profiles, publish (private/unlisted/public), feed with
  area filter, 1–5 ratings, plan this hike, report/block; no follows, comments, photos. Google sign-in now, Apple at
  native. Cost rule $0/month; database host decided in 3.1 (Neon / Supabase / Raspberry Pi).
- **Master roadmap doc:** https://claude.ai/code/artifact/846e4975-e790-41bf-8d40-801761d22191 (Claude Doc).
  **Pending:** the manager updated the doc by hand on 2026-10-18; not yet verified (Claude Docs tools weren't available
  in that session). Next: read the doc (connector, or a Markdown export in the scratchpad) and diff it section by section
  against `docs/roadmap/` on `main` (6ba84ed); report differences, patch only those. Then add the link to
  `docs/roadmap/README.md` and drop its "mirror is the newer copy" note.
- **Step branch:** `main` (incl. #10) merged into `step/0.5-deployment` on 2026-10-18, so the roadmap mirror there has phases 0–6.
- **`main` protection:** branch ruleset `main` (active, no bypass): required checks `lint`, `api-test`,
  `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`, `api-contract`; deletion and force-push blocked. PR-required, linear history etc. arrive in 0.6.
- **Open PRs:** none. Dependabot #8 (`actions/cache` 5→6) merged 2026-10-18 (09f8763) and merged into the step branch.
- **Local leftovers (manager may delete):** temp clones `%TEMP%\tmp.7qIrHpAUnP`, `%TEMP%\tmp.GMVXYXKa6R`;
  Docker images `hike-api:qa`, `hike-api:test`.

### Carry-forward (decided items waiting for their step)
- **0.5:** decide an env-var prefix for API settings (ADR) — `ENV`, `VERSION` are collision-prone. Dockerfile
  header comment should show `--build-arg VERSION`. Consider Dependabot `docker` ecosystem for `api/`.
  Secret scanning + push protection: already enabled (public repo, checked 2026-10-14); the fake-key check
  deferred from 0.1 can be run in 0.5. README still says "run everything from Git Bash" — no longer required (nit).
- **0.6:** `--fail-if-no-match` on every `pnpm --filter` in CI and pre-commit; pin CI actions to SHAs; caching (`api-test` already has setup-uv cache); confirm Dependabot handles
  the pnpm 12 lockfile.
- **Before Phase 1 screens:** UX §6 44×44 px targets (deferred from 0.3); no visual identity or tokens exist yet (`design/tokens.json`, `docs/design/` absent).
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
- Contract: operation IDs only from `operation_id()` (handler name verb_noun → camelCase); `check_operation_ids`
  enumerates via public `fastapi.routing.iter_route_contexts` (FastAPI 0.143 keeps included routers as placeholders).
  `api/openapi.json` + `web/src/api/schema.d.ts` committed, regenerated by `just gen-api`.
- `just` on Windows runs recipes with `cmd.exe /c`; recipes stay in the sh/cmd common subset.
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
- 0.3: 2 review rounds (frontend 2: hung `/health` never errored — QA caught; router default error page pre-empted the app boundary — reviewer caught, QA had only tested the boundary in isolation). QA edited frontend's `tsconfig.node.json` (needed, accepted). ux-expert/architect can't commit (no shell) → tech lead commits design docs as authored; propose making that a standing rule.
  Watch: QA tested a component in isolation but not in its real wiring — first occurrence; a second one triggers a `qa.md` change.
- 0.4: review round 1 (reviewer): typecheck alias, vacuous `--filter`, untested `create_app` wiring, boundary cases.
  QA's new real-wiring rule then found `check_operation_ids` blind to included routers (fixed). devops 2 rounds on the
  `justfile` Windows shell — both verifications used an inherited Git Bash PATH, not the real one; the manager found it.
  Tech lead committed while an agent was active (edits swept into QA's commit).
  Watch: "verified in an environment that isn't the real one" (devops, 0.4) — first occurrence.
- **Repeated patterns → changes (manager-approved and applied 2026-10-14):**
  1. QA missed failure-path gaps twice (0.1, 0.2) → `.claude/agents/qa.md`: treat every untested failure path
     of a checklist item as a *finding*, not a follow-up; always probe negatives and false positives
     (errors, 4xx/5xx, ignore rules, invalid input).
  2. Agents touched others' files via broad commands twice (0.1 `git stash`, 0.2 `ruff --fix`) → CLAUDE.md
     Git section: "Stage by path; never run `git stash`, `git add -A`, or formatters/fixers over files you
     don't own."
  3. The tests-first stub sequence above → `.claude/agents/tech-lead.md` step loop, steps 4–5.
  4. (0.4) QA tested in isolation, not through real wiring, twice (0.3, 0.4) → `.claude/agents/qa.md` verify step 6.
