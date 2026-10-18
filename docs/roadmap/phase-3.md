# Phase 3 — Accounts and community checklist

All steps are required. Order matters: 3.1 decides, 3.2–3.4 build the base, 3.5–3.8 build the community, 3.9 makes it safe to open.

**Free vs account (product rule).** Without an account you can plan, build checklists, save trips on this device
(offline), browse the feed and public hike pages, and plan from a public hike. An account is needed to save trips to
the cloud (sync across devices), publish, rate, report and block.

**Cost rule.** Running cost stays $0/month. Every service must fit a free tier; anything that would cost money needs
the manager's approval first.

## 3.1 Community design

- [ ] ADR: auth — Firebase Auth (Google sign-in now; Sign in with Apple added in 5.7); FastAPI verifies ID tokens with firebase-admin
- [ ] ADR: database — PostgreSQL on a $0 host (candidates: Neon free tier, Supabase free tier, the manager's Raspberry Pi); compare free-tier limits, cold-start/pausing, backups and restore, security exposure, and the move to Cloud SQL when outgrown (connection string only)
- [ ] ADR: data model — `users`, `profiles`, `trips`, `feedback`, `published_hikes`, `ratings`, `reports`, `blocks`; ownership and soft-delete rules
- [ ] ADR: privacy — visibility levels (private default, unlisted link, public); route-end trimming default and opt-out for trailhead starts; what a published hike exposes (never: email, GPX timestamps, raw track, untrimmed ends); how "Plan this hike" works on a trimmed route
- [ ] ADR: moderation — report reasons, auto-hide threshold, admin role (Firebase custom claim, manager only), block semantics, account suspension
- [ ] API contract sketch for every Phase 3 endpoint (paths, request/response models, auth, errors)
- [ ] UX spec (`docs/ux/`): feed, hike page, publish flow, rating, "Plan this hike", sign-in prompts at gated actions, profile, account menu, report/block, terms; states, copy, accessibility, acceptance criteria
- [ ] Visual spec: avatar fallback (initials, no photo uploads), rating stars, visibility badges, feed card
- [ ] Drafts of the privacy policy and terms of use (manager approves the text)
- [ ] Verify: monthly cost at 100 users estimated at $0, with each free-tier limit and its headroom listed

## 3.2 API hardening (moved from the old 3.7; now required because the app accepts user content)

- [ ] All public routes under `/v1` (already the case) with a router-level prefix
- [ ] slowapi rate limits: e.g. 30/min per IP for `/v1/checklist`, 10/min for `/v1/routes/parse`; per-user limits on write endpoints (publish 10/h, rate 60/h, report 20/h)
- [ ] Consistent `ErrorResponse` for 4xx and 5xx, including validation errors
- [ ] Structured JSON logs with request ID, user ID (if any), latency; never log tokens or email
- [ ] Sentry SDK for API and web (free plan); release = git SHA; source maps uploaded from CI
- [ ] Cloud Run: staging service (`api-staging`) deployed from PRs with the `deploy` label
- [ ] Locust scenario: parse + checklist + feed mix at 20 requests/s for 2 minutes
- [ ] Tests: 429 after the limit; every error path matches `ErrorResponse`
- [ ] CI: `load-test` workflow against staging; fails if p95 ≥ 1 s
- [ ] Verify: a week of production logs with 0 unhandled 500s

## 3.3 Accounts and database

**Auth**

- [ ] Firebase Auth with Google sign-in in the web app
- [ ] `app/auth.py`: FastAPI dependency verifying the Firebase ID token (firebase-admin), returning `CurrentUser`; an optional variant for endpoints that also serve signed-out users
- [ ] `GET /v1/me` → `{user_id, email, handle, display_name, created_at}`
- [ ] `PUT /v1/me/profile` → `{handle, display_name, bio}`; handle unique, 3–20 chars `[a-z0-9_]`; bio ≤ 160 chars
- [ ] `DELETE /v1/me` deletes the account and everything it owns (trips, published hikes, ratings, reports filed, blocks) and the Firebase user
- [ ] Terms of use accepted at first sign-in; acceptance stored with its version
- [ ] Signed-out mode keeps working exactly as in Phase 2; sign-in is asked for only at a gated action
- [ ] Tests: valid token, expired token, wrong project, missing header → 200 / 401 / 401 / 401
- [ ] Tests: handle validation and uniqueness; account deletion removes 100% of the user's rows

**Database**

- [ ] PostgreSQL on the host chosen in 3.1; connection string in Secret Manager; backups per the ADR
- [ ] SQLAlchemy 2.0 async models for the 3.1 data model
- [ ] Alembic initialised; first migration
- [ ] Local Postgres via `docker compose` for development
- [ ] Tests: Alembic upgrade head → downgrade base → upgrade head on a clean Postgres
- [ ] CI: Postgres service container in `api-test`
- [ ] CI: `migrations` job (required when `api/migrations/**` changes)
- [ ] CI: deploy runs `alembic upgrade head` before shifting traffic
- [ ] Verify: sign-in to account menu in ≤ 3 taps; a backup restores into a clean database

## 3.4 Cloud trips and sync

- [ ] `trips` columns: `id` (uuid), `user_id`, `name`, `date`, `start_time`, `options` (jsonb), `route` (jsonb), `checklist` (jsonb), `ticks` (jsonb), `rules_version`, `created_at`, `updated_at`, `deleted_at` (soft delete for sync)
- [ ] `GET /v1/trips` (paginated, `?updated_since=`)
- [ ] `POST /v1/trips`
- [ ] `GET /v1/trips/{trip_id}`
- [ ] `PUT /v1/trips/{trip_id}` (with `updated_at` for conflict detection)
- [ ] `DELETE /v1/trips/{trip_id}` (soft delete)
- [ ] `POST /v1/trips/{trip_id}/refresh` → new checklist + server-side diff
- [ ] `POST /v1/sync` — request: `{cursor, changes[]}`; response: `{cursor, changes[], conflicts[]}`; last write wins per trip by `updated_at`
- [ ] Sync engine in the web app: local changes queued in Dexie, pushed on reconnect and on app focus
- [ ] First sign-in on a device: offer to upload the trips already saved on it
- [ ] Sign-out clears synced data from the device
- [ ] Tests: user A can't read, update or delete user B's trip (403/404)
- [ ] Tests: sync — 10 scenarios (create offline, edit offline on two devices, delete vs edit, etc.)
- [ ] Verify: phone → laptop sync < 5 s

## 3.5 Publish a hike

- [ ] From a saved trip: title (≤ 80), description (≤ 2,000), region (free text), visibility `private` (default) / `unlisted` / `public`
- [ ] A published hike is a snapshot, not a live view of the trip: route summary and down-sampled points (trimmed), stats, timing, the checklist as packed (ticked items), and the author's feedback (missing, didn't need, actual duration)
- [ ] Never published: email, GPX timestamps, the raw track, ticks of items not packed, points inside the trimmed ends
- [ ] Route-end trimming: `redact_route(route, trim_m) -> RouteSummary` as a pure function; default and opt-out per the 3.1 privacy ADR
- [ ] `POST /v1/hikes`, `GET /v1/hikes/{hike_id}`, `PATCH /v1/hikes/{hike_id}` (text, visibility), `DELETE /v1/hikes/{hike_id}` (unpublish → 404 for everyone else)
- [ ] Publish screen from the trip page; visibility badge on published trips; "copy link"
- [ ] Tests: no published point lies within `trim_m` of the true start or end, on all 10 fixtures; Hypothesis property test over random routes
- [ ] Tests: private hike → 404 for other users and signed out; unlisted → 200 by link, absent from feed and search; only the author can edit or delete (403/404)
- [ ] Tests: editing or deleting the source trip doesn't change the published snapshot
- [ ] Verify: publishing from a saved trip takes ≤ 3 taps

