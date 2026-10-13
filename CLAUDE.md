# Hike Prep App — project rules for every agent

A mobile app that builds hike packing checklists from a GPX route and the weather forecast.
React PWA + FastAPI first (Phases 0–3), then React Native / Expo (Phases 4–5), same FastAPI backend throughout.

Everyone in this repo — the tech lead and every subagent — follows this file. Role files in
`.claude/agents/` add to it; they never relax it.

## Team

| Role | Agent | Owns | Never touches |
| --- | --- | --- | --- |
| Manager | the human (Yoav) | priorities, approvals, merges, anything needing an account, a console or a phone | — |
| Tech lead | `tech-lead` (main session) | step briefs, delegation, review, PRs, `docs/roadmap/PROGRESS.md`, `docs/steps/` | product code and tests (delegates them) |
| Architect | `architect` | `docs/adr/`, `docs/architecture/`, interface/contract sketches | implementation, tests |
| Backend expert | `backend-expert` | `api/` application code, `api/Dockerfile`, API-side CI jobs | `web/`, tests written by QA (may add unit tests for its own internals) |
| Frontend expert | `frontend-expert` | `web/` application code, web-side CI jobs | `api/`, the generated `web/src/api/schema.d.ts` by hand |
| QA | `qa` | acceptance tests, e2e, test fixtures, coverage, checkpoint verification | application code |

## Source of truth

1. `docs/roadmap/` — the roadmap and per-phase step checklists, mirrored from the "Hike Prep App — Roadmap" doc.
   The doc is the master copy; if the two disagree, stop and tell the tech lead, who asks the manager.
2. `docs/roadmap/PROGRESS.md` — which steps are done, verified, and how.
3. `docs/steps/<step-id>.md` — the brief for the step in progress.
4. `docs/adr/` — architecture decisions. A decision not in an ADR is not decided.

## Definition of done (a step)

A step is done only when **all** hold:
- every checklist item in the step is met or explicitly deferred by the manager (written in the brief);
- its tests are automated and pass locally and in CI;
- every CI check the step adds exists, is green, and is listed for the manager to mark as **required**;
- its measurable **Checkpoint** is verified with evidence (command output, numbers, links) recorded in `PROGRESS.md`.

## Engineering standards (non-negotiable)

- **No untested logic.** Every behaviour change ships with tests that fail without it.
- **No network in unit tests.** Python: `pytest-socket` (`--disable-socket`), outbound HTTP mocked with `respx`. Web: MSW. Real network only in e2e and explicit smoke tests.
- **No hand-written API types.** The web client uses types generated from FastAPI's OpenAPI (`pnpm gen:api`). The generated file is committed and never edited by hand.
- **Rules stay server-side and pure.** Packing-rule logic lives in the API as pure functions (input → output, no I/O, no clock, no randomness); I/O sits at the edges.
- **Coverage gates are respected.** Never lower a threshold, add `# pragma: no cover`, `/* istanbul ignore */`, `skip`, or `xfail` to get green. If a gate is wrong, raise it with the tech lead.
- **Strict types.** mypy strict and TypeScript strict; no `Any`/`any`, `type: ignore`, or `@ts-ignore` without a one-line reason on the same line.
- **Every CI check a step adds becomes a required check.**
- **Stay in the stack.** Python 3.12, FastAPI, Pydantic, gpxpy, uv, pytest (+ respx, Hypothesis, syrupy), ruff, mypy; React + TS, Vite, TanStack Query, Zustand, Dexie, Vitest, Playwright; later Expo, Jest, Maestro. A new dependency outside this list needs an ADR and manager approval.
- **Scope discipline.** Do the step, the whole step, and nothing else. Spotted something out of scope? Note it under "Follow-ups" in your report; don't do it.

## Layout

```
api/                 FastAPI app (uv project)        → backend-expert
  app/               application code
  tests/             pytest                          → qa (acceptance) + backend-expert (unit)
web/                 React + Vite app (pnpm)         → frontend-expert
  src/
  e2e/               Playwright                      → qa
.github/workflows/   CI and deploy                   → owner of the area the job checks
docs/roadmap/        roadmap mirror + PROGRESS.md    → tech-lead
docs/steps/          one brief per step              → tech-lead
docs/adr/            decision records                → architect
```

## Commands

Use the `justfile` targets once they exist (`just install`, `just test`, `just lint`, `just gen-api`).
Until then: `cd api && uv run pytest`, `uv run ruff check .`, `uv run mypy .`; `cd web && pnpm test`, `pnpm lint`, `pnpm tsc --noEmit`.
Run the gates for the area you touched before you report back.

## Git

- Work happens on the step branch the tech lead created: `step/<id>-<slug>` (e.g. `step/0.2-fastapi-skeleton`). Never commit to `main`.
- Conventional Commits (`feat(api): …`, `test(web): …`, `ci: …`, `docs(adr): …`). Small commits, each with passing gates.
- Only the tech lead pushes and opens PRs. Nobody force-pushes, rewrites shared history, or merges — the manager merges.
- Never commit secrets, `.env*` files, or credentials. If a task seems to need one, stop and report.

## Handoffs

Subagents start with no memory of the conversation. Everything they need is in the task the tech lead sends
and in the files it points to. Every subagent ends with a report in this shape and nothing else:

```
## Result: done | blocked | needs-decision
## What changed
- <file>: <one line>
## Evidence
- <command> → <result: pass counts, coverage %, timings>
## Checklist items covered
- <item text from docs/steps/<id>.md>
## Open issues / follow-ups
- <anything out of scope, any doubt, any shortcut you were tempted to take>
```

`blocked` and `needs-decision` mean stop and say exactly what is needed. Never guess past a missing decision.
