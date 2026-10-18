# Hike Prep App — Roadmap

Oct 12, 2026 · @Yoav

## Overview

The app turns a hiking route and a date into a packing checklist, with a one-line reason next to every item. It starts as a React PWA on a FastAPI backend, adds accounts and a community where people publish hikes with their packing lists, rate them and plan from them, and moves to React Native (Expo) only after the PWA has been used on real hikes.

The guiding rule: **all the thinking lives in FastAPI.** The frontend only uploads, displays and ticks boxes, so the migration is a new UI over an unchanged API, not a rewrite.

&#91;embedded content: roadmap · 7 phases, 1 decision gate\]

Phases 0–4 build and prove the PWA (Phase 3 adds accounts and the community); native starts only if the gate finds a real reason for it.

**Free to use.** Planning, checklists, saving on your device and browsing the community need no account. An account is needed to save to the cloud, publish, rate, report and block.

**Cost rule.** Running cost stays $0/month: every service must fit a free tier (Cloud Run, Firebase Hosting and Auth, a free Postgres host). A GCP card is on file with a budget alert; anything that would cost money needs the manager's approval.

| Layer | PWA phases (0–4) | Native phases (5–6) |
| --- | --- | --- |
| Frontend | React + TypeScript + Vite, vite-plugin-pwa | React Native + TypeScript via Expo, Expo Router |
| Backend | FastAPI + Pydantic | Same, unchanged |
| Route parsing | gpxpy | Same |
| Weather | Open-Meteo | Same |
| Local storage | IndexedDB | AsyncStorage or expo-sqlite |
| Accounts | Firebase Auth (Google) | + Sign in with Apple |
| Database | PostgreSQL on a $0 host (chosen in 3.1), Alembic | Same |
| Data fetching | TanStack Query + generated API client | Same |
| CI / hosting | GitHub Actions, API on Cloud Run, web on Firebase Hosting | + EAS Build for app binaries |

Detailed per-step checklists, including the full API surface: Step checklists

## Phase 0 — Setup

Goal: a deployed web page on your phone that talks to a deployed API, with tests and deploys automated from the first commit. Effort: about one weekend.

Every checkpoint number in this roadmap is a starting target, not a law; adjust it once you see real data.

**Testing and CI policy, for every phase:** a step is only done when its **Tests** are automated and its **CI** check is running in the GitHub repo and green. Three test layers: unit tests (pytest, Vitest), API integration tests (FastAPI `TestClient`, with external HTTP replayed from recorded responses via respx), and end-to-end tests (Playwright for the PWA, Maestro for the native app). Unit tests never touch the network. Coverage gates in CI: backend ≥ 85% overall and 100% on the rule engine; frontend ≥ 70%. Every bug found later gets a regression test before the fix. Every CI check a step adds becomes a **required status check** on `main`.

**Exit checkpoint:** all six step checkpoints below are met, and a push to `main` reaches production with zero manual steps.

- [ ] **0.1 Repo and tooling.** One monorepo with `api/` and `web/` (later `packages/core/` and `mobile/`).
  - Python managed with uv; the web app with pnpm
  - pre-commit hooks: ruff, mypy, ESLint, Prettier
  - README with the exact commands to run each part locally; a PR template with a checklist (tests added, docs updated)
  - **Tests:** a `make test` (or `just test`) target runs every suite in one command
  - **CI:** `lint` job runs `pre-commit run --all-files`; Dependabot set up for uv, npm and GitHub Actions (weekly); GitHub secret scanning with push protection turned on
  - **Checkpoint:** a fresh clone runs both apps locally in ≤ 3 commands each; pre-commit passes on 100% of files; a commit containing a fake API key is blocked
- [ ] **0.2 FastAPI skeleton.** The base everything else plugs into.
  - App factory, settings via pydantic-settings (`.env` locally, env vars in prod)
  - `/health` returns the app version and git commit SHA
  - CORS restricted to the web app's origins
  - mypy in strict mode; pytest with pytest-cov
  - **Tests:** `/health` returns 200 with version and SHA; settings pick up an env-var override; an allowed origin gets CORS headers and an unknown one doesn't
  - **CI:** `api-test` job: ruff, mypy, pytest with the coverage gate; CodeQL scanning for Python
  - **Checkpoint:** 3 passing tests, 0 mypy errors, 0 CodeQL alerts, `/health` answers in < 50 ms locally
- [ ] **0.3 React app.** Vite + TypeScript (strict), React Router, TanStack Query.
  - One page that calls `/health` and shows the API version
  - Vitest + React Testing Library, with MSW to mock the API; Playwright installed
  - **Tests:** a component test renders the version from a mocked `/health`, and shows an error state when it fails; one Playwright smoke test loads the page against the local API
  - **CI:** `web-test` job: ESLint, `tsc`, Vitest with coverage, production build, and a bundle-size budget (size-limit); `e2e` job starts the API and web app in the runner and runs Playwright; CodeQL for JavaScript/TypeScript
  - **Checkpoint:** 0 type errors, bundle < 200 KB gzipped (enforced by size-limit), 3 passing tests