## 3.6 Feed and hike page

- [ ] `GET /v1/feed?cursor=&near=lat,lon&radius_km=&min_km=&max_km=&sort=recent|top` — cursor pagination, public hikes only; excludes hidden content and users blocked in either direction
- [ ] `GET /v1/users/{handle}` → public profile and their public hikes
- [ ] `/feed` screen: cards with title, author, distance, gain, duration, rating, region; infinite scroll; filters for area and length; empty and offline states (last page cached)
- [ ] `/h/{hike_id}` hike page, viewable signed out: stats, elevation profile, trimmed route, the author's packing list with their notes, rating, "Plan this hike"
- [ ] `/u/{handle}` profile page
- [ ] Tests: pagination has no duplicates or gaps while new hikes are inserted; each filter; private, unlisted, hidden and blocked content never appears
- [ ] Tests: component tests for feed, card and hike page states; Playwright: signed out, open feed → open a hike
- [ ] Verify: feed p95 < 500 ms with 1,000 seeded hikes; first feed page visible in < 2 s on your phone over mobile data

## 3.7 Ratings

- [ ] 1–5 stars, one rating per user per hike (setting it again replaces it); no written reviews in this phase
- [ ] `PUT /v1/hikes/{hike_id}/rating` `{stars}`, `DELETE /v1/hikes/{hike_id}/rating`
- [ ] Hike shows average and count; `sort=top` uses a Bayesian average (a pure function), so 1 five-star rating doesn't beat 40 four-star ones
- [ ] Tests: upsert keeps one rating per user; rating your own hike → 403; signed out → 401; out-of-range stars → 422; a deleted account's ratings leave the average
- [ ] Tests: Bayesian average on fixed examples, plus a Hypothesis property (result stays within 1–5)
- [ ] Verify: rating takes 1 tap from the hike page

