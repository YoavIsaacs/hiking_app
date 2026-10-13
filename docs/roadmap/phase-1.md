# Phase 1 — MVP core checklist

Backend code lives under `api/app/`: `routes/` (GPX), `weather/`, `timing/`, `rules/`, `routers/`, `models/`. Tests mirror it under `api/tests/`.

## 1.1 GPX test corpus

- [ ] `api/tests/fixtures/gpx/` folder
- [ ] Fixture: loop hike (any source)
- [ ] Fixture: out-and-back hike
- [ ] Fixture: export from AllTrails
- [ ] Fixture: export from Komoot
- [ ] Fixture: export from Strava
- [ ] Fixture: your own watch or phone recording
- [ ] Fixture: file with no `<ele>` tags (strip them from a copy if needed)
- [ ] Fixture: file with > 10,000 track points
- [ ] Fixture: `<rte>` route instead of `<trk>`
- [ ] Fixture: multi-segment `<trk>` (pause/resume)
- [ ] Fixture: malformed XML (truncated file)
- [ ] Fixture: valid XML but not GPX (e.g. a KML file)
- [ ] `expected.json`: per file — source app, reference distance (m), reference gain (m), whether it has elevation, expected error (for invalid files)
- [ ] `tests/fixtures/loader.py` — helper returning `(path, expected)` pairs for parametrisation
- [ ] Test: every `.gpx` file has an `expected.json` entry, and vice versa
- [ ] Note any files containing your home location; trim the start/end or use routes that don't

## 1.2 GPX parser — `POST /v1/routes/parse`

**Models** (`app/models/route.py`)

- [ ] `TrackPoint`: `lat`, `lon`, `elev_m: float | None`, `dist_m` (cumulative)
- [ ] `LatLonElev`: `lat`, `lon`, `elev_m`
- [ ] `RouteSummary`: `name`, `distance_m`, `gain_m`, `loss_m`, `min_elev_m`, `max_elev_m`, `high_point: LatLonElev`, `start: LatLonElev`, `end: LatLonElev`, `is_loop: bool`, `points: list[TrackPoint]` (≤ 500), `has_elevation`, `elevation_source` (`file` / `lookup` / `none`), `source_format` (`trk` / `rte`), `point_count_original`
- [ ] `ErrorResponse`: `code`, `message`, `detail` (shared by all endpoints)

**Logic** (`app/routes/`)

- [ ] `parse_gpx(bytes) → RawTrack` with gpxpy; prefer `<trk>`, fall back to `<rte>`
- [ ] Merge all segments in order; drop consecutive duplicate points
- [ ] Reject a file with < 2 points (422 `too_few_points`)
- [ ] `geodesic_distance()` between consecutive points (geographiclib or haversine; pick one and document it)
- [ ] `smooth_elevation()` — moving-average window (configurable, e.g. 5 points)
- [ ] `gain_loss()` — accumulate only changes beyond a noise threshold (configurable, e.g. 3 m)
- [ ] `is_loop` — start and end within a threshold (e.g. 200 m)
- [ ] `simplify()` — Ramer–Douglas–Peucker until ≤ 500 points; always keep start, end and high point
- [ ] Name from GPX metadata, else from the filename

**Endpoint** (`app/routers/routes.py`)

- [ ] `POST /v1/routes/parse`, multipart field `file`
- [ ] Size check before parsing: > 10 MB → 413 `file_too_large`
- [ ] Invalid XML or not GPX → 422 `invalid_gpx`
- [ ] All parsing exceptions mapped to `ErrorResponse`; nothing escapes as 500
- [ ] Response model declared so the OpenAPI schema is fully typed

**Tests** (`tests/routes/`)

- [ ] Parametrised: distance within 2% of reference for each valid fixture
- [ ] Parametrised: gain within 10% for each fixture with elevation
- [ ] Malformed file → 422; KML file → 422; 11 MB file → 413; 1-point file → 422
- [ ] `<rte>` fixture parses with `source_format = rte`
- [ ] Multi-segment fixture distance doesn't include the jump between segments (if that's your chosen behaviour — decide and test it)
- [ ] `simplify()` output ≤ 500 points and keeps start, end, high point
- [ ] Loop fixture `is_loop = true`; out-and-back `is_loop = true`; one-way route `false`
- [ ] Hypothesis: random tracks → distance ≥ 0, gain ≥ 0, loss ≥ 0
- [ ] Hypothesis: reversed track → same distance, gain and loss swapped
- [ ] Endpoint tests through `TestClient` for 200, 413, 422
- [ ] pytest-benchmark on the largest fixture

**CI**

- [ ] `api-test` runs the new tests
- [ ] Benchmark job stores the baseline (github-action-benchmark) and fails on > 20% regression
- [ ] Regenerate the client; `api-contract` green

## 1.3 Elevation backfill

