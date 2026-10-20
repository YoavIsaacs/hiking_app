# 0005 — Elevation backfill: parse → lookup → summarise seam, Open-Meteo client, call budget, warning contract

Status: accepted (tech lead, 2026-10-20) · Date: 2026-10-20 · Step: 1.3

## Context
Step 1.3 (`docs/steps/1.3.md`): when an uploaded GPX has no usable elevation, `POST /v1/routes/parse` looks it
up from Open-Meteo for the simplified points only, recomputes gain/loss, and returns `elevation_source = "lookup"`.
If the lookup fails, the route still comes back, flagged, and never as a 500. The forces:
- **Trigger.** ADR 0004 §2/§3.1 step 8: `has_elevation` is false when *any* de-duplicated point lacks a plausible
  `<ele>` (missing, unparseable, non-finite or outside [−1000, 10000] m). The backfill must cover the implausible
  case as well as the missing one, and must never run for a file with full plausible elevation.
- **Purity (CLAUDE.md, ADR 0004 §1).** Nothing in `app/routes/` does I/O, reads the clock or logs. The roadmap's
  path `app/routes/elevation.py` already holds 1.2's pure smoothing/gain code.
- **Concurrency (ADR 0004 §3.10).** The parse runs in a worker thread under `parse_limiter` (1 slot); Cloud Run has
  `--concurrency=8`, 512 MiB, 1 vCPU, max 1 instance. Network I/O must not hold the parse slot.
- **Simplify needs the high point** (§3.5 forces it), but before the lookup there is no elevation to find it.
- **Checkpoint:** gain within 15 % of the reference for `derived-tel-hadid-no-ele.gpx` (parent's AllTrails
  reference 103 m, so 87.55–118.45 m), and **≤ 5 API calls per route**. The checklist also says batches of ≤ 100
  and "1 retry"; 5 batches plus a retry each would be 10 calls.
- **Contract (ADR 0001, 0004 §2).** All `RouteSummary` fields are required; a new field regenerates
  `api/openapi.json` and `web/src/api/schema.d.ts` (`just gen-api`). Step 1.9 defines
  `Warning: code, severity (info / warn / danger), message` and lists "elevation unavailable" among its warnings,
  and its `ChecklistRequest` carries a `RouteSummary` back to the server.
- **Open-Meteo Elevation API** (docs, checked 2026-10-20): `GET /v1/elevation?latitude=..&longitude=..`,
  comma-separated, "Up to 100 coordinates can be requested at once"; response `{"elevation": [38.0]}` (always an
  array); errors are HTTP 400 `{"error": true, "reason": "..."}`. The data is Copernicus DEM 2021 GLO-90 (90 m).
  Free tier (terms): non-commercial only (no ads, no subscriptions; donations allowed); fewer than 10,000 calls/day,
  5,000/hour and 600/minute, "applied by IP addresses and application"; data under CC BY 4.0 with attribution
  ("a link next to any location Open-Meteo data are displayed"), and Copernicus credited. No API key.

## Decision
A pure stage 1 builds the no-elevation `RouteSummary` (≤ 400 points). If `elevation_source == "none"`, an async
edge service looks up those points with an `ElevationClient` on a lifespan-owned `httpx.AsyncClient`, in ≤ 4
concurrent batches of ≤ 100 with **one retry per route**, so there are at most 5 calls. A pure stage 3 then fills in
elevation and recomputes gain/loss on those points. Any failure returns the stage-1 summary with an
`elevation_unavailable` entry in a new required `warnings: list[ApiWarning]` field.

### 1. Seam
```mermaid
flowchart LR
  R[routers/routes.py<br/>parse_route] --> S[services/route_parse.py<br/>summarise_upload]
  S -- "worker thread, parse_limiter" --> P1[routes/summary.py<br/>summarise_gpx = summarise_track ∘ parse_gpx]
  S -- "event loop, no limiter" --> C[clients/elevation.py<br/>ElevationClient.lookup]
  S -- "worker thread, default limiter" --> P3[routes/summary.py<br/>with_looked_up_elevation]
  S --> W[routes/summary.py<br/>with_warning]
  M[main.py lifespan] -- "app.state.elevation_lookup" --> D[dependencies.py<br/>get_elevation_lookup] --> R
  C --> H[(Open-Meteo<br/>/v1/elevation)]
```
- **Stage 1 (pure): `summarise_track(track, filename, params)`.** This is today's body of `summarise_gpx` after
  `parse_gpx`. `summarise_gpx(data, filename, params)` becomes `summarise_track(parse_gpx(data), filename,
  params)`, stays pure, and stays the benchmark target. The one behaviour change: when `has_elevation` is false it
  simplifies to `min(params.max_points, params.lookup_max_points)` = **400** points instead of 500 (§5). It never
  calls anything. `elevation_source` is `"file"` or `"none"` and `warnings` is `[]`.