- [ ] **0.4 Generated API client.** No hand-written API types, ever.
  - A `pnpm gen:api` script that generates TypeScript types and client from FastAPI's `/openapi.json` (openapi-typescript or orval)
  - **Tests:** `tsc` type-checks a file that calls every generated endpoint
  - **CI:** `api-contract` job exports the OpenAPI schema, regenerates the client and runs `git diff --exit-code`; a backend change that alters the API fails until the client is regenerated
  - **Checkpoint:** 0 hand-written request or response types in `web/`; the contract job fails when you break it on purpose
- [ ] **0.5 Deployment.** API as a Docker image on Cloud Run (min instances 0, so it costs \~nothing idle); web app on Firebase Hosting.
  - Production config through environment variables only; secrets in GitHub Environments and Secret Manager, never in the repo
  - GitHub authenticates to GCP with Workload Identity Federation, so there are no long-lived service-account keys
  - **Tests:** post-deploy smoke tests call the live `/health` and run the Playwright smoke test against the live URL
  - **CI/CD:** `deploy-api` workflow builds the image, pushes it to Artifact Registry and deploys a new Cloud Run revision; `deploy-web` deploys to Firebase Hosting; every PR gets a Firebase preview channel URL posted as a comment; if the post-deploy smoke test fails, traffic is routed back to the previous Cloud Run revision automatically
  - **Checkpoint:** both live on HTTPS; on your phone over mobile data the page shows the API response in < 5 s cold and < 1 s warm; a deliberately broken deploy rolls back with no manual step
- [ ] **0.6 Pipeline rules.** Make the repo enforce the process.
  - Branch protection on `main`: PRs only, linear history, all of `lint`, `api-test`, `web-test`, `e2e`, `api-contract` required
  - Path filters so a backend-only change skips web jobs (and vice versa); dependency caching for uv and pnpm; `concurrency` cancels outdated runs on the same PR
  - Release tags (`v0.1.0` style) trigger a changelog via release-please
  - **Tests:** open one PR with a failing test and confirm the merge is blocked
  - **CI:** the required-checks list above, plus a nightly scheduled run of the full suite to catch dependency drift
  - **Checkpoint:** PR pipeline < 5 min; merge to `main` live in < 10 min; 0 ways to push to `main` without green checks

## Phase 1 — MVP core

Goal: upload a GPX, pick a date and start time, get a checklist where every item has a reason. This is the heart of the project. Effort: 3–4 weekends.

**Exit checkpoint:** for 3 GPX files from hikes you've already done, you'd add ≤ 2 items and remove ≤ 2 items per list; all step checkpoints met; backend coverage ≥ 85%.

**Backend (FastAPI)**

- [ ] **1.1 GPX test corpus.** Build the fixtures before the parser, so the parser is written against real files.
  - 10 GPX files from ≥ 4 sources (AllTrails, Komoot, Strava, a watch or your own recordings)
  - Must include: a loop, an out-and-back, a file with no elevation, a file with > 10,000 points, a `<rte>` route (not a `<trk>` track), a multi-segment track, and one malformed file
  - For each, record the reference distance and elevation gain shown by the source app in `expected.json`
  - **Tests:** a fixture-loader test confirms every file has an `expected.json` entry
  - **CI:** fixtures are committed under `api/tests/fixtures/gpx/`; a check fails if a fixture has no expected values
  - **Checkpoint:** 10 files, 7 edge cases covered, 10 reference entries
- [ ] **1.2 GPX parser — `POST /routes/parse`.** GPX in, a `RouteSummary` out.
  - Parse with gpxpy; accept `<trk>` and `<rte>`; merge segments
  - Distance via geodesic distance between points
  - Elevation gain and loss with smoothing (moving average plus a small noise threshold), since raw GPS elevation overstates gain
  - Min/max elevation, high-point coordinates, start and end points
  - Down-sample the track to ≤ 500 points with Ramer–Douglas–Peucker for the frontend
  - Reject files > 10 MB; return 422 with a clear message for invalid GPX
  - **Tests:** parametrised over all 10 fixtures, comparing to `expected.json`; malformed file → 422; oversized file → 413; property-based tests with Hypothesis (distance ≥ 0, gain ≥ 0, reversing a track keeps distance and swaps gain/loss)
  - **CI:** runs in `api-test`; a pytest-benchmark job fails if parsing the largest fixture regresses by > 20%
  - **Checkpoint:** distance within 2% and gain within 10% of reference on all valid fixtures; largest fixture parses in < 2 s; 0 responses with status 500
- [ ] **1.3 Elevation backfill.** If a file has no elevation, look it up from Open-Meteo's elevation API.
  - Batch coordinates (up to 100 per request) and only for the down-sampled points
  - **Tests:** recorded responses via respx; assert the batch count; API timeout → the route is still returned, flagged "elevation unavailable"
  - **CI:** in `api-test`; no live network calls (pytest-socket blocks them)
  - **Checkpoint:** no-elevation fixture gets gain within 15% of its reference; ≤ 5 API calls per route