- [ ] `app/routes/elevation.py` — `ElevationClient` wrapping Open-Meteo's elevation endpoint
- [ ] Batch coordinates in groups of ≤ 100
- [ ] Only look up the simplified points, then recompute gain/loss on them
- [ ] httpx `AsyncClient` with a timeout (e.g. 5 s) and 1 retry
- [ ] On failure: return the route with `has_elevation = false`, `elevation_source = none`, and a warning
- [ ] Settings: elevation base URL, timeout
- [ ] Recorded response fixtures in `tests/fixtures/http/elevation/`
- [ ] Test: no-elevation fixture gets gain within 15% of reference
- [ ] Test: 250 points → exactly 3 requests
- [ ] Test: timeout → route returned, flagged, no 500
- [ ] Test: file that already has elevation → 0 requests
- [ ] Confirm pytest-socket blocks any accidental live call

## 1.4 Duration estimator

- [ ] `app/timing/tobler.py` — `speed_kmh(slope)` per Tobler's function
- [ ] `estimate(route, start_time, pace_factor, rest_min_per_hour) → Timing`
- [ ] `Timing` model: `start`, `finish`, `moving_min`, `total_min`, `eta_by_point: list[datetime]`
- [ ] Use the simplified points; clamp extreme slopes caused by GPS noise
- [ ] Rest allowance added proportionally along the route
- [ ] Defaults in settings: pace factor 1.0, rest 10 min/hour
- [ ] Test: flat 5 km → expected time from Tobler at 0% slope
- [ ] Test: steep uphill slower than flat; gentle downhill faster; steep downhill slower
- [ ] Test: pace factor 1.5 → moving time × 1.5
- [ ] Test: ETAs strictly increasing; first = start time; last = finish
- [ ] Test: zero-distance route → 0 minutes
- [ ] Spreadsheet or notes: your actual times for 5 past hikes, for the checkpoint

## 1.5 Weather service

**Models**

- [ ] `WeatherPoint`: `label` (start / high point / end / waypoint N), `lat`, `lon`, `eta`, `temp_c`, `apparent_temp_c`, `wind_kmh`, `gust_kmh`, `precip_prob_pct`, `precip_mm`, `uv_index`
- [ ] `DaylightInfo`: `sunrise`, `sunset`
- [ ] `WeatherSummary`: `points`, `daylight`, `min_apparent_temp_c`, `max_temp_c`, `max_gust_kmh`, `max_precip_prob_pct`, `max_uv`, `forecast_issued_at`

**Logic** (`app/weather/`)

- [ ] Choose sample points: start, high point, end, plus one every \~2 hours of walking
- [ ] One multi-location Open-Meteo request with hourly and daily fields
- [ ] Timezone handled from the forecast response; ETAs converted consistently
- [ ] Pick the hourly value nearest each ETA (handle hikes crossing midnight)
- [ ] Forecast horizon check → `ForecastUnavailable` with a friendly message
- [ ] Cache keyed by rounded coordinates + date (in-memory TTL cache, 1 hour)
- [ ] Degraded mode: Open-Meteo down → checklist built without weather rules, plus a warning

**Tests**

- [ ] Recorded responses: hot day, cold windy day, rainy day, high-UV day
- [ ] Correct hour picked for each ETA; midnight-crossing case
- [ ] Second identical request hits the cache (0 extra HTTP calls)
- [ ] Date beyond the horizon → `ForecastUnavailable`
- [ ] Open-Meteo 500 / timeout → degraded mode
- [ ] Summary maxima and minima computed correctly

**CI**

- [ ] `.github/workflows/live-weather.yml` — weekly, one real call, validates the response parses into the models; not a required check

## 1.6 `TripContext` model

- [ ] `TripOptions`: `group_size`, `with_kids`, `with_dog` (later phases add more)
- [ ] `TripContext`: `route: RouteSummary`, `timing: Timing`, `weather: WeatherSummary | None`, `options: TripOptions`, `date`
- [ ] Builder: `build_context(route, date, start_time, options)` calls timing and weather
- [ ] Test: builds for all 10 valid fixtures (weather mocked)
- [ ] Test: JSON round-trip equals the original
- [ ] mypy strict passes on `models/`

## 1.7 Rule engine framework

- [ ] `Priority` enum: `must`, `should`, `consider`
- [ ] `Category` enum: water, food, clothing, navigation, safety, sun, gear, documents
- [ ] `Item`: `key` (stable id), `name`, `category`, `priority`, `reasons: list[str]`, `quantity: float | None`, `unit: str | None`
- [ ] `Rule` protocol: `id`, `description`, `evaluate(ctx, cfg) → list[Item]`
- [ ] Registry: auto-imports every module in `app/rules/` and collects rules
- [ ] `rules.yaml` thresholds; Pydantic model validating it at startup (bad config = app refuses to start)
- [ ] Merge step: same `key` → highest priority, largest quantity, all reasons kept
- [ ] Base list (`base.py`): items that always appear
- [ ] Sort: by category order, then priority, then name
- [ ] `GET /v1/rules` — rule ids, descriptions and current thresholds
- [ ] Test: registry finds a dummy rule placed in a temp package
- [ ] Test: merge keeps highest priority and combines reasons
- [ ] Test: invalid YAML (wrong type, missing key) fails at startup
- [ ] Test: no item ever has an empty reasons list (checked across all fixtures)
- [ ] Test: 30 dummy rules evaluate in < 50 ms
- [ ] CI: coverage gate 100% on `app/rules/` (`--cov-fail-under` per package via a second coverage run or coverage config)