- **Deviation from ADR 0004's follow-up sketch:** `summarise_track` takes no `elevation_source` argument and no
  backfilled `RawTrack`. The lookup covers only the simplified points, so a `RawTrack` with elevation at every
  point never exists. Instead, the stage-1 no-elevation summary *is* the lookup input: its `points` are the
  simplified points with full-resolution `dist_m`, start and end included. It is also the failure answer as it stands.
- **Stage 2 (edge): `app/services/route_parse.py::summarise_upload`.** It orchestrates, logs and owns the clock:
  1. `summary = await anyio.to_thread.run_sync(summarise_gpx, data, filename, params, limiter=limiter)`, the existing
     call moved here unchanged. `RouteParseError` propagates to the router, which maps it to 422 as today.
  2. `summary.elevation_source != "none"` → return it. No lookup, no log line.
  3. Otherwise `result = await elevation.lookup([(p.lat, p.lon) for p in summary.points])` **on the event loop,
     outside `parse_limiter`**, so a slow Open-Meteo never blocks other parses. If `elevation is None` (the
     lifespan did not run), it raises `RuntimeError("elevation lookup is not running (app lifespan not
     started)")`. That is a wiring bug, so a 500 is correct.
  4. Log one line (§7), then: on failure `with_warning(summary, ELEVATION_UNAVAILABLE)`; on success
     `await anyio.to_thread.run_sync(with_looked_up_elevation, summary, result.elevations, params)`, in a worker
     thread on anyio's **default** limiter. The work is bounded (≤ 400 points, ≤ `max_resample_points` samples,
     ≤ about 100 ms for a hostile globe-spanning line) and must not queue behind a 2.6 s hostile parse in the one
     parse slot.
- **Why a service module, not the router:** the router keeps the HTTP mapping (upload, size, 422). The service can
  be unit-tested with a fake `ElevationLookup` and no `TestClient`. Phase 2 orchestration (forecast, rules) gets
  siblings in `app/services/`.
- **Memory (ADR 0004 §3.10):** during the lookup the request holds the ≈ 100 KB summary, ≤ 4 response bodies of
  ≤ 64 KiB, and the router's `data` (≤ 10 MiB). That last one is the R term the budget already charges to every
  non-parsing request. The §3.10 budget and the queue arithmetic are unchanged. Worst-case added latency is
  §5's 10 s, and it holds no parse slot.

### 2. Trigger
Backfill **iff** stage 1 returns `elevation_source == "none"`, which is exactly `has_elevation == false`: some
de-duplicated point has a missing, unparseable, non-finite, overflowed (> 65,536 characters) or out-of-range `<ele>`
(ADR 0004 §3.1 step 8 and text capture). A file with every `<ele>` plausible is `"file"` and makes 0 calls. No DEM
correction of file elevation (out of scope).

### 3. Which points, and what the fields mean for a looked-up route
Order: **simplify without a high point (stage 1, horizontal RDP to ≤ 400) → look up exactly those points → compute
everything elevation-related on them.** No re-simplification and no densification.

| Field | `elevation_source = "lookup"` |
| --- | --- |
| `points[].elev_m` | the looked-up value for that point, as returned (not smoothed); never null |
| `start.elev_m`, `end.elev_m` | `points[0].elev_m`, `points[-1].elev_m` (simplify always keeps both ends) |
| `min_elev_m`, `max_elev_m` | min/max of the looked-up values, **over `points`**, not over all de-duplicated points as for `"file"` |
| `high_point` | the first index in `points` with the maximum looked-up value (`high_point_index`), so `max(p.elev_m for p in points) == max_elev_m` still holds |
| `gain_m`, `loss_m` | §3.4's method on `(points[].dist_m, elev)`: resample at `resample_step_m` (5 m) over the full-resolution distance, smooth with `lookup_smoothing_window_m`, hysteresis with `lookup_gain_threshold_m` |
| `has_elevation` | `true` |
| `warnings` | `[]` |
| everything else | unchanged from stage 1 (`distance_m`, `dist_m`, `is_loop`, `name`, `point_count_original`, …) |

**Smoothing parameters.** New `ParseParams` fields `lookup_smoothing_window_m` and `lookup_gain_threshold_m`, kept
apart from 1.2's pair so that tuning one never moves the other's gates. **Starting values = 1.2's: 20 m and
9.5 m.** The brief says 1.2's values were tuned for dense GPS. In fact they were tuned on DEM-sampled planned routes
(ADR 0004 Context: the AllTrails elevations are DEM samples), and that is the closest evidence we have. I don't
have GLO-90 numbers, so I'm not picking new values. GLO-90 at 90 m may flatten Tel Hadid's 11–13 m bumps, which
the reference counts, so the risk is **under**-counting.
- **Confirmation:** QA's recorded test (§7) computes the gain of `derived-tel-hadid-no-ele.gpx` with
  `DEFAULT_PARAMS`. If it is within 87.55–118.45 m, the values stand, and the number goes into `PROGRESS.md`. QA
  also reports the lookup gain for the other two AllTrails parents with `<ele>` stripped in the test (Modiin ref
  198, Ben Shemen ref 200). These are informational, not gated (the roadmap gates only the no-ele fixture).
