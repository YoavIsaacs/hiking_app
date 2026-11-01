# Progress

Master roadmap: "Hike Prep App — Roadmap" doc. Mirror: `docs/roadmap/overview.md` (checkpoints) and `phase-*.md` (checklists).
The tech lead keeps this file true. A step moves to Done only with checkpoint evidence.

| Step | Title | Status | PR | Checkpoint evidence | Verified on |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Repo and tooling | done (part deferred) | [#3](https://github.com/YoavIsaacs/hiking_app/pull/3) | Fresh clone → `just install` → `just dev-api` / `just dev-web` = 3 commands each, both HTTP 200 (QA, branch); `pre-commit run --all-files` 10/10 hooks pass on `main` @ 4018695 locally and in CI run [38387791812](https://github.com/YoavIsaacs/hiking_app/actions/runs/38387791812); `just test` passes. `lint` required on `main` since 2026-10-14 (ruleset `main`). **Deferred by manager:** secret scanning/push protection and the fake-API-key check. | 2026-10-13 |
| 0.2 | FastAPI skeleton | done | [#6](https://github.com/YoavIsaacs/hiking_app/pull/6) | On `main` @ 77726b0: `uv run pytest` 35 passed, coverage 100% (gate 85%, `--disable-socket`); `mypy app tests` strict → 0 errors (15 files); CodeQL run [38527140518](https://github.com/YoavIsaacs/hiking_app/actions/runs/38527140518) → 0 results, 0 open alerts; `/health` local latency n=300 after warm-up p50 1.20 ms / p95 1.64 ms / max 2.34 ms (< 50 ms). Docker (QA, branch): non-root uid 10001, `/health` returns build `GIT_SHA`/`VERSION`. Required checks on `main` (`gh api …/rules/branches/main`): `lint`, `api-test`, `Analyze (python)` (GitHub Actions). | 2026-10-14 |
| 0.3 | React app | done | [#7](https://github.com/YoavIsaacs/hiking_app/pull/7) | On `main` @ c4202b1: `tsc -b --noEmit` → 0 errors; size-limit 108.25 kB gzipped (limit 200 kB; gate proven to fail at 50 KB by QA on branch); Vitest 43 passed / 11 files incl. the 3 named tests (render version, 500 error state, loading), coverage 96.34 stmts / 96.36 branches / 98.59 lines (gate 80); Playwright `just e2e` 6 passed (Chromium, Pixel 7, iPhone 14 WebKit); CI run [38560446752](https://github.com/YoavIsaacs/hiking_app/actions/runs/38560446752) lint/api-test/web-test/e2e green; CodeQL run [38560446633](https://github.com/YoavIsaacs/hiking_app/actions/runs/38560446633) green, 0 open alerts. Required on `main`: `lint`, `api-test`, `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`. | 2026-10-14 |
| 0.4 | Generated API client | done | [#9](https://github.com/YoavIsaacs/hiking_app/pull/9) | On `main` @ 3688c57: `grep type Health|interface Health|isHealth web/src` → none (API types only via generated `components['schemas']`); `just gen-api` → tree clean; `tsc -b` 0 errors; API pytest 83 passed, 100% coverage; Vitest 58 passed. Deliberate break (field added without regenerating) → `api-contract` red in run [38565760255](https://github.com/YoavIsaacs/hiking_app/actions/runs/38565760255), reverted → green; `main` CI run [38568116619](https://github.com/YoavIsaacs/hiking_app/actions/runs/38568116619) and CodeQL [38568116652](https://github.com/YoavIsaacs/hiking_app/actions/runs/38568116652) green. `api-contract` required on `main`. | 2026-10-14 |
| 0.5 | Deployment | done (part deferred) | [#11](https://github.com/YoavIsaacs/hiking_app/pull/11), [#16](https://github.com/YoavIsaacs/hiking_app/pull/16), [#17](https://github.com/YoavIsaacs/hiking_app/pull/17) | Both live on HTTPS: API `https://hike-api-zr6tmbe2ya-zf.a.run.app/health` 200, `git_sha` 5e8e157 == `main` HEAD, `env: production`; web `https://hike-prep.web.app` 200 `no-cache`, HTTP → 301 HTTPS; hashed assets `immutable` (preview channel check). Deploys from `main` via WIF, no keys: Deploy API [39233736461](https://github.com/YoavIsaacs/hiking_app/actions/runs/39233736461), Deploy Web [39233736800](https://github.com/YoavIsaacs/hiking_app/actions/runs/39233736800) (live Playwright 6 passed). **Broken deploy rolls back with no manual step:** #16 (wrong `git_sha` on purpose) → run [39243336412](https://github.com/YoavIsaacs/hiking_app/actions/runs/39243336412) failed at candidate smoke 6/6, promote skipped, traffic 100 % on `hike-api-00002-mef`, live `/health` kept 3398338; fix-forward #17 → run [39244521177](https://github.com/YoavIsaacs/hiking_app/actions/runs/39244521177) green, 100 % on `hike-api-00005-ruw`. PR preview: #11 `https://hike-prep--pr-11-ehfnijw0.web.app` commented. CORS: `hike-prep.web.app` allowed, `evil.web.app` no ACAO. **Phone (manager):** < 5 s cold / < 1 s warm passed — numbers not recorded (manager: "roughly correct"). No new required checks; required on `main` (`gh api …/rules/branches/main`): `lint`, `api-test`, `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`, `api-contract`. **Deferred by manager:** $1 hard stop / kill switch (ADR 0003) — revisit before Phase 3. | 2026-10-19 |
| 0.6 | Pipeline rules | done | [#18](https://github.com/YoavIsaacs/hiking_app/pull/18), [#23](https://github.com/YoavIsaacs/hiking_app/pull/23) | **0 ways to push to `main` without green checks:** ruleset `main` (`gh api …/rules/branches/main`): `deletion`, `non_fast_forward`, `pull_request` (0 approvals, squash only), `required_linear_history`, `required_status_checks` = `lint`, `api-test`, `web-test`, `e2e`, `api-contract`, `Analyze (python)`, `Analyze (javascript-typescript)`, `pr-title`; bypass list empty. Manager's direct push of a test commit (admin) → `GH013 … Changes must be made through a pull request`, rejected. Failing-test PR #19 → `api-test` red, `BLOCKED`. Repo: squash only, message = PR title. **PR pipeline:** 95 s wall (#18, all jobs), 88 s (#19) — < 5 min. Path filters: #20 web-only / #21 api-only / #22 docs-only skipped the other area's jobs, still `CLEAN`; #22 non-conventional title → `pr-title` red, retitled → green. **Merge → live:** #18 merged 12:41:40Z; Deploy API [39254055437](https://github.com/YoavIsaacs/hiking_app/actions/runs/39254055437) 78 s, Deploy Web [39254055323](https://github.com/YoavIsaacs/hiking_app/actions/runs/39254055323) 106 s → live ≈ 1 m 50 s (< 10 min); `/health` `git_sha` 53fa3cb. **Release:** release-please (GitHub App token) opened #23 with CI running; merged → tag + release `v0.1.0`, `CHANGELOG.md`. **Nightly:** dispatch [39254396266](https://github.com/YoavIsaacs/hiking_app/actions/runs/39254396266) green on fresh deps (e.g. fastapi 0.143.2 → 0.148.0); forced failure opened #25, second forced run commented on it (closed). 429 probe: 0 × 429 at 100 concurrent (`max-instances=1` kept). New required check: `pr-title`. | 2026-10-19 |
| 1.1 | GPX test corpus | **partial** (manager deviation) | [#27](https://github.com/YoavIsaacs/hiking_app/pull/27) | On `main` @ 55bac5b: 9 `.gpx` + 9 `expected.json` entries (checkpoint needs 10 → 9/10). Edge cases → file: loop → 3 AllTrails files; no elevation → `derived-tel-hadid-no-ele`; > 10k points → `derived-ben-shemen-over-10k-points` (10,417); `<rte>` → `derived-modiin-hills-south-rte`; multi-segment → `derived-tel-hadid-multi-segment` (34.1 m gap); malformed → `derived-ben-shemen-truncated`; (+ not GPX → `derived-modiin-hills-south-kml`); **out-and-back → none (deferred)** → 6/7. Sources: AllTrails only (1/4). Reference values: manager-supplied AllTrails (8.5 km/198 m, 10.6 km/200 m, 6.4 km/103 m). `uv run pytest` 380 passed, coverage 99.17 % (local and `api-test` on PR); post-merge CI [39267399727](https://github.com/YoavIsaacs/hiking_app/actions/runs/39267399727), CodeQL, Deploy API green, live `git_sha` 55bac5b. No new required checks. **Open until** the manager's Komoot / Strava / own-recording files arrive. | 2026-10-19 |
| 1.2 | GPX parser | done | [#33](https://github.com/YoavIsaacs/hiking_app/pull/33) | **Live** (`https://hike-api-zr6tmbe2ya-zf.a.run.app`, `git_sha` 4870b23 == `main` HEAD), `POST /v1/routes/parse` on all 9 fixtures: Ben Shemen 10,496 m / 204.5 m vs AllTrails 10.6 km / 200 m (−0.98 % / +2.2 %); Modiin 8,580 m / 202.0 m vs 8.5 km / 198 m (+0.94 % / +2.0 %); Tel Hadid 6,342 m / 99.6 m vs 6.4 km / 103 m (−0.90 % / −3.33 %) — bars 2 % / 10 %. Largest fixture (`derived-ben-shemen-over-10k-points`, 10,417 pts) 0.49 s round trip live, 55 ms in the CI benchmark (< 2 s). `<rte>` and multi-segment 200; truncated and KML → 422 `invalid_gpx`; 11 MB → 413; **0 × 500** (live, and Hypothesis/never-500 suites). On `main` @ 4870b23: CI [39423033087](https://github.com/YoavIsaacs/hiking_app/actions/runs/39423033087), CodeQL [39423033091](https://github.com/YoavIsaacs/hiking_app/actions/runs/39423033091), Deploy API [39423033084](https://github.com/YoavIsaacs/hiking_app/actions/runs/39423033084) green; branch gates: 1,637 passed, coverage 99.73 % (gate 85), ruff/mypy strict clean. Hostile input (ADR 0004): worst RSS 97.3 MiB at 512 MiB, slowest admitted file 2.6 s. New required check `benchmark` (ruleset read 2026-10-20: `lint`, `api-test`, `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`, `api-contract`, `pr-title`, `benchmark`). **Deviations (manager):** own expat reader instead of gpxpy (option A); path `/v1/routes/parse`; 100k-point cap; Cloud Run `--concurrency=8` (#35, first gated deploy: Deploy API [39426483438](https://github.com/YoavIsaacs/hiking_app/actions/runs/39426483438) printed `containerConcurrency=8`, promoted `hike-api-00019-pal`, live `git_sha` cd24cb0). Team: ≈ 49 agent calls, 4 review rounds; QA missed hostile shapes in rounds 1, 3, 4 (see brief team log). | 2026-10-20 |
| 1.3 | Elevation backfill | done | [#41](https://github.com/YoavIsaacs/hiking_app/pull/41) | **Live** (`git_sha` 85d175d == `main` HEAD): `POST /v1/routes/parse` of `derived-tel-hadid-no-ele.gpx` → 200 in 0.53 s, gain **104.99 m vs AllTrails 103 m (+1.93 %, bar ±15 %)**, `elevation_source = "lookup"`, 72 points, no warnings; Cloud Logging `elevation_lookup` for request `1613ceaa4c284e80b7e383b90609c16a` (read by the manager): `calls=1 outcome=ok points=72 batches=1` (bar ≤ 5 calls). Offline (recorded responses): Tel Hadid +1.9 %, Modiin −1.7 % (1 call), Ben Shemen +1.8 % (2 calls); 250 points → exactly 3 requests; has-elevation → 0; worst case ≤ 5 (Hypothesis). Grid pick spacing 90 m / window 135 m / T 3.0 m (ADR 0005 Amendment 1). Branch gates: 2074 passed, 99.52 %; ruff, mypy strict clean. On `main` @ 85d175d: CI, CodeQL, Deploy API (first CI build of the pinned image: `python 3.12.15 expat expat_2.9.0`), Deploy Web green. No new required checks (ruleset read 2026-11-01: `lint`, `api-test`, `Analyze (python)`, `web-test`, `e2e`, `Analyze (javascript-typescript)`, `api-contract`, `pr-title`, `benchmark`). **Manager decisions:** $0-only fallbacks for the Open-Meteo quota (ADR 0005, option D excluded). Team: ≈ 22 agent calls; review 1 round (reviewer) + 2 CI rounds (see brief). | 2026-11-01 |

## Current state (handoff for a fresh session)
Read this, then `docs/steps/<current step>.md`. Nothing here lives only in chat.

- **Current step:** 1.3 Elevation backfill — `docs/steps/1.3.md`, branch `step/1.3-elevation-backfill`. Stage: **PR**
  (build, verify, review done 2026-11-01; reviewer approved; review round fixed: raw-byte body cap + bounded gzip,
  mock-only read paths removed). 1.2 carry items all closed in 1.3. After merge: watch Deploy API (first CI build of the
  new Dockerfile), then live checkpoint + `elevation_lookup` log line (manager reads Cloud Logging).
  **Next after 1.3 (proposed, small fix branch):** ADR 0004 item 55 RSS ratchet (119 → 398 MiB under repeated hostile
  uploads) + an `api-image` PR job building `api/Dockerfile` (new required check → manager approval).
  **Tech-lead process note:** don't commit while a subagent is editing the same tree. Pre-commit stashes the
  unstaged files mid-edit (it happened twice on `step/1.2-close` and restored cleanly).
  **For 1.10:** CORS POST, Blob typing, 429 copy. **Manager:** update the master roadmap doc (own expat reader, not
  gpxpy; `/v1/routes/parse`).
  **1.1 (manager, 2026-11-01): AllTrails is the only data source**; Komoot / Strava / own recordings dropped (GPX assumed
  equivalent across apps). Still owed by the manager: one AllTrails out-and-back `.gpx` + AllTrails' distance and gain, into
  `docs/maps/` (uncommitted). Then QA adds it, removes `out_and_back` from `DEFERRED_BY_MANAGER` in
  `api/tests/fixtures/test_gpx_corpus.py`, and 1.1 closes at 10 files / 7 edge cases / 1 source (deviation).
  - Dependabot #24 (actions minor) and #26 (`setup-uv` 7.6 → 10.3; changelog checked: no impact — we set
    `enable-cache: true` explicitly, no `.tool-versions`) merged 2026-10-19; post-merge Deploy API 69 s green, live
    `git_sha` 17e3ff3. No open PRs.
- **GCP:** project `hike-prep` (number 1484623023), region `me-west1`, billing linked, budget 5 ILS/month
  (manager, 2026-10-19). Runbook steps 1–4, 5–10 done (manager) and verified (tech lead): Firebase site `hike-prep`, WIF provider `hiking-app`, SAs, env `production` (branch `main` only), API URL `https://hike-api-zr6tmbe2ya-zf.a.run.app` (sample image until the first deploy).
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
- **`main` protection (0.6):** ruleset `main` (active, no bypass): PR required (0 approvals, squash only), linear
  history, deletion and force-push blocked; required checks `lint`, `api-test`, `web-test`, `e2e`, `api-contract`,
  `Analyze (python)`, `Analyze (javascript-typescript)`, `pr-title`. Repo: squash merge only, commit = PR title (body blank).
  The ruleset UI also set `require_extra_approval_for_unattributed_changes: true` (not in the runbook) — harmless so far; first suspect if a PR is blocked unexpectedly.
- **Releases:** release-please (GitHub App `hike-release-please`; var `RELEASE_APP_CLIENT_ID`, secret
  `RELEASE_APP_PRIVATE_KEY`) keeps a release PR open; the manager merges it to cut a release. Nightly 02:43 UTC on fresh deps; failures go to one open `nightly-failure` issue.
- **Open PRs:** none (2026-11-01; Dependabot #36–#39 merged by the manager, merged into the 1.3 branch).
- **Local leftovers (manager may delete):** temp clones `%TEMP%\tmp.7qIrHpAUnP`, `%TEMP%\tmp.GMVXYXKa6R`;
  Docker images `hike-api:qa`, `hike-api:test`.

### Carry-forward (decided items waiting for their step)
- **From 0.6 (needs a decision when it matters):** API `/health` `version` comes from `api/pyproject.toml`, not the
  release-please version (`.release-please-manifest.json`) — wire them together (release-please `extra-files` + `uv.lock`
  sync) or accept the drift; raise before the next release. When `design/tokens.json` exists, add `design/**` to the CI
  `web` path filter. QA: web pre-commit hooks don't run in a bare `git worktree` (needs its own `pnpm install`, short path).
- **Before Phase 3 (or when there is something to show):** custom domain for the web app (Firebase Hosting custom domain; buying a domain costs money → manager approval) and optionally `/api/**` Hosting rewrite to Cloud Run (check `me-west1` support). Revisit the deferred ADR 0003 kill switch.
- **Before Phase 1 screens:** UX §6 44×44 px targets (deferred from 0.3); no visual identity or tokens exist yet (`design/tokens.json`, `docs/design/` absent).
  Phase 1 needs a graphic-designer pass before the first real screen.
- **Windows dev:** stopping `just dev-api` can orphan uvicorn (README troubleshooting). Port 8765 is held by an
  unrelated process on the manager's machine — avoid it.

### Settled technical decisions (so nobody re-litigates them)
- `api/`: no build-system; pytest `pythonpath = ["."]`; `--disable-socket --allow-hosts=127.0.0.1` (Windows
  TestClient loopback; outbound still blocked); `filterwarnings = ["error", <one targeted httpx/Starlette ignore>]`
  — stay on `httpx`; `httpx2` would need an ADR + manager approval.
- API settings: env names = `HIKE_` + field name upper-cased (0.5, ADR 0002); `create_app(settings)`
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
- 0.5: review round 1 (reviewer): bare `Any` in QA's tests (blocking), preview `jq` masking failures, Docker build-arg test missing,
  rollback skipped on cancel. Then 2 CI rounds on PR #11: firebase-tools error hidden by the step's redirect; runbook step 8
  bound name-only OIDC subjects but the repo uses **immutable subjects** → 403 on impersonation; the runbook self-check
  never tested a real token exchange. Architect correctly refused a tech-lead claim ("rename-safe") the docs didn't support.
  Manager dropped the kill switch (ADR 0003 deferred). Tech lead claimed "WIF auth works" too early (corrected); committed
  while an agent was active (second time, after 0.4).
  Watch → now repeated twice:
  - **Tech lead commits while an agent is running** (0.4, 0.5) → `.claude/agents/tech-lead.md` step 5 changed (manager-approved 2026-10-19).
  - **Verification that doesn't exercise the real path** (devops 0.4 inherited PATH; 0.5 runbook self-check read config,
    never exchanged a token) → `.claude/agents/devops.md` "Verify the real path" rule added (manager-approved 2026-10-19).
- 0.6: devops 1 review round (reviewer: release-please would have cut v1.0.0 — `0.0.0` manifest means "no release";
  shared concurrency group could cancel pending `main` runs; runbook squash message `PR_BODY` contradicted D1). QA's
  verification PRs and 429 probe were clean. Devops added Dependabot commit prefixes + a README hint (accepted) and ran
  `actionlint` ad hoc (not added). Manager stored a variable as a secret (caught by tech lead's read-only check); the
  first direct-push command was bash syntax in PowerShell — runbook commands for the manager must be PowerShell-safe.
  Tech lead's own direct-push attempt was blocked by tool permissions (correct; manager ran it). No repeated pattern.
- 1.1: qa 1 review round (reviewer: QA's own multi-segment derivation rounded coords to 4 dp → +7 % distance, and no test
  compared derived files to their parents; fixed + fidelity tests). QA added `api/tests/__init__.py` (needed for mypy;
  accepted). Tech lead's bulk `sed` wrongly ticked manager actions in the brief (caught and fixed before commit).
  Watch: "a derived artefact not checked against its source" (QA, 1.1) — first occurrence.
- 1.3: reviewer 1 round (decompressed-byte cap; sharp grid peak; stale PROGRESS; grid-not-committed wording). QA found the
  undecodable-gzip 500 (good). Tech lead rejected a mock-only fallback in app code; QA's report then claimed a test hit the
  real path when respx pre-decoded it (backend caught it by stopping correctly). CI: Linux-only exact-float boundary test
  (QA) and `main` red from ubuntu-latest → 26.04 (fixed in #42, runners pinned). Backend edited QA test inputs beyond the
  ADR pin list (accepted by QA). Devops' first image-pin pass couldn't run (Docker off) and its edit wouldn't have built.
  Watch → **repeated (2nd)**: QA verifying through a test double or harness that bypasses the path under test (0.3 isolation
  vs wiring; 1.3 respx pre-read). Proposed `qa.md` change (pending manager approval): "Know what your double does: when a
  test is about wire-level handling (encoding, streaming, size caps), prove the production read path runs, e.g. by making
  the alternative path raise."
- **Repeated patterns → changes (manager-approved and applied 2026-10-14):**
  1. QA missed failure-path gaps twice (0.1, 0.2) → `.claude/agents/qa.md`: treat every untested failure path
     of a checklist item as a *finding*, not a follow-up; always probe negatives and false positives
     (errors, 4xx/5xx, ignore rules, invalid input).
  2. Agents touched others' files via broad commands twice (0.1 `git stash`, 0.2 `ruff --fix`) → CLAUDE.md
     Git section: "Stage by path; never run `git stash`, `git add -A`, or formatters/fixers over files you
     don't own."
  3. The tests-first stub sequence above → `.claude/agents/tech-lead.md` step loop, steps 4–5.
  4. (0.4) QA tested in isolation, not through real wiring, twice (0.3, 0.4) → `.claude/agents/qa.md` verify step 6.
