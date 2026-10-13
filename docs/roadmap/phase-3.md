# Phase 3 — Extend and decide checklist

3.1–3.7 are a menu: pick what you want. 3.8 is required. If you skip 3.2 (accounts), the trip endpoints aren't needed and 3.1 stays client-side only.

## 3.1 Saved trips and history

- [ ] `/trips` list: name, date, distance, status (upcoming / past), sorted upcoming first
- [ ] Search by name; filter upcoming / past
- [ ] "Same hike, new date" → copies route and options, opens `/plan` prefilled with today's date
- [ ] If accounts exist: `POST /v1/trips/{trip_id}/duplicate` returns the new trip
- [ ] Test: search and filter logic
- [ ] Test: duplicate copies route and options but not ticks or feedback
- [ ] Playwright: duplicate a saved trip and build its checklist
- [ ] Count taps to re-plan (≤ 3)

## 3.2 Accounts and sync (optional)

**Auth**

- [ ] Firebase Auth with Google sign-in in the web app
- [ ] `app/auth.py`: FastAPI dependency verifying the Firebase ID token (firebase-admin), returning `CurrentUser`
- [ ] `GET /v1/me` → `{user_id, email, display_name, created_at}`
- [ ] Signed-out mode keeps working exactly as in Phase 2
- [ ] Tests: valid token, expired token, wrong project, missing header → 200 / 401 / 401 / 401

**Database**

- [ ] Cloud SQL Postgres instance (smallest tier); connection via the Cloud Run connector; password in Secret Manager
- [ ] SQLAlchemy 2.0 async models: `users`, `trips`, `feedback`, plus `gear`, `profiles` if 3.3 / 3.4 chosen
- [ ] `trips` columns: `id` (uuid), `user_id`, `name`, `date`, `start_time`, `options` (jsonb), `route` (jsonb), `checklist` (jsonb), `ticks` (jsonb), `rules_version`, `created_at`, `updated_at`, `deleted_at` (soft delete for sync)
- [ ] Alembic initialised; first migration
- [ ] Local Postgres via `docker compose` for development

**Endpoints**

- [ ] `GET /v1/trips` (paginated, `?updated_since=`)
- [ ] `POST /v1/trips`
- [ ] `GET /v1/trips/{trip_id}`
- [ ] `PUT /v1/trips/{trip_id}` (with `updated_at` for conflict detection)
- [ ] `DELETE /v1/trips/{trip_id}` (soft delete)
- [ ] `POST /v1/trips/{trip_id}/refresh` → new checklist + server-side diff
- [ ] `POST /v1/sync` — request: `{cursor, changes[]}`; response: `{cursor, changes[], conflicts[]}`; last write wins per trip by `updated_at`

**Client**

- [ ] Sync engine in the web app: local changes queued in Dexie, pushed on reconnect and on app focus
- [ ] Sign-in screen and account menu; sign-out clears synced data from the device
- [ ] Tests: user A can't read, update or delete user B's trip (403/404)
- [ ] Tests: sync — 10 scenarios (create offline, edit offline on two devices, delete vs edit, etc.)
- [ ] Tests: Alembic upgrade head → downgrade base → upgrade head on a clean Postgres
- [ ] CI: Postgres service container in `api-test`
- [ ] CI: `migrations` job (required when `api/migrations/**` changes)
- [ ] CI: deploy runs `alembic upgrade head` before shifting traffic
- [ ] Verify: phone → laptop sync < 5 s

## 3.3 Gear inventory

- [ ] `GearItem` model: `id`, `name`, `generic_key` (matches a rule item `key`), `weight_g`, `notes`
- [ ] `GET /v1/gear`, `POST /v1/gear`, `PUT /v1/gear/{gear_id}`, `DELETE /v1/gear/{gear_id}` (or Dexie-only if no accounts)
- [ ] `/gear` screen: list, add, edit, delete; pick the generic item from a dropdown of known keys
- [ ] Checklist shows your gear name under the generic name when mapped
- [ ] Pack weight total (quantities included; water counted at 1 kg/L)
- [ ] Unmapped items listed so you can add gear for them
- [ ] Tests: mapping, multiple gear for one key (pick the default), unmapped fallback
- [ ] Tests: weight total with quantities
- [ ] Verify: ≥ 80% of a typical checklist maps; weigh your packed bag and compare (within 5%)