## 1.8 Starter rules (one file each in `app/rules/`)

- [ ] `water.py` — litres from total time × temperature band; quantity rounded to 0.5 L
- [ ] `headlamp.py` — finish within 60 min of sunset, or start before sunrise
- [ ] `insulation.py` — insulating layer below an apparent-temperature threshold
- [ ] `wind.py` — windproof layer above a gust threshold
- [ ] `rain.py` — rain shell above a rain-probability threshold; "must" above a higher one
- [ ] `sun.py` — sun hat and sunscreen above a UV threshold
- [ ] `food.py` — snacks always; extra food beyond a duration threshold
- [ ] `poles.py` — trekking poles above a gain threshold
- [ ] `heat.py` — warning + earlier start suggestion above a temperature threshold
- [ ] `long_day.py` — power bank and offline map on hikes beyond a duration threshold
- [ ] `navigation.py` — offline map / downloaded GPX always
- [ ] `base.py` — first aid kit, phone, ID, whistle
- [ ] For each rule: test triggers, test doesn't trigger, test exactly at the threshold (36+ tests)
- [ ] Each rule's reason text includes the actual number (e.g. "gusts up to 45 km/h at the high point")

## 1.9 `POST /v1/checklist`

- [ ] `ChecklistRequest`: `route: RouteSummary`, `date`, `start_time`, `options: TripOptions`
- [ ] `Warning`: `code`, `severity` (info / warn / danger), `message`
- [ ] `ChecklistResponse`: `route`, `timing`, `weather`, `groups: list[{category, items}]`, `warnings`, `rules_version`, `generated_at`
- [ ] Warnings: finish after sunset, weather unavailable, forecast too far ahead, elevation unavailable, heat
- [ ] `rules_version` = hash of `rules.yaml` + git SHA, so saved trips know what produced them
- [ ] Validation: date not in the past; start time present
- [ ] Test: 3 full API tests on fixtures with recorded weather
- [ ] Test: syrupy snapshots of the full response for those 3
- [ ] Test: past date → 422
- [ ] Test: weather down → 200 with a warning
- [ ] Measure: p95 uncached < 1.5 s, cached < 300 ms (simple Locust or httpx script)
- [ ] Regenerate the client; `api-contract` green

## 1.10 Plan screen (`/plan`)

- [ ] File input accepting `.gpx` (and `*/*` on mobile, validated by the API)
- [ ] Drag-and-drop zone on desktop
- [ ] Call `POST /v1/routes/parse` on file select; show name, distance, gain immediately
- [ ] Date picker limited from today to the forecast horizon
- [ ] Start-time input with a sensible default (e.g. 08:00)
- [ ] Options: group size, with kids, with dog
- [ ] "Build checklist" button → `POST /v1/checklist` → navigate to `/trip`
- [ ] Hold the current trip in a small store (Zustand) for the next screens
- [ ] Errors: invalid file, file too large, network failure, forecast too far ahead
- [ ] Loading states for both calls
- [ ] Tests: each error message renders for its API error code (MSW)
- [ ] Tests: date picker blocks past and beyond-horizon dates
- [ ] Playwright: upload a fixture → pick date → reach the checklist (desktop and mobile projects)
- [ ] Count taps in the mobile flow for the checkpoint

## 1.11 Route summary (`/trip`, top section)

- [ ] Stat cards: distance, gain, estimated duration, start → finish
- [ ] Finish vs sunset: margin in minutes, highlighted when < 60
- [ ] Elevation profile chart (Recharts) from `points`
- [ ] Weather strip: one card per weather point (time, temperature, wind, rain %, UV)
- [ ] Warnings banner from `warnings`, coloured by severity
- [ ] Units displayed in metric (km, m, °C, km/h)
- [ ] Tests: renders all 10 fixture responses without errors
- [ ] Tests: sunset highlight logic at 59 / 60 / 61 minutes
- [ ] Playwright `toHaveScreenshot()` baselines for 2 fixtures, desktop and mobile
- [ ] CI: `lighthouserc.json` with performance ≥ 85 and LCP < 2.5 s, run against the PR preview URL (treosh/lighthouse-ci-action)

## 1.12 Checklist screen (`/trip`, list section)

- [ ] Groups in category order, each collapsible
- [ ] Item row: checkbox, name, quantity, priority badge, reason text
- [ ] "Consider" items collapsed under "More ideas"
- [ ] Progress: ticked / total, per group and overall
- [ ] Tick state kept in the trip store
- [ ] Tests: tick / untick updates counts
- [ ] Tests: every item renders its reason
- [ ] Tests: ordering matches the API order
- [ ] Playwright: tick 3 items, counts update
- [ ] @axe-core/playwright checks on `/plan` and `/trip`; 0 violations
- [ ] Verify the exit checkpoint on 3 past hikes and record the add/remove counts in `docs/field-notes.md`