## 3.8 Plan this hike

- [ ] `POST /v1/hikes/{hike_id}/plan` `{date, start_time, options}` → a fresh `ChecklistResponse` for your date and forecast, computed server-side from the hike's stored route
- [ ] The author's experience merged in by a pure function: items they logged as missing are added as "consider" with the reason "The author wished they'd had this"; items they marked as not needed are flagged with the author's note
- [ ] The new trip saves on the device when signed out, and syncs when signed in; the hike's "planned N times" count goes up
- [ ] Tests: the checklist uses the planner's date and weather, not the author's; author-missing items appear with their reason; private or unpublished hike → 404; the merge function on 5 scenarios
- [ ] Playwright: hike page → Plan this hike → pick date → checklist visible
- [ ] Verify: hike page to your own checklist in ≤ 4 taps; 100% of author-flagged items show with their reason

## 3.9 Safety and moderation

- [ ] Report a hike or a profile: reason (spam, offensive, unsafe advice, private information, other) + optional note
- [ ] Auto-hide after reports from 3 distinct users, until an admin decides
- [ ] Block a user: their content disappears for you and yours for them, everywhere
- [ ] Admin role via Firebase custom claim (manager only): report queue, hide/restore content, suspend a user
- [ ] `POST /v1/reports`, `POST /v1/blocks`, `DELETE /v1/blocks/{user_id}`, `GET /v1/admin/reports`, `POST /v1/admin/hikes/{hike_id}/hide`, `POST /v1/admin/users/{user_id}/suspend`
- [ ] Privacy policy and terms pages on the web app, linked from the account menu and the sign-in prompt
- [ ] Account deletion (3.3) reachable from the account menu
- [ ] Tests: hidden content is gone from feed, profile and hike page for everyone except the author and admins; block works both ways; non-admin → 403 on every admin endpoint; suspended user's writes → 403
- [ ] Tests: auto-hide at exactly 3 distinct reporters, not at 3 reports from one user
- [ ] Verify: a report reaches the admin queue in < 1 min; hiding takes effect in the feed in < 1 min; `docs/ugc-compliance.md` ticks every App Store guideline 1.2 and Google Play UGC requirement