- [ ] **1.4 Duration estimator.** Tobler's hiking function per segment, times a personal pace factor (default 1.0), plus a rest allowance (e.g. 10 min per hour).
  - Output the estimated time of arrival at every sampled point, which the weather step needs
  - **Tests:** flat route matches the expected speed; uphill and downhill segments match Tobler's curve; pace factor scales total time linearly; zero-length route → 0 duration
  - **CI:** in `api-test`
  - **Checkpoint:** on 5 hikes you've done, after setting your pace factor, the estimate is within ±20% of your real time
- [ ] **1.5 Weather service.** Open-Meteo forecast at the start, the high point, the end, and every \~2 hours of walking on long routes, each at the time you'd be there.
  - Fields: temperature, apparent temperature, wind and gusts, precipitation probability and amount, UV index; daily sunrise and sunset
  - Fetch all sample points in one multi-location request; handle the local timezone
  - Cache by rounded coordinates and hour (TTL 1 hour)
  - Dates beyond the forecast horizon (about 16 days) → a clear "too far ahead" response, not an error
  - **Tests:** recorded responses; correct hour selected for each ETA, including a hike that crosses midnight; cache hit avoids a second call; out-of-range date; Open-Meteo returning 500 → graceful degraded response
  - **CI:** in `api-test`; a separate weekly `live-weather` workflow calls the real API once to detect response-format changes (not a required check)
  - **Checkpoint:** ≤ 1 Open-Meteo call per checklist request; cached repeat < 100 ms
- [ ] **1.6 `TripContext` model.** One Pydantic model combining route stats, timings, weather per point, start time and group options; it's the only input rules see.
  - **Tests:** built from all 10 fixtures without errors; JSON round-trip is lossless
  - **CI:** in `api-test`; mypy strict on the models
  - **Checkpoint:** 10 of 10 fixtures produce a valid context
- [ ] **1.7 Rule engine framework.** The core abstraction.
  - A `Rule` protocol: `id`, `category`, `evaluate(ctx) → list[Item]`
  - `Item`: name, category, priority (must / should / consider), reason text, optional quantity (e.g. 2.5 L water)
  - Rules auto-registered from a `rules/` package; thresholds in a YAML config validated by Pydantic
  - Duplicates merged: highest priority wins, reasons combined
  - A base list that's always included
  - **Tests:** registry discovers a dummy rule; dedupe and priority merging; invalid YAML config fails at startup; every emitted item has a non-empty reason
  - **CI:** in `api-test`, with a 100% coverage gate on `rules/` and the engine
  - **Checkpoint:** adding a rule = 1 new file + 0 engine changes; 30 rules evaluate in < 50 ms
