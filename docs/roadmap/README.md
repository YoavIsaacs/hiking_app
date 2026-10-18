# Roadmap mirror

Read-only mirror of the "Hike Prep App — Roadmap" doc, which stays the master copy. Mirrored 2026-10-13.

**2026-10-18 — community pivot (manager decision).** Applied here first, at the manager's request: new Phase 3
"Accounts and community" (all steps required); the old Phase 3 menu became Phase 4 (its accounts step and API
hardening moved into Phase 3); native moved to Phases 5–6, with a new 5.7 for sign-in and community screens.
Cost rule: $0/month. **The master doc must be updated to match** (manager action); until then this mirror is the
newer copy.

| File | Holds | Use it for |
| --- | --- | --- |
| `overview.md` | Phase goals, exit checkpoints, and every step's summary with its **Tests**, **CI** and **Checkpoint** | What "done" means for a step |
| `phase-0.md` … `phase-6.md` | Detailed per-step checklists (files, models, endpoints, individual tests) | What to build in a step |
| `PROGRESS.md` | Status and checkpoint evidence per step (tech lead maintains) | Where we are |

A step brief needs both: the checklist items from `phase-N.md` and the Tests / CI / Checkpoint lines from `overview.md`.

Don't edit the mirror files to change scope. Scope changes go to the manager, then into the doc, then get re-mirrored here in a `docs(roadmap): …` commit.