- **If it misses (backend, pre-declared, not committed as code):** grid on the lookup pair only, window ∈ {0, 20,
  45, 90} m × T ∈ {2.0, 2.5, …, 12.0} m, scored on the three recorded routes. Feasible means Tel Hadid within
  ±15 %. Pick the feasible point that maximises the minimum margin (15 % − |error|) over all three; break ties by
  smaller window, then smaller T. Record the values in `params.py` with a comment pointing here, and the grid
  summary in the backend report. Forbidden, as in ADR 0004 §3.4: per-file parameters, loosening the gate,
  dropping the Tel Hadid gate.
- **Escalation (tech lead → manager, with the grid table):** if no grid point is feasible, or if the pick leaves
  Modiin or Ben Shemen outside ±15 % (a sign of overfitting to one file). The options to present: (a) a median
  pre-filter (ADR amendment); (b) a looser gate for looked-up routes (roadmap change); (c) a different elevation
  source (new service; terms and cost to check).

### 4. Client
- **Module: `app/clients/elevation.py`** (new package `app/clients/`, for outbound HTTP adapters; 1.5's
  forecast client and later Overpass sit beside it). The roadmap path `app/routes/elevation.py` is rejected because
  `app/routes/` is the pure package, and its `elevation.py` already holds the pure smoothing code. The tech lead
  records this path deviation in the brief.
- **Base URL:** the existing `Settings.open_meteo_base_url` (`HIKE_OPEN_METEO_BASE_URL`, default
  `https://api.open-meteo.com`) plus the path constant `ELEVATION_PATH = "/v1/elevation"`. This meets "Settings:
  elevation base URL". 1.5 reuses the same setting (brief, Out of scope).
- **New setting:** `elevation_timeout_s: float = 5.0`, with `gt=0, le=30`; env `HIKE_ELEVATION_TIMEOUT_S` (ADR 0002
  §8 naming). Batch size, retries and the call budget are `Final` constants in `app/routes/params.py`, **not**
  settings: the checkpoint's budget is a tested invariant, and env overrides would let it drift (the ADR 0004 §1
  rule).
- **Lifetime:** `create_app` sets `app.state.elevation_lookup = None` and passes `lifespan=lifespan` to `FastAPI`.
  On startup `lifespan` opens one `httpx.AsyncClient` from `new_http_client(settings)`: `base_url` =
  `open_meteo_base_url`, `timeout=httpx.Timeout(elevation_timeout_s)`, `follow_redirects=False`, header
  `User-Agent: hike-prep-api/<settings.version>`, no transport retries. It stores
  `ElevationClient(http, timeout_s=...)` on `app.state.elevation_lookup`. On shutdown it resets that to `None`, and
  `async with` closes the client. `get_elevation_lookup(request)` returns `app.state.elevation_lookup` and is the
  override point for tests. Because the attribute starts as `None`, a `TestClient` used without `with` still serves
  files that have elevation, and fails loudly (§1 step 3) only when a lookup is needed.
- **Query:** `latitude` and `longitude` are comma-joined, with no spaces, in point order; each value is
  `f"{v:.5f}"` (`COORD_DECIMALS = 5`, ≈ 1.1 m, far below the 90 m DEM cell). That keeps a 100-point URL at about
  2 KB. Other parameters: none.
- **Per attempt:** `anyio.fail_after(timeout_s)` around send *and* body read. This is a true wall-clock bound; httpx's
  timeouts are per phase and per read. The body is streamed and capped at `MAX_RESPONSE_BYTES = 64 KiB` (100 values
  is about 1 KB); a larger body is `bad_response`.
- **Response validation (`parse_elevations`)** — success only if the status is 200 and the body is a JSON object
  whose `elevation` is a list of exactly `expected` numbers (JSON int or float; not bool, string or null), each
  finite and within [`MIN_PLAUSIBLE_ELEV_M`, `MAX_PLAUSIBLE_ELEV_M`]. `NaN`/`Infinity` tokens and `1e999` are
  failures. Extra keys are ignored, and so is Content-Type. Anything else is `bad_response`.
- **Errors the client turns into a result:** `TimeoutError` (from `fail_after`), `httpx.TimeoutException`,
  `httpx.TransportError`, non-200 status and `bad_response`. **Every other exception propagates.** That includes
  pytest-socket's `SocketBlockedError`/`SocketConnectBlockedError` (`RuntimeError`s), so an accidental live call in a
  test fails loudly instead of degrading to a warning.
- **Terms:** the app is free with no ads or subscriptions, so it is non-commercial use. At ≤ 5 calls per route,
  10,000 calls/day allows ≥ 2,000 backfilled uploads a day. Cloud Run's egress IPs are shared, so we may meet
  someone else's limit (a 429, then the warning). Attribution is a 1.10/1.11 UX item (Follow-ups).