- [ ] **1.8 Starter rules.** At least 12, for example:
  - Water amount from duration × temperature
  - Headlamp if the estimated finish is within 1 hour of sunset
  - Insulating layer from the coldest apparent temperature on the route; windproof layer from gusts
  - Rain shell above a rain-probability threshold
  - Sun hat and sunscreen when the UV index is high
  - Extra food on hikes over a set duration
  - Hiking poles on routes with large elevation gain
  - Heat warning and an earlier start suggestion on hot days
  - First aid kit, phone, ID always
  - **Tests:** ≥ 3 per rule (triggers, doesn't trigger, exactly at the threshold)
  - **CI:** in `api-test`, inside the 100% coverage gate
  - **Checkpoint:** ≥ 12 rules, ≥ 36 rule tests, 100% line coverage on `rules/`
- [ ] **1.9 `POST /checklist`.** Parsed route + date + start time + options in; checklist grouped by category, route summary, weather summary and warnings out (e.g. "you finish 40 min after sunset").
  - **Tests:** 3 end-to-end API tests over fixtures with recorded weather; snapshot tests (syrupy) of the full response, so any change in output shows up in review
  - **CI:** in `api-test`; `api-contract` regenerates the client
  - **Checkpoint:** p95 < 1.5 s uncached and < 300 ms cached; every response field typed in the OpenAPI schema

**Frontend (React)**

- [ ] **1.10 Plan screen.** GPX upload (file picker on mobile, drag-and-drop on desktop), date picker limited to the forecast window, start time, group options.
  - Inline validation and clear errors for bad files
  - **Tests:** component tests for validation and the error states; Playwright: upload a fixture, pick a date, reach the checklist
  - **CI:** `web-test` and `e2e`; the Playwright run also uses a mobile viewport profile
  - **Checkpoint:** from opening the app to the checklist in ≤ 4 taps plus the file pick; works on iOS Safari and Android Chrome
- [ ] **1.11 Route summary.** Distance, gain, estimated duration, finish time vs sunset (highlighted when late), elevation profile chart, weather strip per sample point.
  - **Tests:** component tests with each fixture's API response; visual regression screenshots with Playwright (`toHaveScreenshot`)
  - **CI:** `e2e` fails on unreviewed screenshot changes; Lighthouse CI runs on the preview URL
  - **Checkpoint:** numbers match the API exactly for all fixtures; Lighthouse mobile performance ≥ 85 and LCP < 2.5 s
- [ ] **1.12 Checklist screen.** Grouped by category, priority badges, reason under each item, tap to tick, progress count, "consider" items collapsed by default.
  - **Tests:** tick and untick; progress count; grouping and ordering; every item renders its reason
  - **CI:** `web-test` and `e2e`; axe accessibility checks in Playwright
  - **Checkpoint:** 100% of items show a reason; tick responds in < 100 ms; 0 axe violations

## Phase 2 — A real PWA, tested on the trail

Goal: an installable app that works without signal and that you actually rely on. Effort: about 2 weekends of building, plus 5 hikes of field testing.

**Exit checkpoint:** on the last 3 hikes, 0 missed must-have items and ≤ 2 unnecessary items per hike; duration estimate within ±15% on the last 3 hikes; you used the app for every hike in the phase.

- [ ] **2.1 Installable app.** vite-plugin-pwa: manifest, 192 and 512 px icons plus a maskable icon, theme colour, standalone display; Apple touch icon and iOS meta tags.
  - **Tests:** a unit test validates the generated manifest's required fields
  - **CI:** Lighthouse CI asserts the installability checks pass on every PR preview
  - **Checkpoint:** installs and launches standalone on 1 iPhone and 1 Android phone
- [ ] **2.2 Offline app shell.** Workbox precaches the app shell; an offline screen when an action needs the network.
  - **Tests:** Playwright loads the app, switches the browser context offline, reloads, and expects the app to render
  - **CI:** that offline test runs in `e2e`
  - **Checkpoint:** in airplane mode the installed app opens in < 2 s
- [ ] **2.3 Local persistence.** IndexedDB via Dexie: saved trips (route summary, checklist, weather snapshot, timestamp) and tick state written on every change.
  - Versioned schema with migrations from the first release
  - **Tests:** Vitest with fake-indexeddb for save, load, delete and a schema migration; Playwright: tick items, reload, ticks are still there
  - **CI:** `web-test` and `e2e`
  - **Checkpoint:** after killing the app mid-checklist, 100% of ticks survive; 20 saved trips use < 5 MB
- [ ] **2.4 Forecast refresh with diff.** When online, re-run the checklist for a saved trip and highlight what changed; ticks on unchanged items are kept.
  - **Tests:** a pure diff function unit-tested on 5 scenarios (item added, removed, priority changed, quantity changed, no change); component test of the highlight
  - **CI:** `web-test`
  - **Checkpoint:** all 5 scenarios correct; 0 ticks lost on refresh
- [ ] **2.5 Mobile UX pass.** Tap targets ≥ 44 px, primary actions in the bottom third of the screen, a high-contrast option for bright sun, dark mode.
  - **Tests:** Playwright visual snapshots in light, dark and high-contrast themes; axe checks on every screen
  - **CI:** `e2e`; Lighthouse CI accessibility budget
  - **Checkpoint:** Lighthouse accessibility ≥ 90; 0 tap-target warnings; WCAG AA contrast on all text
- [ ] **2.6 Feedback log.** After a hike: "missing item", "didn't need" and "actual duration" per trip, stored locally and exportable as JSON.
  - **Tests:** component tests for the form; the export produces valid JSON against a schema
  - **CI:** `web-test`
  - **Checkpoint:** logging one hike takes < 2 minutes
- [ ] **2.7 Field testing.** 5 real hikes in varied conditions: hot, cold or windy, long, a near-dark finish, and one with a companion profile you care about (e.g. a kid).
  - After each hike, turn every logged miss into a rule or threshold change
  - **Tests:** each hike's `TripContext` saved as a fixture; a regression test asserts the corrected checklist for it
  - **CI:** those regression tests run in `api-test`, so a later change can't silently undo a fix
  - **Checkpoint:** 5 hikes logged; ≥ 1 regression test per hike; ≤ 1 missed must-have on each of the last 2 hikes
- [ ] **2.8 Duration calibration.** Compare estimated and actual times; update your pace factor and, if needed, the rest allowance.
  - **Tests:** a test over your logged hikes asserts the mean absolute error stays under the target
  - **CI:** in `api-test`
  - **Checkpoint:** estimate within ±15% on the last 3 hikes

## Phase 3 — Accounts and community

Goal: people sign in, keep their trips in the cloud, publish hikes with the packing list they actually used, find other people's hikes in a feed, rate them, and plan their own trip from one. Free to use; an account only for the cloud and community actions. Running cost $0. Effort: 6–8 weekends.

**Exit checkpoint:** a second person on a second account finds your public hike in the feed, rates it, and builds their own checklist from it in ≤ 4 taps after opening it; the privacy tests pass (0 private or unlisted hikes in feed or search, 0 published points inside trimmed route ends, no email in any public response); the month's infrastructure bill is $0.00.

- [ ] **3.1 Community design.** ADRs for auth, the database host ($0: Neon, Supabase or a Raspberry Pi, with the path to Cloud SQL), the data model, privacy and moderation; the API contract; UX and visual specs; privacy policy and terms drafts.
  - **Tests:** none; this is design
  - **CI:** none
  - **Checkpoint:** ADRs accepted and dated; every Phase 3 endpoint in the contract sketch; cost at 100 users estimated at $0 with each free-tier limit and its headroom listed
- [ ] **3.2 API hardening.** `/v1` prefix, rate limiting (slowapi) including per-user limits on writes, structured JSON logs, Sentry for errors, one consistent error schema. Moved from the old optional menu: required once the app takes user content.
  - **Tests:** rate limit returns 429 past the limit; every error type matches the schema; a load test with Locust
  - **CI:** `api-test`; a `load-test` workflow runs Locust against the PR's staging revision before merges to `main`
  - **Checkpoint:** p95 < 1 s at 20 requests/s; 0 unhandled 500s in a week of production logs
- [ ] **3.3 Accounts and database.** Firebase Auth (Google sign-in); FastAPI verifies ID tokens; profile with a unique handle; account deletion; terms accepted at first sign-in; PostgreSQL on the 3.1 host with Alembic migrations.
  - **Tests:** API tests with mocked token verification (valid, expired, wrong project, missing); handle validation; account deletion removes every row the user owns; migration up/down test against a Postgres service container
  - **CI:** `api-test` gains a Postgres service container; a `migrations` job runs Alembic upgrade and downgrade on every PR that touches migrations
  - **Checkpoint:** sign-in in ≤ 3 taps; deleting an account leaves 0 of its rows; a backup restores into a clean database
- [ ] **3.4 Cloud trips and sync.** Trips stored per user; offline-first sync, last write wins per trip; trips saved on a device before signing in can be uploaded.
  - **Tests:** users can't read each other's trips; sync conflict tests
  - **CI:** `api-test`, `web-test`, `migrations`
  - **Checkpoint:** a trip created on the phone appears on the laptop in < 5 s; 10 of 10 offline-edit scenarios sync with 0 lost changes
- [ ] **3.5 Publish a hike.** A snapshot of a saved trip (stats, trimmed route, the packing list as packed, the author's feedback) as private, unlisted or public; route ends trimmed by a pure function.
  - **Tests:** no published point within the trim distance of the true start or end on all fixtures, plus a Hypothesis property test; visibility rules (private 404, unlisted by link only); only the author edits or unpublishes
  - **CI:** `api-test`, `web-test`, `e2e`
  - **Checkpoint:** publishing from a saved trip in ≤ 3 taps; 0 published points inside trimmed ends on all 10 fixtures
- [ ] **3.6 Feed and hike page.** Public feed with cursor pagination, area and length filters, recent or top; a public hike page and profile page viewable signed out.
  - **Tests:** pagination with no duplicates or gaps under inserts; filters; private, unlisted, hidden and blocked content never appears; component tests; Playwright: signed out, feed → hike page
  - **CI:** `api-test`, `web-test`, `e2e` (axe on the new screens)
  - **Checkpoint:** feed p95 < 500 ms with 1,000 seeded hikes; first feed page in < 2 s on your phone over mobile data
- [ ] **3.7 Ratings.** 1–5 stars, one per user per hike, not on your own; average and count; "top" sorted by a Bayesian average.
  - **Tests:** upsert, own-hike 403, signed-out 401, invalid stars 422; Bayesian average on fixed examples and a property test
  - **CI:** `api-test`, `web-test`
  - **Checkpoint:** rating takes 1 tap from the hike page; averages correct in every test scenario
- [ ] **3.8 Plan this hike.** A fresh checklist for your date and forecast from a published route, with the author's "missing" and "didn't need" notes merged in by a pure function; saved on the device or synced.
  - **Tests:** uses the planner's date and weather; author notes appear with their reason; private or unpublished hike 404; merge function on 5 scenarios; Playwright: hike page → plan → checklist
  - **CI:** `api-test`, `web-test`, `e2e`
  - **Checkpoint:** hike page to your own checklist in ≤ 4 taps; 100% of author-flagged items shown with their reason
- [ ] **3.9 Safety and moderation.** Report, auto-hide at 3 distinct reporters, block, an admin queue for the manager, suspend; privacy policy and terms pages.
  - **Tests:** hidden content gone for everyone but the author and admins; block both ways; admin endpoints 403 for everyone else; suspended users can't write; auto-hide threshold counts distinct users
  - **CI:** `api-test`, `web-test`, `e2e`
  - **Checkpoint:** a report reaches the admin queue in < 1 min; hiding takes effect in the feed in < 1 min; every App Store 1.2 / Google Play UGC requirement ticked in `docs/ugc-compliance.md`

## Phase 4 — Extend, then decide on native

Goal: the features that make it more than a checklist, and a written go/no-go on native. Treat 4.1–4.5 as a menu; only 4.6 is required. Effort: open-ended, 2–5 weekends depending on picks.

**Exit checkpoint:** the decision document in 4.6 exists and is dated; every menu item you chose meets its checkpoint.

- [ ] **4.1 Saved trips and history.** Trip list with search, and "same hike, new date" duplication.
  - **Tests:** component tests for search and duplicate; Playwright: re-plan a saved trip
  - **CI:** `web-test` and `e2e`
  - **Checkpoint:** re-planning a past hike takes ≤ 3 taps
- [ ] **4.2 Gear inventory.** Your actual gear with weights, mapped to generic items ("rain shell" → your jacket); the checklist shows your names and total pack weight.
  - **Tests:** mapping and fallback when no gear matches; weight totals including quantities
  - **CI:** `api-test` and `web-test`
  - **Checkpoint:** ≥ 80% of checklist items map to your own gear; computed pack weight within 5% of your packed bag on a scale
- [ ] **4.3 Group profiles.** Kid (extra layers, snacks, slower pace factor), dog (water for the dog, leash, heat warning for paws), solo (share your route with someone).
  - **Tests:** ≥ 3 tests per profile-specific rule; pace factor applied to the duration
  - **CI:** `api-test`, inside the rules coverage gate
  - **Checkpoint:** ≥ 3 profile-specific rules per profile, all tested
- [ ] **4.4 Trail search from OpenStreetMap.** Search hiking route relations by name or near a location via the Overpass API; convert results into the same `RouteSummary` as GPX.
  - **Tests:** recorded Overpass responses; conversion of relations with gaps or unordered ways
  - **CI:** `api-test`; the weekly live-API workflow also queries Overpass once
  - **Checkpoint:** finds ≥ 8 of 10 known hikes in your region by name; results in < 3 s
- [ ] **4.5 Water sources.** OSM drinking-water and spring nodes within 100 m of the route; the water rule uses the longest stretch without a source.
  - **Tests:** distance-to-route calculation; water rule with and without sources on fixture routes
  - **CI:** `api-test`
  - **Checkpoint:** lists the known water sources correctly on 3 routes you know
- [ ] **4.6 Decision gate: go native?** A one-page document listing each feature you want next and whether a PWA can do it. Include community features (e.g. push when your hike is rated). Native is justified if ≥ 1 must-have can't be done as a PWA (e.g. background GPS, reliable iOS notifications, offline maps, a store listing).
  - **Tests:** none; this is a decision
  - **CI:** none
  - **Checkpoint:** the document exists, every candidate feature is marked PWA yes/no, and the decision is dated

## Phase 5 — Migrate to React Native (Expo)

Goal: the same app, native, at parity with the PWA. The backend doesn't change at all. Effort: 3–4 weekends.

**Exit checkpoint:** parity table 100% green; all PWA end-to-end flows have Maestro equivalents passing in CI; used on 2 real hikes.

What carries over and what gets rewritten:

| Carries over as is | Gets rewritten |
| --- | --- |
| The whole FastAPI backend and rule engine | Components: `<View>`, `<Text>`, `<Pressable>` instead of HTML elements |
| Generated TypeScript API client and types | Styling: StyleSheet or NativeWind instead of CSS |
| Data hooks and TanStack Query setup | Navigation: Expo Router instead of React Router |
| State management (e.g. Zustand) | File picking: expo-document-picker for GPX |
| Checklist and formatting logic, if kept out of components | Storage: AsyncStorage or expo-sqlite instead of IndexedDB |
|  | Charts: a React Native chart library for the elevation profile |

- [ ] **5.0 Extract shared code (in the PWA, before any native work).** Move the API client, types, data hooks, the sync engine, the trip-diff function and formatters into `packages/core`, with no DOM or browser imports.
  - **Tests:** core's unit tests move with it; the web app's full suite still passes
  - **CI:** new `core-test` job; an ESLint rule fails the build on any `react-dom`, `window` or `document` import in `packages/core`
  - **Checkpoint:** 0 DOM imports in core; web test suite 100% green after the move
- [ ] **5.1 Expo app scaffold.** `mobile/` with Expo + TypeScript and Expo Router, linked to `packages/core` in the workspace; environment config per build profile (development, preview, production).
  - **Tests:** Jest with React Native Testing Library set up; one test renders the home screen with a mocked `/health`
  - **CI:** `mobile-test` job: ESLint, `tsc`, Jest; `expo-doctor` checks dependency compatibility
  - **Checkpoint:** the app runs on your phone through Expo Go and shows the deployed API's version
- [ ] **5.2 Data layer.** TanStack Query with core's hooks; trips stored in expo-sqlite (or AsyncStorage) behind the same repository interface the PWA uses.
  - **Tests:** the shared repository contract tests run against both the IndexedDB and SQLite implementations
  - **CI:** `core-test` and `mobile-test`
  - **Checkpoint:** 100% of core hooks reused unchanged; trips persist across app restarts
- [ ] **5.3 Plan screen.** expo-document-picker for GPX (accept `*/*` and validate by content, since Android often reports GPX files with the wrong MIME type); native date and time pickers.
  - **Tests:** component tests; a Maestro flow: pick a fixture file, choose a date, reach the checklist
  - **CI:** `mobile-test`; an `e2e-mobile` workflow runs Maestro flows on an Android emulator in GitHub Actions
  - **Checkpoint:** picks GPX from Files and Downloads on both iOS and Android; all 10 fixtures accepted
- [ ] **5.4 Route summary screen.** Elevation chart with a React Native chart library; weather strip.
  - **Tests:** component tests per fixture response; Maestro screenshot of the screen
  - **CI:** `mobile-test` and `e2e-mobile`
  - **Checkpoint:** numbers identical to the PWA for all fixtures; scrolling at 60 fps on your phone
- [ ] **5.5 Checklist screen.** FlatList, tick with haptic feedback, same grouping and reasons as the PWA.
  - **Tests:** tick, untick, progress count; Maestro: tick items, kill the app, reopen, ticks still there
  - **CI:** `mobile-test` and `e2e-mobile`
  - **Checkpoint:** 40-item list scrolls at 60 fps; tick < 100 ms; 100% of ticks survive an app kill
- [ ] **5.6 Trip migration from the PWA.** Export trips from the PWA as JSON and import them in the app (signed-in users get their trips by sync from 3.4; import covers trips saved on a device while signed out).
  - **Tests:** import validates against the same JSON schema as the export; round-trip test
  - **CI:** `core-test`
  - **Checkpoint:** 100% of your PWA trips import correctly
- [ ] **5.7 Sign-in and community screens.** Google and Sign in with Apple through Firebase Auth; feed, hike page, publish, rate, "Plan this hike", report and block, account menu with deletion; hike links open in the app.
  - **Tests:** component tests for every screen state; sign-in with the auth module mocked; Maestro: feed → hike → plan → checklist, and report a hike
  - **CI:** `mobile-test` and `e2e-mobile`
  - **Checkpoint:** every Phase 3 community flow has a native equivalent; hike links open the app on iOS and Android
- [ ] **5.8 Parity check and development build.** EAS development build on your phone; a parity table listing every PWA feature.
  - **Tests:** every PWA Playwright flow has a matching Maestro flow
  - **CI:** EAS Build runs on merges to `main` (preview profile); `e2e-mobile` becomes a required check
  - **Checkpoint:** parity table 100% green; native app used on 2 real hikes

## Phase 6 — Native features and release

Goal: use what native unlocks, then ship to the stores. 6.2–6.4 are optional. Effort: 3–5 weekends, plus store review time.

**Exit checkpoint:** live in ≥ 1 store; crash-free sessions ≥ 99% in the first month; every release goes out through CI with no manual build steps.

- [ ] **6.1 Evening-before reminder.** A local notification the evening before a planned hike; a scheduled backend job (Cloud Scheduler) re-runs the checklist with the fresh forecast and sends a push through Expo's push service only if the list changed.
  - **Tests:** API tests for the scheduling job (changed vs unchanged list, deleted trip, expired push token); mobile tests for notification scheduling with the module mocked
  - **CI:** `api-test` and `mobile-test`; the scheduler job's container deploys through the existing `deploy-api` workflow
  - **Checkpoint:** reminder arrives within ±5 minutes of schedule; push sent only when the list changed, in 5 of 5 test scenarios
- [ ] **6.2 Map view (optional).** Route line on a map (react-native-maps or MapLibre) with the high point and water sources marked.
  - **Tests:** component test that the route converts to map coordinates correctly; Maestro screenshot
  - **CI:** `mobile-test` and `e2e-mobile`
  - **Checkpoint:** route renders for all 10 fixtures; map ready in < 2 s
- [ ] **6.3 Offline map tiles (optional).** Download a tile pack for the route's bounding box when a trip is saved.
  - **Tests:** bounding-box and pack-size calculations; Maestro: open a saved trip in airplane mode
  - **CI:** `mobile-test` and `e2e-mobile`
  - **Checkpoint:** map visible offline for saved trips; tile pack ≤ 50 MB for a typical day hike
- [ ] **6.4 On-trail pace tracking (optional).** Background location compares progress with the plan and warns if the projected finish slips past sunset.
  - **Tests:** the projection logic tested on recorded tracks (on pace, behind, stopped); permission-denied path
  - **CI:** `core-test` for the projection logic; `mobile-test`
  - **Checkpoint:** correct warning in 3 of 3 recorded-track simulations; battery use ≤ 5% per hour of tracking
- [ ] **6.5 Release pipeline and beta.** EAS Build and EAS Submit from GitHub Actions: preview builds on every merge to `main`, production builds on version tags; Sentry for crash reporting with source maps uploaded by CI; EAS Update for JavaScript-only fixes.
  - **Tests:** the full Jest and Maestro suites gate every build
  - **CI/CD:** `release-mobile` workflow on tags: tests → EAS Build → EAS Submit to TestFlight and Google Play internal testing; version numbers bumped automatically from the tag
  - **Checkpoint:** a tag produces store-ready builds with 0 manual steps; ≥ 5 testers for 2 weeks; crash-free sessions ≥ 99%
- [ ] **6.6 Store preparation.** Listings, screenshots, privacy policy (location, files, account, published hikes), user-generated-content requirements (report, block, moderation — built in 3.9), Google Play data-safety form, Apple privacy labels; developer accounts (Apple annual fee, Google one-time fee).
  - **Tests:** Maestro flows capture the store screenshots, so they're reproducible
  - **CI:** a `screenshots` workflow regenerates them on demand
  - **Checkpoint:** submission accepted by ≥ 1 store, with ≤ 2 review rejections
- [ ] **6.7 Release and PWA decision.** Publish, then decide whether the PWA stays as the web version or is retired.
  - **Tests:** a post-release smoke flow on a store-installed build
  - **CI:** release-please generates the changelog and store release notes from merged PRs
  - **Checkpoint:** live in ≥ 1 store; PWA decision recorded in the repo

## CI/CD at a glance

By the end of Phase 6, the repo runs these automated checks. Required checks block merges to `main`.

| Workflow / job | Runs on | What it checks or does | Added in | Required |
| --- | --- | --- | --- | --- |
| `lint` | Every PR | pre-commit: ruff, mypy, ESLint, Prettier | 0.1 | Yes |
| Dependabot, secret scanning | Weekly / every push | Dependency updates; blocks committed secrets | 0.1 | — |
| `api-test` | PRs touching `api/` | mypy, pytest, coverage gates (85% overall, 100% rules), no network | 0.2 | Yes |
| CodeQL | Every PR, weekly | Security scanning for Python and TypeScript | 0.2–0.3 | Yes |
| `web-test` | PRs touching `web/` or `packages/` | ESLint, `tsc`, Vitest, coverage, bundle-size budget | 0.3 | Yes |
| `e2e` | Every PR | Playwright flows, offline test, visual snapshots, axe | 0.3 | Yes |
| `api-contract` | Every PR | Generated client matches the OpenAPI schema | 0.4 | Yes |
| `deploy-api`, `deploy-web` | Merge to `main` | Build, deploy, smoke test, automatic rollback | 0.5 | — |
| PR previews | Every PR | Firebase preview URL; Lighthouse CI on it | 0.5, 1.11 | Yes (Lighthouse budgets) |
| Nightly full run | Schedule | Entire suite against fresh dependencies | 0.6 | — |
| Parser benchmark | PRs touching `api/` | Fails on > 20% parse-time regression | 1.2 | Yes |
| `live-weather` | Weekly | Real Open-Meteo and Overpass calls, to catch format changes | 1.5, 4.4 | No |
| `migrations` | PRs touching the database | Alembic upgrade and downgrade on Postgres | 3.3 | Yes |
| `load-test` | Before merge to `main` | Locust against the staging revision | 3.2 | Yes |
| `core-test` | PRs touching `packages/core` | Shared logic tests; no DOM imports | 5.0 | Yes |
| `mobile-test` | PRs touching `mobile/` | ESLint, `tsc`, Jest, `expo-doctor` | 5.1 | Yes |
| `e2e-mobile` | PRs touching `mobile/` or `core` | Maestro flows on an Android emulator | 5.3 | Yes (from 5.8) |
| EAS preview build | Merge to `main` | Installable preview build | 5.8 | — |
| `release-mobile` | Version tag | Tests → EAS Build → EAS Submit to beta tracks | 6.5 | — |
| release-please | Merge to `main` | Changelog, version bumps, release notes | 0.6 | — |

## Making the migration cheap, and the risks

Decisions to make from day one so Phase 5 stays small:

- Keep every decision (durations, weather lookups, rules) on the server; the frontend never calculates what to pack
- Share types through the generated OpenAPI client instead of hand-written interfaces
- Put data fetching and state in hooks, separate from components; hooks port to React Native unchanged
- Prefer libraries that work in both (TanStack Query, Zustand, date-fns); keep web-only libraries inside components

| Risk | Mitigation |
| --- | --- |
| The checklist feels generic, so the app adds little | Field-test early (Phase 2); every item must show a route- or weather-based reason |
| Rule thresholds are wrong for real conditions | Keep thresholds in config and tune them after each test hike |
| Messy GPX files (routes vs tracks, no elevation, huge files) | Normalise in the parser; fill elevation from an elevation API; test with exports from several apps |
| Weather API terms | Open-Meteo's free tier is for non-commercial use; check its terms and pricing before any public release |
| iOS PWA limits surprise you | Test the installed PWA on an iPhone early in Phase 2 |
| Scope creep in Phase 4 | Treat Phase 4 as a menu; the decision gate is the only required item |
| Scope creep in the community (Phase 3) | The feature set is fixed: publish, feed, ratings, plan from a hike, report/block. Follows, comments, photos, messages and social notifications stay out until the manager adds them |
| Published routes reveal where people live | Private by default; route ends trimmed by a tested pure function; no timestamps or email in public responses |
| Abuse or unsafe content in a public feed | Report, auto-hide, block and an admin queue (3.9) before anyone else can see the feed; the app stores require them anyway |
| Free tiers run out or change terms | Cost rule: $0 by default; free-tier limits and headroom tracked in the 3.1 database ADR; GCP budget alert; moving to Cloud SQL is a connection-string change |
| Weather API terms with a public community | Open-Meteo's free tier is non-commercial; the app stays free. Re-check before any paid feature |