## 3.4 Group profiles

- [ ] Extend `TripOptions`: `kids: list[{age_years}]`, `dog: bool`, `solo: bool`, `pace_factor: float`
- [ ] `GET /v1/profiles`, `PUT /v1/profiles` — stored defaults (or Dexie-only)
- [ ] Kid rules: extra layer, extra snacks, comfort item, slower pace factor by age
- [ ] Dog rules: extra water for the dog, bowl, leash, paw-heat warning above a temperature
- [ ] Solo rules: share your route and ETA with someone, emergency whistle/beacon
- [ ] Plan screen: profile toggles prefilled from defaults
- [ ] Tests: ≥ 3 per rule (triggers / doesn't / threshold); pace factor reaches the duration estimate

## 3.5 Trail search from OpenStreetMap

- [ ] `app/trails/overpass.py` — Overpass client with timeout and a polite User-Agent
- [ ] Query hiking relations (`route=hiking`) by name within a bounding box, or near a point
- [ ] Assemble ways into one ordered line; handle gaps and reversed ways
- [ ] Convert to `RouteSummary` (elevation via 1.3 backfill)
- [ ] `GET /v1/trails/search?q=&lat=&lon=&radius_km=` → list of `{osm_relation_id, name, distance_m, from, to}`
- [ ] `GET /v1/trails/{osm_relation_id}` → `RouteSummary`
- [ ] Cache results (24 h) to respect Overpass usage policy
- [ ] Search UI on `/plan` as an alternative to GPX upload; use device location if permitted
- [ ] Tests: recorded Overpass responses; way assembly with gaps and reversed ways; empty results
- [ ] Add one Overpass call to the weekly `live-weather` workflow (rename it `live-apis`)
- [ ] Verify: ≥ 8 of 10 known regional hikes found by name; < 3 s
- [ ] Attribution: "© OpenStreetMap contributors" shown wherever OSM data appears

## 3.6 Water sources

- [ ] Overpass query: `amenity=drinking_water`, `natural=spring`, `man_made=water_tap` within the route's bounding box
- [ ] Keep sources within 100 m of the route; compute each one's distance along the route
- [ ] Add `water_sources: list[{lat, lon, kind, dist_along_m}]` and `longest_dry_stretch_m` to `RouteSummary`
- [ ] Water rule uses the longest dry stretch instead of total time when sources exist
- [ ] Show sources on the elevation profile as markers
- [ ] Tests: point-to-line distance; along-route distance; dry-stretch calculation
- [ ] Tests: water rule with and without sources
- [ ] Verify on 3 routes you know

## 3.7 API hardening

- [ ] All public routes under `/v1` (already the case) with a router-level prefix
- [ ] slowapi rate limits: e.g. 30/min per IP for `/v1/checklist`, 10/min for `/v1/routes/parse`
- [ ] Consistent `ErrorResponse` for 4xx and 5xx, including validation errors
- [ ] Structured JSON logs with request ID, user ID (if any), latency
- [ ] Sentry SDK for API and web; release = git SHA; source maps uploaded from CI
- [ ] Cloud Run: staging service (`api-staging`) deployed from PRs with the `deploy` label
- [ ] Locust scenario: parse + checklist mix at 20 requests/s for 2 minutes
- [ ] Tests: 429 after the limit; every error path matches `ErrorResponse`
- [ ] CI: `load-test` workflow against staging; fails if p95 ≥ 1 s
- [ ] Verify: a week of production logs with 0 unhandled 500s

## 3.8 Decision gate: go native?

- [ ] `docs/decisions/0001-native-app.md` (ADR format)
- [ ] List every wanted next feature
- [ ] For each: can a PWA do it on iOS and Android? (yes / partly / no, with reason)
- [ ] Mark which are must-haves
- [ ] Decision: go native if ≥ 1 must-have is "no"
- [ ] Date and commit the decision