### 5. Call budget, retry, concurrency, latency
- **Constants** (`app/routes/params.py`): `ELEVATION_BATCH_SIZE = 100`, `ELEVATION_MAX_RETRIES = 1`,
  `ELEVATION_MAX_CALLS = 5`, and `LOOKUP_MAX_POINTS = (ELEVATION_MAX_CALLS − ELEVATION_MAX_RETRIES) ×
  ELEVATION_BATCH_SIZE = 400`.
- **How both hold:** a looked-up route has at most 400 points, so ≤ 4 batches, and **"1 retry" is one retry per
  lookup (per route), shared by its batches**. So calls ≤ ⌈400/100⌉ + 1 = 5. Stage 1 simplifies every no-elevation
  route to `min(max_points, lookup_max_points)` points, so the failure answer and the lookup answer have the same
  points. `ParseParams.__post_init__` raises `ValueError` unless `3 ≤ lookup_max_points ≤ LOOKUP_MAX_POINTS`.
  `ElevationClient.lookup` raises `ValueError` for 0 or more than `LOOKUP_MAX_POINTS` coordinates; that is a
  programming error.
- **Retried (once per route):** timeout, `httpx.TransportError` (connect, read, protocol errors) and HTTP 5xx.
  **Not retried:** 429 (Open-Meteo's limits are per minute, hour and day, so an immediate retry only burns budget),
  other 4xx and 3xx (our bug or a moved endpoint), and `bad_response` (deterministic). The retry is immediate, with
  no backoff.
- **Batches run concurrently** in one anyio task group. When a batch fails and the retry token is spent or the
  failure is not retryable, the lookup fails and the group is cancelled. **Calls counts attempts started**,
  including any cancelled in flight, so the bound is on what Open-Meteo may see.
- **Worst-case added latency: 2 × `elevation_timeout_s` = 10 s** (a first round of ≤ T, then one retry of ≤ T),
  plus a thread hop for stage 3. Typical latency is one round trip of about 0.1–0.3 s. No parse slot is held.
  Against Cloud Run's 300 s timeout it adds to ADR 0004's 28 s queue bar, for ≤ 38 s.
- **Partial failure is all-or-nothing:** if any batch fails, nothing is used, and every `elev_m` stays null.
  ADR 0004's "no holes" rule.

### 6. Failure contract
- New model `ApiWarning` in `app/models/warnings.py`. It is 1.9's `Warning` shape; the class is named `ApiWarning`
  because `Warning` shadows a Python builtin. Its fields: `code: WarningCode`, `severity: WarningSeverity`,
  `message: str` (English, for developers and logs). As with `ErrorResponse`, UX maps `code` to copy, and **clients
  treat an unknown `code` as a generic warning**. 1.9 extends `WarningCode`.
- `WarningCode = Literal["elevation_unavailable"]` in 1.3. `WarningSeverity = Literal["info", "warn", "danger"]`.
- The one warning 1.3 emits, `ELEVATION_UNAVAILABLE`, exactly:
  `{"code": "elevation_unavailable", "severity": "warn", "message": "Elevation could not be looked up, so gain,
  loss and the elevation profile are unavailable."}`. The message never carries upstream detail (status, reason);
  that detail goes to the log.
- `RouteSummary` gains **`warnings: list[ApiWarning]`**, required with no default (ADR 0004 §2), as the last field.
  It is `[]` when there is nothing to report.
- On failure the response is the stage-1 summary unchanged plus that warning: `has_elevation = false`,
  `elevation_source = "none"`, `gain_m`/`loss_m`/`min_elev_m`/`max_elev_m`/`high_point` null, every `elev_m` null,
  status 200.
- **Invariant over HTTP:** `elevation_source == "none"` ⇔ `warnings` contains `elevation_unavailable`. The pure
  `summarise_gpx` keeps `"none"` with `[]`, because it never attempts a lookup.
- `points` stays `2..500` in the schema; it is ≤ 400 whenever `elevation_source` is `"none"` or `"lookup"`.
- Contract change: backend runs `just gen-api`. `openapi.json` gains `ApiWarning` and `RouteSummary.warnings`, and
  `schema.d.ts` is regenerated, never edited.

### 7. Testing contract and observability
- **Recorded fixtures** in `api/tests/fixtures/http/elevation/`. QA captures them once, manually, outside pytest:
  - `record.py` is QA's script, not collected. It enumerates **every de-duplicated point** of each AllTrails parent
    (`alltrails-tel-hadid-loop.gpx`, `alltrails-modiin-hills-south-double-loop.gpx`,
    `alltrails-ben-shemen-hertzl-singletrack.gpx`) with `parse_gpx` and `drop_consecutive_duplicates`, and sends
    them through the app's own `split_batches`/`batch_query` to the live endpoint. That is about 21 calls in all,
    well inside the free tier.
  - `<parent-stem>.json`, one per parent:
    `{"source_fixture", "recorded_at" (UTC ISO 8601), "endpoint", "command" (exact command line), "git_sha",
    "coord_decimals": 5, "docs_checked": "https://open-meteo.com/en/docs/elevation-api", "requests": [{"url",
    "status", "date_header", "raw": "raw/<parent-stem>-<k>.json"}], "points": [{"lat", "lon", "sent",
    "elevation_m"}]}`. Here `lat`/`lon` are the GPX floats, `sent` is the `"lat,lon"` pair as sent, and
    `elevation_m` is the returned value.
  - `raw/<parent-stem>-<k>.json`: each response body, byte for byte.
- **Replay is by coordinate, not by URL.** A test helper builds `{(format_coord(lat), format_coord(lon)):
  elevation_m}` from `points` at load time and installs a respx side effect on `GET {base}/v1/elevation`. The side
  effect splits `latitude`/`longitude` from `request.url.params`, asserts both have equal length and ≤ 100 items,
  looks up every pair, and returns `httpx.Response(200, json={"elevation": [...]})`. An unknown pair raises
  `KeyError`, which the client does not catch, so the test fails loudly. Changes to batching, order, simplification
  or `lookup_max_points` therefore don't break the tests. Only a change to `COORD_DECIMALS` needs a re-record, and
  even then the stored GPX floats re-key the table, about 1 m off.
- A **synthetic** side effect (elevation = any fixed deterministic function of lat/lon) serves synthetic routes
  and fuzzing, where no real data is needed.
- **Log line** (logger `app.elevation`, from `summarise_upload`, exactly one per attempted lookup, none when no
  lookup): message `"elevation_lookup"`, with extra fields `points` (int), `batches` (int), `calls` (int),
  `outcome` (`ok` | `timeout` | `transport_error` | `http_status` | `bad_response`), `status_code` (int | null, the
  last non-200 status) and `duration_ms` (float). Level INFO on `ok`, WARNING otherwise. `JsonFormatter` adds
  `request_id`. The live checkpoint reads `calls` and `outcome` from this line.

## Interface — stub contract
Backend stubs exactly these modules and signatures (bodies `raise NotImplementedError` where QA needs red tests).
```python
# app/routes/params.py — additions
ELEVATION_BATCH_SIZE: Final = 100   # Open-Meteo: "Up to 100 coordinates can be requested at once"
ELEVATION_MAX_RETRIES: Final = 1    # per lookup (per route), shared by its batches
ELEVATION_MAX_CALLS: Final = 5      # roadmap 1.3 checkpoint
LOOKUP_MAX_POINTS: Final = (ELEVATION_MAX_CALLS - ELEVATION_MAX_RETRIES) * ELEVATION_BATCH_SIZE  # 400

@dataclass(frozen=True, slots=True)
class ParseParams:
    ...                                          # 1.2 fields unchanged
    lookup_max_points: int = LOOKUP_MAX_POINTS   # 3..LOOKUP_MAX_POINTS; effective = min(this, max_points)
    lookup_smoothing_window_m: float = 20.0      # ADR 0005 §3: 1.2's values until QA's recordings say otherwise
    lookup_gain_threshold_m: float = 9.5         # non-negative finite, like the 1.2 pair

# app/models/warnings.py — new
WarningCode = Literal["elevation_unavailable"]
WarningSeverity = Literal["info", "warn", "danger"]

class ApiWarning(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: WarningCode
    severity: WarningSeverity
    message: Annotated[str, Field(min_length=1)]

ELEVATION_UNAVAILABLE: Final[ApiWarning]  # the exact values in §6

# app/models/route.py — RouteSummary gains, as its last field (required, no default):
    warnings: list[ApiWarning]

# app/routes/summary.py — pure
def summarise_track(
    track: RawTrack, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary: ...  # elevation_source "file" | "none"; warnings []; no-elevation → ≤ lookup_max_points points
def summarise_gpx(
    data: bytes, filename: str | None, params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary: ...  # == summarise_track(parse_gpx(data), filename, params); benchmark target
def with_looked_up_elevation(
    summary: RouteSummary, elevations: Sequence[float], params: ParseParams = DEFAULT_PARAMS
) -> RouteSummary: ...  # §3 table; ValueError if summary.elevation_source != "none",
                        # len(elevations) != len(summary.points), or any value non-finite/implausible
def with_warning(summary: RouteSummary, warning: ApiWarning) -> RouteSummary: ...  # appends; nothing else changes

# app/clients/__init__.py — empty
# app/clients/elevation.py
ELEVATION_PATH: Final = "/v1/elevation"
COORD_DECIMALS: Final = 5
MAX_RESPONSE_BYTES: Final = 64 * 1024
LookupOutcome = Literal["ok", "timeout", "transport_error", "http_status", "bad_response"]

@dataclass(frozen=True, slots=True)
class LookupResult:
    elevations: tuple[float, ...] | None  # None iff outcome != "ok"; else len == len(coords)
    outcome: LookupOutcome
    calls: int                            # attempts started, ≤ ELEVATION_MAX_CALLS
    batches: int
    status_code: int | None               # last non-200 status seen, for the log

class ElevationLookup(Protocol):
    async def lookup(self, coords: Sequence[tuple[float, float]]) -> LookupResult: ...

def format_coord(value: float) -> str: ...                              # f"{value:.5f}"
def split_batches(
    coords: Sequence[tuple[float, float]], size: int = ELEVATION_BATCH_SIZE
) -> list[Sequence[tuple[float, float]]]: ...                           # in order, each ≤ size
def batch_query(batch: Sequence[tuple[float, float]]) -> dict[str, str]: ...  # {"latitude": "..", "longitude": ".."}
def parse_elevations(body: bytes, expected: int) -> tuple[float, ...] | None: ...  # §4 validation; None = bad

class ElevationClient:  # satisfies ElevationLookup
    def __init__(self, http: httpx.AsyncClient, *, timeout_s: float) -> None: ...
    async def lookup(self, coords: Sequence[tuple[float, float]]) -> LookupResult: ...
        # ValueError if not 1 ≤ len(coords) ≤ LOOKUP_MAX_POINTS

def new_http_client(settings: Settings) -> httpx.AsyncClient: ...  # §4 "Lifetime" options

# app/services/__init__.py — empty
# app/services/route_parse.py — logger = logging.getLogger("app.elevation")
async def summarise_upload(
    data: bytes,
    filename: str | None,
    *,
    limiter: anyio.CapacityLimiter,
    elevation: ElevationLookup | None,
    params: ParseParams = DEFAULT_PARAMS,
) -> RouteSummary: ...  # raises RouteParseError (→ 422 in the router) or RuntimeError (no lifespan)

# app/config.py — Settings gains
    elevation_timeout_s: Annotated[float, Field(gt=0, le=30)] = 5.0   # HIKE_ELEVATION_TIMEOUT_S

# app/dependencies.py
def get_elevation_lookup(request: Request) -> ElevationLookup | None: ...

# app/main.py
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]: ...
# create_app: app.state.elevation_lookup = None; FastAPI(..., lifespan=lifespan)

# app/routers/routes.py — handler name (operation ID parseRoute) and responses unchanged
async def parse_route(
    file: Annotated[UploadFile, File(description="GPX 1.0/1.1 file, at most 10 MB")],
    limiter: Annotated[anyio.CapacityLimiter, Depends(get_parse_limiter)],
    elevation: Annotated[ElevationLookup | None, Depends(get_elevation_lookup)],
) -> RouteSummary: ...  # read/close/size check as today, then summarise_upload; RouteParseError → ApiError(422)
```
`pyproject.toml`: backend moves `httpx` from the `dev` group to `[project] dependencies`. It is already in
`uv.lock` (≥ 0.28.1), so no new package enters the lock.

## Options considered
- **Lookup inside the pure pipeline (an injected callable)**: rejected. It puts I/O in `app/routes/` and can't
  await from the worker thread.
- **A sync httpx client inside the worker thread**: rejected. It holds the one parse slot for up to 10 s of network
  time, so every parse queues behind Open-Meteo.
- **ADR 0004's sketch (`summarise_track(..., elevation_source=)` over a backfilled `RawTrack`)**: rejected. It
  needs elevation at every de-duplicated point, up to 100k points or 1,000 calls.
- **An intermediate `PreparedTrack` type between the stages**: rejected. The no-elevation `RouteSummary` already
  holds exactly the lookup input, is the failure answer, and keeps the waiting request small.
- **Orchestration in the router**: rejected. It mixes HTTP mapping with the pipeline, and the service is testable
  without `TestClient`.
- **Re-simplifying after the lookup to force the high point**: rejected. It would need elevation at points never
  looked up; the high point among looked-up points is in `points` by construction.
- **Client at `app/routes/elevation.py`, renaming the pure module**: rejected. That is I/O in the pure package, plus
  churn in 1.2's code, tests and ADR references.
- **5 batches of 100 and a retry only when budget is left**: rejected. Every route over 400 points, the common
  case, would never retry.
- **A retry per batch**: rejected. Up to 10 calls breaks the checkpoint.
- **Reading "≤ 5 calls" as excluding retries**: rejected. It is a roadmap reinterpretation, and 400 points cost
  nothing measurable against a 90 m DEM.
- **Sequential batches**: rejected. The worst case is (4 + 1) × 5 s = 25 s against 10 s, and the typical case is
  4× slower.
- **Retrying 429, or a backoff before the retry**: rejected. The limits are per minute, hour and day, so an
  immediate 429 retry only burns budget; backoff adds latency and a knob for blips that one immediate retry
  already covers.
- **httpx transport `retries=1`**: rejected. It covers connect errors only, and its attempts would not appear in
  our call count.
- **Partial results (fill the batches that succeeded)**: rejected. That leaves holes in the profile (ADR 0004 §2).
- **`warning: str | None`, or a warning without `severity`**: rejected. 1.9 defines `{code, severity, message}`, and
  a list allows more than one warning.
- **Batch size, retries and timeout as env settings (all of them)**: rejected. The call budget is a tested
  invariant; only the timeout is operational.
- **A separate `elevation_base_url` setting**: rejected. It is the same host as 1.5's weather, and the brief says to
  reuse it.
- **Reusing 1.2's smoothing fields for lookups**: rejected. Tuning for lookups would move the file-elevation gates.
  **Choosing new values now**: rejected, because there is no GLO-90 data yet.
- **URL-keyed cassettes / a VCR library**: rejected. Any change to batching or simplification breaks every
  recording, and the library is a new dependency.
- **Catching every exception in the client**: rejected. It would hide bugs, and it would turn pytest-socket's block
  into a silent warning.

## Consequences
- Easier: the parse slot never waits on the network. `summarise_gpx` and its benchmark are unchanged for files
  with elevation. Lookup tests survive changes to batching and simplification. 1.9 reuses `ApiWarning`. Clients
  get one rule: `"none"` comes with `elevation_unavailable`.
- **No-elevation routes return ≤ 400 points (was 500)**, both from the pure `summarise_gpx` and over HTTP. 1.2
  tests that pin 500 for a no-elevation file change (QA).
- For looked-up routes, `min_elev_m`/`max_elev_m`/`high_point` are taken over ≤ 400 horizontally chosen points. A
  summit on a straight stretch can fall between them, so the reported maximum can be a little low. That is accepted
  at 90 m DEM resolution.
- **Harder later:**
  - Raising the call budget, or more than 400 lookup points, is an ADR amendment plus a manager check against the
    free-tier limits.
  - Coastal or sea points that come back non-finite fail the whole lookup (no holes).
  - Shared Cloud Run egress IPs make 429s possible that we cannot prevent without a static egress IP, which is
    paid (Cloud NAT).
  - `RouteSummary.warnings` becomes part of 1.9's request body, so its enum grows under the unknown-code rule.
  - httpx moves into the runtime image, and Starlette's httpx deprecation (pyproject filter) may force a
    migration later.
- Route coordinates now leave our server for Open-Meteo, as weather coordinates will in 1.5. This needs a line in
  the privacy copy before Phase 3.

## How it is tested — tests QA writes
All tests are offline (`--disable-socket --allow-hosts=127.0.0.1`). They use the respx router on
`settings.open_meteo_base_url` (`http://open-meteo.test` in `tests/conftest.py`) and an app run **with its
lifespan** (`with TestClient(create_app(settings)) as c`), unless a row says otherwise.

| Brief test | What it asserts |
| --- | --- |
| no-elevation fixture gets gain within 15 % | `derived-tel-hadid-no-ele.gpx` through the endpoint, using the recorded Tel Hadid table: 200, `elevation_source == "lookup"`, `has_elevation`, 87.55 ≤ `gain_m` ≤ 118.45, `distance_m` within 2 % of 6,400, `warnings == []`, respx call count ≤ 5 (exactly 4 for 400 points). This is also the "real app wiring" test. Informational: the same for Modiin and Ben Shemen, with `<ele>` stripped in the test; their numbers are reported, not asserted. |
| 250 points → exactly 3 requests | A synthetic 250-point no-`<ele>` route through the endpoint with the synthetic side effect: call count == 3, batch sizes as a multiset {100, 100, 50}, every request has equal-length `latitude`/`longitude` of ≤ 100 values at 5 dp. Plus `split_batches` unit cases: 1, 100, 101, 400. |
| timeout → returned, flagged, no 500 | Every call raises `httpx.ReadTimeout` (and, separately, `ConnectTimeout`): 200, `has_elevation` false, `elevation_source == "none"`, `warnings == [ELEVATION_UNAVAILABLE]` exactly, all `elev_m` null; calls == 2 for a ≤ 100-point route. Wall-clock bound: an `ElevationClient` on `httpx.MockTransport` with an async handler that sleeps longer than `timeout_s` = 0.05 gives outcome `timeout`. |
| file with elevation → 0 requests | Every fixture with `has_elevation: true` in `expected.json`, through the endpoint: call count == 0, `elevation_source == "file"`, no `elevation_lookup` log record. |
| pytest-socket blocks live calls | An `ElevationClient` on a real `httpx.AsyncClient` (base `http://192.0.2.1`, no respx) raises pytest-socket's blocked-socket error from `lookup`; the client does not swallow it into a result. Plus: `pyproject` `addopts` contains `--disable-socket`. |
| implausible elevation → backfilled | The Tel Hadid parent with one `<ele>` set to `99999`, and separately one `<ele>` removed: `elevation_source == "lookup"`, and `gain_m` equals the no-ele fixture's lookup gain exactly (same coordinates, same points). |
| 5xx / malformed / wrong count; retry once | 503 then 200 → success, calls = batches + 1. 503 twice on one batch → flagged, and that batch made exactly 2 calls. 429 → flagged, no retry. Bodies: not JSON, `{}`, wrong count, `null`, `"12"`, `true`, `NaN`, `1e999`, `20000`, over 64 KiB → flagged, no retry. One batch of 3 fails → all `elev_m` null (all-or-nothing). Hypothesis: any failure pattern on a 400-point route keeps calls ≤ 5. |
| endpoint through real wiring | The gain row above. Lifespan: inside `with`, `app.state.elevation_lookup` is an `ElevationClient`; after exit it is `None`. `HIKE_ELEVATION_TIMEOUT_S` is read; 0 and −1 are rejected. |

Also:
- **Contract and pure units:** `with_looked_up_elevation` gives the §3 table's invariants: `max(points.elev) ==
  max_elev_m`, `high_point` in `points`, `start`/`end` equal to `points[0]`/`points[-1]`, `gain − loss == last −
  first` of the smoothed series. It raises `ValueError` on preconditions. `with_warning` changes nothing else.
  `parse_elevations` accepts every recorded raw body and equals the table values. `ParseParams` rejects
  `lookup_max_points` outside 3..400. `ceil(LOOKUP_MAX_POINTS / ELEVATION_BATCH_SIZE) + ELEVATION_MAX_RETRIES <=
  ELEVATION_MAX_CALLS`.
- **Log:** `caplog` holds exactly one `elevation_lookup` record per lookup, with `calls`, `outcome` and `points`
  as specified.
- **1.2 tests to update (QA):**
  - HTTP tests that upload files without usable elevation now need the lifespan and a respx router: the fuzz
    `over_http` in `test_never_500.py`, `test_text_caps.py`'s overflowed-`<ele>` test, `test_elevation_bounds.py`.
    A shared `elevation_api` fixture with the synthetic side effect is the suggested shape. Their expectations move
    from `"none"` to `"lookup"`, or to `"none"` plus the warning under a failing side effect.
  - Any test pinning 500 points for a no-elevation file changes to 400.
  - Pure-layer tests of `summarise_gpx` keep `"none"`, and gain `warnings == []`.
- **Backend unit tests:** internals beyond these (task-group cancellation, streamed body cap).
- **Live checkpoint (after merge, not CI):** `POST /v1/routes/parse` of `derived-tel-hadid-no-ele.gpx` on the
  deployed API → `elevation_source == "lookup"`, gain 87.55–118.45 m. The `elevation_lookup` log entry for that
  request shows `calls ≤ 5` and `outcome == "ok"`.

## Follow-ups (out of scope)
- **Attribution (1.10/1.11, UX):** CC BY 4.0 needs "a link next to any location Open-Meteo data are displayed",
  plus Copernicus credit. When `elevation_source == "lookup"`, the profile/summary should show "Elevation data:
  Open-Meteo.com (Copernicus DEM GLO-90)" with links. Weather in 1.5 shares the obligation.
- **Live checkpoint log access:** reading the deployed `elevation_lookup` line needs Cloud Logging (console or
  `gcloud logging read`), which is a manager action. The tech lead should add it to the brief's Manager actions.
- **ADR 0002 §8's env list** should gain `HIKE_ELEVATION_TIMEOUT_S` the next time ADR 0002 is touched.
- **ADR 0004 §1 says `RouteSummary` is response-only;** 1.9 makes it a request model too. 1.9's ADR should decide
  whether the server trusts a client-sent summary.
- **Caching lookups** (brief, Out of scope): revisit if 429s or the daily limit show up in the
  `elevation_lookup` outcomes.
- **Commercial use:** if the app ever adds ads or subscriptions, Open-Meteo requires a paid plan, which is a
  manager decision.

## References
- Open-Meteo Elevation API docs (endpoint, ≤ 100 coordinates, response and error shape, Copernicus GLO-90 90 m,
  attribution): https://open-meteo.com/en/docs/elevation-api (checked 2026-10-20)
- Open-Meteo terms (free-tier limits 10,000/day, 5,000/hour, 600/minute; per IP and application; non-commercial
  definition; CC BY 4.0): https://open-meteo.com/en/terms (checked 2026-10-20)
- Open-Meteo pricing (one API call is typically one HTTP request; monthly limits not enforced yet):
  https://open-meteo.com/en/pricing (checked 2026-10-20)
- Open-Meteo licence (attribution link next to the data; Copernicus licence): https://open-meteo.com/en/licence
  (checked 2026-10-20)
- respx guide (side effects, `call_count`/`calls`, `base_url`, `assert_all_mocked`):
  https://lundberg.github.io/respx/guide/
- Repo: `docs/steps/1.3.md`; `docs/roadmap/phase-1.md` §1.3 and §1.9; ADR 0002 §8; ADR 0004 §1, §2, §3.1,
  §3.4–3.6, §3.10, Follow-ups; `api/app/routes/{summary,simplify,elevation,params}.py`,
  `api/app/routers/routes.py`, `api/app/{main,dependencies,config,logging_config}.py`,
  `api/tests/conftest.py`, `api/tests/fixtures/gpx/expected.json`.
