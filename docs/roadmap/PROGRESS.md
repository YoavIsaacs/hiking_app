# Progress

Master roadmap: "Hike Prep App — Roadmap" doc. Mirror: `docs/roadmap/overview.md` (checkpoints) and `phase-*.md` (checklists).
The tech lead keeps this file true. A step moves to Done only with checkpoint evidence.

| Step | Title | Status | PR | Checkpoint evidence | Verified on |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Repo and tooling | done (part deferred) | [#3](https://github.com/YoavIsaacs/hiking_app/pull/3) | Fresh clone → `just install` → `just dev-api` / `just dev-web` = 3 commands each, both HTTP 200 (QA, branch); `pre-commit run --all-files` 10/10 hooks pass on `main` @ 4018695 locally and in CI run [38387791812](https://github.com/YoavIsaacs/hiking_app/actions/runs/38387791812); `just test` passes. **Deferred by manager:** secret scanning/push protection and fake-API-key check. **Open:** `lint` not yet marked required (`rules/branches/main` → `[]`). | 2026-10-13 |
| 0.2 | FastAPI skeleton | in progress | | | |
| 0.3 | React app | not started | | | |
| 0.4 | Generated API client | not started | | | |
| 0.5 | Deployment | not started | | | |
| 0.6 | Pipeline rules | not started | | | |

## Team notes
- 0.1: 2 review rounds total (frontend 1: template brought oxlint; devops 1: over-broad `.gitignore`).
  QA missed the `.gitignore` false positives (checked only the listed paths). Devops ran `git stash` touching
  a file it doesn't own (restored). Single occurrences — watch, no agent-file change yet.
