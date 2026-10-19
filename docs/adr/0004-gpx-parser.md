# 0004 — GPX parser: module boundary, RouteSummary/ErrorResponse contract, algorithms, upload limits, benchmark

Status: accepted · Date: 2026-10-19 · Step: 1.2

## Context
Step 1.2 adds `POST /v1/routes/parse`. It turns an uploaded GPX file into a typed `RouteSummary`, rejects bad input
with a typed `ErrorResponse`, never returns 500, and parses the largest fixture in < 2 s. A CI benchmark guards
against regressions. The forces at play:
- **Gates:** distance within 2 % and gain within 10 % of the AllTrails reference on every valid 1.1 fixture. Raw
  gain is far above the references: Modiin 245/198, Ben Shemen 375/200, Tel Hadid 236/103 m.
- **Fixtures:** the three AllTrails files are *planned routes*, and their elevations are DEM samples. The values
  have 2 decimals and repeat over runs of consecutive points, the staircase of DEM cells. They show single-cell
  artefacts of 2–6 m and bumps of about 10 m that AllTrails does not count. Point spacing is about 8 m (Tel
  Hadid), 14 m (Ben Shemen) and 23 m (Modiin). The > 10k fixture is Ben Shemen linearly densified 14×, so any
  point-count window or threshold behaves differently on it. Method parameters therefore have to be in metres
  along the track, not in points.
- **Code rules (CLAUDE.md):** rule logic is pure (no I/O, clock or randomness), mypy strict, no `Any` without a
  reason, no network in unit tests, coverage gate 85 %, and new dependencies need an ADR plus manager approval.
- **API contract (ADR 0001):** handler names become operation IDs (`parse_route` → `parseRoute`), and
  `api-contract` fails on a stale `openapi.json`/`schema.d.ts`. The OpenAPI must be fully typed, error responses
  included, because 1.10 (PWA) and later Expo generate their clients from it.
- **Existing error shape:** `RequestIdMiddleware` turns unhandled exceptions into
  `500 {"detail": "Internal Server Error"}`, and `tests/test_errors.py` asserts exactly that body. FastAPI's own
  422 is `{"detail": [...]}`, and Starlette's 404/405 is `{"detail": "Not Found"}`. Neither is `ErrorResponse`.
- **Runtime:** Cloud Run with 512 MiB of memory, concurrency 80 and max 1 instance (ADR 0002/0003). The
  filesystem is in memory, and Cloud Run caps HTTP/1 requests at 32 MiB. Starlette spools uploads to a
  `SpooledTemporaryFile` (1 MiB in memory, then "disk", which is RAM here) and has **no total file-size limit**.
- **Path:** the brief notes that `overview.md` says `/routes/parse` and is pending manager confirmation. This ADR
  uses `/v1/routes/parse`, the phase-1 checklist path. If the manager picks the other path, only the router prefix
  changes.

## Decision

### 1. Module boundary
| Module | Role | Imports |
| --- | --- | --- |
| `app/models/route.py` | `LatLonElev`, `TrackPoint`, `RouteSummary` (Pydantic, response-only) | pydantic, `app.routes.params` (the 500 cap) |
| `app/models/errors.py` | `ErrorCode`, `FieldError`, `ErrorResponse` | pydantic |
| `app/routes/` | **pure** pipeline: bytes in, `RouteSummary` or a `RouteParseError` out | stdlib, gpxpy (in `parse.py` only), `app.models.route` |
| `app/routers/routes.py` | the I/O edge: multipart upload, size limit, threadpool, error mapping | fastapi, `app.routes`, `app.errors`, `app.body_limit` |
| `app/errors.py` | `ApiError`, global exception handlers, `ERROR_RESPONSES` for OpenAPI | fastapi/starlette, `app.models.errors` |
| `app/body_limit.py` | `UploadLimitRoute`: streaming request-body cap | fastapi/starlette, `app.routes.params`, `app.errors` |

`ErrorResponse` goes in `app/models/errors.py`, not in `route.py`, because every endpoint shares it. This is a
deliberate deviation from the checklist's "Models (`app/models/route.py`)" heading, and the tech lead records it in
the brief.

**Purity.** Nothing in `app/routes/` reads files, the environment, the clock or randomness, and nothing logs.
`summarise_gpx(data, filename, params)` is the whole pipeline and is what the benchmark measures. gpxpy parsing
bytes in memory counts as pure: it does no I/O.

**One place for parameters: `app/routes/params.py`.** It holds the frozen `ParseParams` dataclass plus `Final`
constants: the upload limit, the 500-point cap, Earth's radius and the name limits. Each pure function takes its
parameters as keyword arguments whose defaults come from `DEFAULT_PARAMS`. Parameters are **not** `Settings`/env:
the accuracy gates are tuned against these exact values, and env overrides would let environments drift away from
what was tested. `ParseParams.__post_init__` raises `ValueError` on nonsense values (a programming error, never
user input).

### 2. Contract
All fields are **required**. Nullable fields are `T | None` with no default, so they are always present in the JSON
and openapi-typescript emits `x: T | null`, never `x?: T`. Units are metres and WGS84 degrees. Floats are finite
(`allow_inf_nan=False`) and are not rounded (see follow-ups for payload size).

**`LatLonElev`**
| Field | Type | Meaning |
| --- | --- | --- |
| `lat` | float, −90..90 | degrees |
| `lon` | float, −180..180 | degrees |
| `elev_m` | float \| null | elevation from the file, metres; null when `has_elevation` is false |

**`TrackPoint`**: `lat`, `lon` and `elev_m` as above, plus `dist_m: float ≥ 0`. `dist_m` is the cumulative 2-D
distance from the start along the **full-resolution** de-duplicated track, not along the simplified line. It never
decreases along `points`, the first value is 0, and the last equals `distance_m`.

**`RouteSummary`**
| Field | Type | Meaning / when no elevation |
| --- | --- | --- |
| `name` | str, 1..200 chars | §3.9 |
| `distance_m` | float ≥ 0 | 2-D haversine length, segment jumps included (§3.2) |
| `gain_m`, `loss_m` | float ≥ 0 \| null | smoothed and thresholded (§3.4); **null** when `has_elevation` is false |
| `min_elev_m`, `max_elev_m` | float \| null | raw file values over all de-duplicated points; **null** when there is no elevation |
| `high_point` | `LatLonElev` \| null | first point with the maximum raw elevation; **null** when there is no elevation |
| `start`, `end` | `LatLonElev` | first and last de-duplicated point (`elev_m` null when there is no elevation) |
| `is_loop` | bool | §3.8 |
| `points` | list[`TrackPoint`], 2..500 items | §3.5; always includes start, end and the high point |
| `has_elevation` | bool | true iff **every** de-duplicated point has a finite `<ele>` |
| `elevation_source` | `"file"` \| `"lookup"` \| `"none"` | 1.2 emits only `file`/`none`; `lookup` is reserved for 1.3 and is in the enum now so 1.3 doesn't change the type |
| `source_format` | `"trk"` \| `"rte"` | §3.1 |
| `point_count_original` | int ≥ 2 | points in the chosen source as the file has them (all segments, before de-duplication) |

No elevation means **null, not 0**. Zero gain is a real value (a flat route), and the Phase 2 rules must not mistake
"unknown" for "flat". A file where only some points have `<ele>` counts as having no elevation, and every `elev_m`
is null. That keeps clients from ever drawing a profile with holes. 1.3's lookup then supplies elevation.

**`ErrorResponse`, shared by every error the app returns:**
```json
{"code": "invalid_gpx", "message": "The file is not well-formed XML (line 12, column 5).", "detail": null}
```
- `code`: `ErrorCode`, the stable, machine-readable value clients branch on.
- `message`: an English sentence for developers and logs. **UX copy maps `code` to user text.** Clients never show
  `message` as product copy.
- `detail`: `list[FieldError] | null`. It is non-null only for `validation_error`. `FieldError` is
  `{loc: list[str | int], msg: str, type: str}`, FastAPI's error list with `input`, `ctx` and `url` **dropped**, so
  uploaded content is never echoed back.

| Status | `code` | Raised by |
| --- | --- | --- |
| 413 | `file_too_large` | the `Content-Length` pre-check, the streaming body cap, or the file-length check (§3.10) |
| 422 | `invalid_gpx` | empty file, not UTF-8, not well-formed, DTD/entity present, root not `<gpx>`, any gpxpy failure, coordinates out of range or not finite |
| 422 | `too_few_points` | fewer than 2 points after merging and de-duplication (this includes waypoint-only files) |
| 422 | `validation_error` | FastAPI `RequestValidationError`, e.g. the `file` field is missing, or `file` is a text field |
| 400 | `bad_request` | Starlette multipart errors (FastAPI turns form-parsing failures into `HTTPException(400)`) |
| 404 / 405 | `not_found` / `method_not_allowed` | Starlette routing; the `Allow` header is kept |
| other 4xx | `http_error` | any other `HTTPException` |
| 500 | `internal_error` | `RequestIdMiddleware`'s catch-all (a bug; the fuzz test exists so this never happens) |

**Reconciling with the existing 500.** `RequestIdMiddleware` keeps its role: it logs with the request ID and
responds when nothing has started. Its body becomes
`{"code": "internal_error", "message": "Internal Server Error", "detail": null}`, built from `ErrorResponse`.
`test_errors.py`'s body assertion changes to match (QA). The test that the secret detail never leaks stays as it
is. Every error response, the 500 included, still carries `X-Request-ID`.

**Handlers (`install_error_handlers`, called in `create_app`):**
- `StarletteHTTPException` → `ErrorResponse`. For an `ApiError` the code comes from `exc.code`; for any other
  `HTTPException` it comes from the status table above. `exc.headers` is kept.
- `RequestValidationError` → 422 `validation_error`.

`ApiError` **subclasses Starlette's `HTTPException`** on purpose. FastAPI's body reader re-raises `HTTPException`
unchanged but wraps any other exception into a 400, and the streaming body cap raises from inside
`request.form()`.

**OpenAPI.** The handler `async def parse_route(...) -> RouteSummary` (operation ID `parseRoute`) declares
`responses=ERROR_RESPONSES`, which maps 400, 413, 422 and 500 to `{"model": ErrorResponse}`. Declaring 422
explicitly stops FastAPI from adding its default `HTTPValidationError` schema, which would be a lie, since our 422 is
`ErrorResponse`. The request body is `multipart/form-data` with `file: binary`; FastAPI names its schema
`Body_parseRoute`. `/health`'s OpenAPI stays unchanged in 1.2: its errors use the shape at runtime, and its
undocumented 500 isn't worth the schema churn.

**Clients must treat an unknown `code` as a generic error.** New codes will be added, and an installed Expo build
can't be updated in lock-step.

### 3. Algorithms

**3.1 Parse (`parse_gpx`).** The input bytes go through these steps, in order:
1. **Empty input** → `invalid_gpx`.
2. **XML prolog guard** (`check_gpx_prolog`, §3.11) on the raw bytes.
3. **Decode** as `utf-8-sig`, strict, which strips a BOM. Failure → `invalid_gpx` "file must be UTF-8".
4. **Parse:** `gpxpy.parse(text)`. **Every** exception from that one call (`GPXXMLSyntaxException`, `GPXException`,
   `ValueError`, …) → `invalid_gpx`, chained with `from`. This catch-all is justified because gpxpy is a
   third-party parser of untrusted input. It wraps **only** the gpxpy call. Our own bugs still surface as 500, and
   the fuzz test hunts for them.
5. **Choose a source.** `trk` if all `<trk>` together hold ≥ 2 points. Otherwise `rte` if all `<rte>` together hold
   ≥ 2. Otherwise whichever has more points (`trk` on a tie); the later < 2 check then raises `too_few_points`.
6. **Merge:** within the chosen kind, every track (or route) and every segment, in document order.
7. **Validate:** every chosen point must have finite lat in −90..90 and lon in −180..180, else `invalid_gpx`. A
   missing or non-finite `<ele>` becomes `None`.

`RawTrack` carries the names: `metadata_name` from `<metadata><name>`, and `track_name` from the first non-blank
`<trk><name>` (or `<rte><name>` when the source is `rte`).

**3.2 Segments and duplicates.**
- **Jumps between segments are counted.** The merged points form one polyline, so the straight jump from the end of
  segment *k* to the start of *k+1* adds to `distance_m`. Its elevation change also feeds gain/loss.
  - Reasons: `points[]` is one line on the map, and `dist_m` stays continuous along it. A pause/resume gap is
    ground the hiker really covers. Smoothing and RDP need no segment-boundary bookkeeping.
  - On the fixture, multi-segment distance ≈ parent − 0.3 m (the 34.1 m dropped path versus the 33.8 m straight
    jump), against ≈ parent − 34 m if the jump were skipped.
- **Consecutive duplicates:** points with exactly equal `(lat, lon)` floats, after merging and so across segment
  boundaries too. The first is kept, with its elevation. Near-duplicates stay; they add ≈ 0 m, and smoothing is
  distance-based, so they don't bias anything.

**3.3 Distance: haversine, 2-D, R = 6 371 008.8 m (IUGG mean radius). No geographiclib.**
- **Error against the WGS84 ellipsoid:** at Israel's latitude (32° N) the meridian radius is 6 353 355 m and the
  prime-vertical radius is 6 384 144 m. A sphere is therefore +0.28 % north–south and −0.21 % east–west, and the
  worst case anywhere on Earth is +0.56 % (meridional, at the equator).
- **Budget:** a loop mixes directions, so the error stays ≤ 0.3 % here. That fits inside the 2 % gate together with
  the references' ±50 m rounding (≤ 0.8 % on Tel Hadid).
- **Conditioning:** haversine stays well-conditioned for metre-scale steps, unlike the spherical law of cosines.
- **2-D, not 3-D:** slope adds only √(1+g²)−1, which is 0.5 % at a 10 % grade. Source apps report horizontal
  length.
- **Accumulation:** the cumulative distance is a running float sum, and `distance_m` is its last element.

**3.4 Elevation: resample by distance → centred moving average in metres → hysteresis threshold.** This only
runs when `has_elevation` is true. The input is the de-duplicated profile `(dist_m[i], elev_m[i])`, with raw
elevations.
1. **Resample.** Let L = total distance and n = min(max(1, ⌈L / `resample_step_m`⌉), `max_resample_points`). Sample
   the piecewise-linear profile at t_k = k·L/n for k = 0..n. Both ends are exact, and the grid is
   mirror-symmetric, which the reversal property needs.
   - Interpolation must be well-defined for repeated distances (use the later point) and for L = 0 (return the two
     endpoint elevations).
   - `max_resample_points` (100 000) bounds memory against hostile, globe-spanning files.
   - Resampling is what makes the method **density-independent**. The > 10k fixture lies on the same
     piecewise-linear profile as its parent, so it resamples to the same series, up to 6-dp/2-dp rounding.
2. **Smooth (`smooth_elevation`).** A centred moving average over ±h samples, with h = ⌊`smoothing_window_m` /
   (2·Δ)⌋ and Δ = L/n. **The window shrinks symmetrically at the ends** (h_k = min(h, k, n−k)), so the endpoints
   keep their raw values and any linear profile passes through unchanged. A window of 0 is the identity.
3. **Gain/loss (`gain_loss`), Schmitt-trigger hysteresis with threshold T.** It is defined so that it is exactly
   symmetric under reversal:
   - **Undetermined phase.** Track the running max and min from the first sample. The first time a sample is ≥
     min + T, the direction becomes *up*. The first extreme is that min, and the leg first sample → min counts as
     loss (it is < T). Down is symmetric.
   - **Up phase.** Follow a new max. A fall of ≥ T below the current max confirms the max: count gain = max − last
     extreme, switch to down, and follow the min. Down is symmetric.
   - **End of the series.** Count the open leg (last extreme → current candidate), then the trailing leg (candidate
     → last sample). If the series never leaves the T band, the only leg is first → last.
   - **Summing.** Collect the legs and sum each sign with `math.fsum`, so the result does not depend on summation
     order.
   - **Consequences:** gain − loss = last − first (they telescope), and `gain_loss(reversed(y)) == (loss, gain)`
     holds exactly.

**Defaults and tuning.** `resample_step_m = 5.0` is fixed. `smoothing_window_m` and `gain_threshold_m` are tuned.
- **Starting values:** window **30 m**, threshold **10 m**. The checklist's "5 points" and "3 m" are examples that
  don't fit this data:
  - a point count isn't density-independent;
  - 3 m is GPS-jitter scale, and these are DEM artefacts.
- **My hand estimate** reads the extremes off the three raw profiles, with no smoothing and this exact hysteresis.
  It is accurate to about ±3 m per file. It is evidence that a feasible region exists; it does not replace tuning:

  | T (raw, no smoothing) | Modiin (ref 198) | Ben Shemen (ref 200) | Tel Hadid (ref 103) |
  | --- | --- | --- | --- |
  | 8 m | ≈ 204 (+3 %) | ≈ 257 (+28 %) ✗ | ≈ 110 (+7 %) |
  | 10 m | ≈ 204 (+3 %) | ≈ 219 (+9.5 %) | ≈ 102 (−1 %) |
  | 11 m | ≈ 204 (+3 %) | ≈ 198 (−1 %) | ≈ 102 (−1 %) |
  | 12 m | ≈ 193 (−3 %) | ≈ 186 (−7 %) | ≈ 94 (−9 %) |

  Tel Hadid's reference counts its 11–13 m bumps, and Ben Shemen's does not count its 10–11 m ones. The feasible
  band is therefore narrow: about 10.5–12 m on raw data, a little lower once smoothing shaves the peaks. Ten
  percent on Tel Hadid **is** reachable with a principled method. The risk is a thin margin, not infeasibility.
- **Tuning procedure (backend; not committed as code).**
  - **Grid:** window ∈ {20, 30, 40, 60, 80} m × T ∈ {3.0, 3.5, …, 15.0} m.
  - **Score:** for each point, the gain % error on **every** valid fixture with elevation. Today that is 6 files:
    the 3 AllTrails files plus the `rte`, > 10k and multi-segment ones.
  - **Pick:** among the points where every file is within ±10 %, choose the one that maximises the *minimum*
    margin (10 % − |error|). Break ties by the smaller window, then the smaller T.
  - **Record:** the chosen values go into `params.py` with a comment pointing here. The grid table (or its
    best-row summary plus the neighbours) goes into the backend report, and QA's per-fixture table into
    `PROGRESS.md`.
  - **Leaving the grid** (a value outside it, or a different method) is an ADR amendment.
- **Forbidden:**
  - per-file or per-`creator` parameters;
  - excluding a fixture;
  - loosening the 10 % gate.
- **If no grid point is feasible:** stop and escalate to the manager with the grid table. The options to present:
  1. a median pre-filter, which kills single-cell DEM spikes without lowering broad peaks (an ADR amendment);
  2. a per-elevation-source threshold, once more sources exist;
  3. a gate the manager accepts for DEM-elevation routes.

**3.5 Simplify: ranked Ramer–Douglas–Peucker to `max_points` (500).**
- **Input up to 500 points:** returned unchanged. The cap is a payload cap, and dropping collinear points under it
  gains nothing.
- **Distance space:** a local equirectangular projection in metres, x = R·cos φ₀·Δλ and y = R·Δφ.
  - φ₀ is the midpoint of the track's latitude range.
  - Δλ is unwrapped relative to the first point into (−180°, 180°], so tracks across the antimeridian work.
  - Distances are horizontal only; elevation is not part of the RDP metric.
  - Each point's distance is measured to the *segment*, not the infinite line, so the degenerate chord of a loop
    (start == end) gives the distance to that point.
- **Strategy:** compute every point's **RDP significance** once, with an iterative explicit stack and **no
  recursion**. A 10k-point track could exceed Python's recursion limit and produce a 500.
  - sig(endpoints) = ∞.
  - When splitting (a, b) at the farthest point i: sig(i) = min(d_max, sig(parent split)).
  - The clamp makes {i : sig(i) > ε} exactly RDP(ε)'s output for every ε, so this *is* RDP, with the ε that
    lands on the budget found implicitly. No binary search, and no "≤ 500 but which ε" ambiguity.
- **Selection:** the forced indices {0, n−1, high point} plus the top `max_points − |forced|` remaining indices by
  (significance descending, index ascending), returned sorted by index. Output = exactly min(n, max_points) points.
- **Cost:** O(n log n) on real tracks and O(n²) in the pathological worst case (see follow-ups).

**3.6 High point.** The first index of the maximum raw elevation, which keeps it deterministic on plateaus. It is
in `points` because simplify forces it, so `max(p.elev_m for p in points) == max_elev_m` holds.

**3.7 Too few points.** After merging and de-duplication, fewer than 2 points → `too_few_points`. ≥ 2 distinct
points then gives L > 0, except for the degenerate case of the same pole at different longitudes, which §3.4 step 1
handles.

**3.8 `is_loop`:** `geodesic_distance(start, end) ≤ loop_threshold_m` (200 m, inclusive). An out-and-back returns
to its start, so it is a loop; the brief requires `true`. A one-way route is `false`.

**3.9 Name.** The first non-blank of: metadata name → track/route name → filename stem → `"Untitled route"`.
- **Filename stem:** keep the text after the last `/` or `\` (some browsers send full paths), drop the last
  `.ext`, then turn `_` into a space (AllTrails filenames use underscores).
- **Every candidate is normalised the same way:** strip control characters (Unicode `Cc`), collapse whitespace runs
  to one space, trim, and cut to 200 code points.
- The router passes `UploadFile.filename`, which may be `None`.

**3.10 Upload size: three layers, all before any GPX parsing, none of them reading an unbounded body.**
- `MAX_UPLOAD_BYTES = 10 * 1024 * 1024` (10 MiB; the user-facing copy says "10 MB"). A file of exactly
  `MAX_UPLOAD_BYTES` is accepted, and one byte more is rejected.
- **Layer 1: `Content-Length` pre-check.** `UploadLimitRoute` is the router's `route_class`, the FastAPI "custom
  APIRoute" pattern. Its handler wrapper raises `ApiError(413, "file_too_large")` before reading anything if the
  header says more than `MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES` (64 KiB for the boundary and part headers).
  Browsers' `FormData` uploads always send `Content-Length`.
- **Layer 2: streaming cap.** The wrapper hands FastAPI a `BodyLimitRequest`, whose `stream()` (the public method
  Starlette's form parser consumes) counts bytes and raises the same `ApiError` once the body passes that limit.
  This covers chunked bodies and lying headers. The multipart spool is therefore bounded at about 10 MiB + 64 KiB.
- **Layer 3: exact file length.** The handler reads `await file.read(MAX_UPLOAD_BYTES + 1)`. If it gets more than
  `MAX_UPLOAD_BYTES`, the answer is 413. This holds no matter what `UploadFile.size` says.
- **Rejected:**
  - a FastAPI dependency, because the body is parsed before dependencies run;
  - an app-wide ASGI middleware, which would give JSON endpoints a "file" error code;
  - reading `Request` by hand, which loses the OpenAPI multipart schema the generated client needs.
- **Threadpool.** The handler is `async def`. It awaits the read, then runs `summarise_gpx` via Starlette's
  `run_in_threadpool`, so a CPU-bound parse of about 0.5 s doesn't block the event loop (or `/health`) for the
  other 79 concurrent requests.

**3.11 XML safety: stdlib only, no defusedxml; we forbid DTDs ourselves.**
- **Which parser gpxpy uses:** it parses with `lxml` if that is importable, otherwise `xml.etree.ElementTree`
  (expat). lxml is not in our tree, so it is ElementTree.
- **Python docs, per ElementTree vulnerability:**
  - external entities: safe (`ParseError`);
  - billion laughs and quadratic blowup: safe with expat ≥ 2.4.1;
  - large tokens: safe with expat ≥ 2.6.0.
- **The guard: `check_gpx_prolog(data)`.** Before gpxpy runs, it drives `xml.parsers.expat` over the raw bytes with
  three handlers:
  - `StartDoctypeDeclHandler` → `invalid_gpx` "DTDs are not allowed";
  - `EntityDeclHandler` → the same;
  - `StartElementHandler` records the root's local name, then **stops the scan** by raising a private sentinel. A
    DOCTYPE can only precede the root, so the scan costs only the prolog.
- **What the guard rejects:** an `ExpatError` before the root (`invalid_gpx` with line/column), no root at all, or a
  root whose local name is not `gpx`. That last check is how the KML fixture fails: gpxpy doesn't check the root
  element and would return an empty GPX.
- **Why this is enough:** GPX is defined by an XSD and never needs a DTD. Every entity attack needs a DTD, so
  rejecting DTDs removes XXE, billion laughs, quadratic blowup and DTD retrieval no matter which expat version or
  parser gpxpy picks. Large-token quadratic parsing is bounded by the 10 MiB cap and fixed in expat ≥ 2.6. A test
  asserts `pyexpat.EXPAT_VERSION ≥ 2.6.0`; see the follow-ups for the Docker image.
- **defusedxml is rejected:** a new dependency, and gpxpy calls ElementTree internally, so it would need
  monkey-patching (`defuse_stdlib`) for no protection beyond the guard.

### 4. Dependencies
| Package | Where | Why | License | Maintenance | Types (mypy strict) | Approval |
| --- | --- | --- | --- | --- | --- | --- |
| **gpxpy** | runtime | the roadmap's parser | Apache-2.0 | 1.6.2 (2023-11); slow cadence, but a stable format and no deps | ships `py.typed` (inline hints; the project requires mypy-clean code) | in stack |
| **python-multipart** | runtime | FastAPI/Starlette need it for any `File()`/`Form()` ("To receive uploaded files, first install python-multipart"); without it the route fails at import | Apache-2.0 | 0.0.32 (2026-06), maintained by Kludex (Starlette's maintainer) | not imported by our code | **needs manager approval** (not in the CLAUDE.md list; it is FastAPI's own optional dependency) |
| **Hypothesis** | dev | property and fuzz tests | MPL-2.0 | active | ships `py.typed` | in stack |
| **pytest-benchmark** | dev | named by the roadmap for the benchmark | BSD-2-Clause | 5.3.0 (2026-08), supports pytest 9 | "minimal typing" since 5.2. If mypy reports no `py.typed`, type the fixture parameter with a local `Protocol` in the test (no `ignore_missing_imports`) | **needs manager approval** (named by the roadmap, not in the CLAUDE.md list) |
| **benchmark-action/github-action-benchmark** | CI action, pinned by SHA like the others | named by the roadmap: stores the baseline and alerts | MIT | active, `@v1` line | n/a | **needs manager approval** (new third-party action) |
| geographiclib | — | rejected (§3.3) | | | | — |
| defusedxml | — | rejected (§3.11) | | | | — |
| lxml | — | must **not** be added: gpxpy would switch parsers silently, changing behaviour and benchmark numbers (the guard keeps it safe either way) | | | | — |

`pyproject` changes: add `gpxpy` and `python-multipart` to `dependencies`, add `hypothesis` and `pytest-benchmark` to
`dev`, and add `--benchmark-disable` to `addopts`. Benchmark tests then run once, as plain tests, inside `api-test`
under coverage, and only the benchmark job times them.

**Why not the stack?**
- **python-multipart:** nothing in the stack parses `multipart/form-data`. Starlette delegates to this package, and
  writing our own multipart parser would be a worse risk.
- **pytest-benchmark:** the stack has no benchmarking tool. Hand-rolled `perf_counter` loops wouldn't produce the
  JSON that github-action-benchmark consumes.
- **github-action-benchmark:** the roadmap names it. The alternative, a hand-written comparison script, would be
  new code to maintain and test, with no charting or history.

### 5. Benchmark (devops implements; QA writes the test)
**What is measured.** The test is `tests/routes/test_benchmark.py::test_parse_largest_fixture`.
- **Call:** `benchmark.pedantic(summarise_gpx, args=(bytes, name), rounds=10, warmup_rounds=1, iterations=1)`. The
  fixture is `derived-ben-shemen-over-10k-points.gpx`, and its bytes are read *outside* the timed call. This is
  the full pure pipeline, not HTTP: transport noise is excluded, and the HTTP timing is the checkpoint's
  `TestClient`/deployed-URL measurement.
- **Correctness:** the test also asserts the result (distance within 2 %), so a "fast because broken" change fails.

**Statistic: `min`, not `mean`/`ops`.**
- For deterministic CPU-bound code, noise only ever adds time, so `min` is the most stable estimator.
- github-action-benchmark's built-in `tool: pytest` compares `ops` (1/mean), which is outlier-sensitive.
- So the job converts pytest-benchmark's JSON with `jq` into `customSmallerIsBetter`:
  - `value` = `stats.min` in seconds;
  - `name` = the test name;
  - `range` = the IQR;
  - `extra` = median and rounds.

**Run options.** `uv run --frozen pytest tests/routes/test_benchmark.py --benchmark-enable --benchmark-only --no-cov
--benchmark-json=…`. `--no-cov` matters: coverage tracing distorts timing, and a subset run would trip
`--cov-fail-under`.

**Regression rule: within one job, on one runner (A/B), not against a stored number from another machine.**
- **Why A/B:** shared GitHub runners vary by CPU model and neighbours, and cross-run differences of 10–30 % are
  common. A required 20 % gate against a cross-machine baseline would flake.
- **On a PR:**
  1. Check out the base SHA and run the benchmark. Feed the result to the action with
     `external-data-json-path: ./bench/ab.json`, `save-data-file: true` and no alert. This is the stored baseline.
  2. Check out the head SHA and run it again. Feed the action the same file with `alert-threshold: "120%"`,
     `fail-on-alert: true`, `fail-threshold: "120%"`, `save-data-file: false` and `summary-always: true`.
  3. The job **also** fails if head `min ≥ 2.0 s`, the absolute checkpoint ceiling.
  4. If the base has no benchmark test (this step's own PR), skip the comparison with a notice, but keep the
     absolute check.
  5. Permissions: `contents: read` only.
- **On push to `main`:** run the head only and append to the history with the action's `external-data-json-path`,
  persisted with `actions/cache`.
  - Key `benchmark-${{ github.sha }}` with restore-keys `benchmark-`; cache keys are immutable, so each run saves
    a new one.
  - `fail-on-alert: false`. The PR already gated, and a post-merge failure can't block anything.
  - Skip the job for the nightly/`fresh-deps` `workflow_call`, so other dependency versions don't pollute the
    history.
- **Path filter:** the job follows `changes.api` like `api-test`; a skip counts as passing. Its name, `benchmark`, is
  a required-check contract.

**Baseline storage options** (for the main-branch history; the PR gate needs none):
- **`actions/cache` (chosen):**
  - no write token, no new branch and **no manager action**;
  - PRs can read caches created on `main`;
  - risk: the cache is evicted after 7 days without access, and the next run then starts a fresh history. That
    is harmless, because the gate is A/B.
- **gh-pages branch:**
  - gives a chart;
  - needs `contents: write` in a job that runs repo code, plus a manager action: create the `gh-pages` branch and
    optionally enable Pages;
  - rejected for now, and can be adopted later without touching the gate.
- **Artifacts:** rejected. Reading another run's artifact needs `actions: read`, run-ID lookup and retention
  management.

### 6. How it is tested
See "How it is tested" below; it is part of the decision.

## Interface
```python
# app/routes/params.py — the only home for parameters and limits
MAX_UPLOAD_BYTES: Final = 10 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES: Final = 64 * 1024
MAX_SUMMARY_POINTS: Final = 500
EARTH_RADIUS_M: Final = 6_371_008.8
MAX_NAME_LENGTH: Final = 200
UNTITLED_ROUTE_NAME: Final = "Untitled route"

@dataclass(frozen=True, slots=True)
class ParseParams:
    resample_step_m: float = 5.0
    max_resample_points: int = 100_000
    smoothing_window_m: float = 30.0      # tuned per §3.4; starting value
    gain_threshold_m: float = 10.0        # tuned per §3.4; starting value
    loop_threshold_m: float = 200.0
    max_points: int = MAX_SUMMARY_POINTS  # 3 <= max_points <= MAX_SUMMARY_POINTS
    def __post_init__(self) -> None: ...  # ValueError on out-of-range values

DEFAULT_PARAMS: Final = ParseParams()
```
```python
# app/routes/errors.py
class RouteParseError(Exception):
    code: ClassVar[Literal["invalid_gpx", "too_few_points"]]
    def __init__(self, message: str) -> None: ...
    @property
    def message(self) -> str: ...
class InvalidGpx(RouteParseError): ...        # code = "invalid_gpx"
class TooFewPoints(RouteParseError): ...      # code = "too_few_points"

# app/routes/track.py
@dataclass(frozen=True, slots=True)
class RawPoint:
    lat: float
    lon: float
    elev_m: float | None                      # None: missing or non-finite <ele>

@dataclass(frozen=True, slots=True)
class RawTrack:
    points: tuple[RawPoint, ...]              # chosen source, merged in document order, validated, NOT de-duplicated
    source_format: SourceFormat               # from app.models.route
    metadata_name: str | None
    track_name: str | None                    # first non-blank <trk><name> (or <rte><name>), raw

# app/routes/xml_guard.py
def check_gpx_prolog(data: bytes) -> None: ...   # raises InvalidGpx (DTD/entity, malformed prolog, no root, root != gpx)

# app/routes/parse.py — the only module that imports gpxpy
def parse_gpx(data: bytes) -> RawTrack: ...      # raises InvalidGpx only
def drop_consecutive_duplicates(points: Sequence[RawPoint]) -> tuple[RawPoint, ...]: ...

# app/routes/geo.py
def geodesic_distance(a: RawPoint, b: RawPoint) -> float: ...                # haversine, metres, 2-D
def cumulative_distance(points: Sequence[RawPoint]) -> tuple[float, ...]: ...  # [0.0, ...], len == len(points)
def is_loop(start: RawPoint, end: RawPoint, *,
            threshold_m: float = DEFAULT_PARAMS.loop_threshold_m) -> bool: ...

# app/routes/elevation.py
def smooth_elevation(dist_m: Sequence[float], elev_m: Sequence[float], *,
                     window_m: float = DEFAULT_PARAMS.smoothing_window_m,
                     step_m: float = DEFAULT_PARAMS.resample_step_m,
                     max_samples: int = DEFAULT_PARAMS.max_resample_points) -> tuple[float, ...]: ...
    # resampled uniform grid (both ends included), centred moving average with symmetric shrinking ends
def gain_loss(elev_m: Sequence[float], *,
              threshold_m: float = DEFAULT_PARAMS.gain_threshold_m) -> tuple[float, float]: ...  # (gain, loss)
def high_point_index(elev_m: Sequence[float]) -> int: ...    # first index of the maximum; ValueError if empty

# app/routes/simplify.py
def rdp_significance(points: Sequence[RawPoint]) -> tuple[float, ...]: ...  # inf at both ends; iterative
def simplify(points: Sequence[RawPoint], *, keep: Collection[int] = (),
             max_points: int = DEFAULT_PARAMS.max_points) -> tuple[int, ...]: ...  # sorted indices, len == min(n, max_points)

# app/routes/naming.py
def route_name(metadata_name: str | None, track_name: str | None, filename: str | None) -> str: ...

# app/routes/summary.py — the whole pipeline; the benchmark target
def summarise_gpx(data: bytes, filename: str | None,
                  params: ParseParams = DEFAULT_PARAMS) -> RouteSummary: ...   # raises RouteParseError only
```
```python
# app/models/route.py
Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]
NonNegMetres = Annotated[float, Field(ge=0)]
SourceFormat = Literal["trk", "rte"]
ElevationSource = Literal["file", "lookup", "none"]

class LatLonElev(BaseModel):          # model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    lat: Latitude
    lon: Longitude
    elev_m: float | None

class TrackPoint(BaseModel):          # same config
    lat: Latitude
    lon: Longitude
    elev_m: float | None
    dist_m: NonNegMetres

class RouteSummary(BaseModel):        # same config
    name: Annotated[str, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
    distance_m: NonNegMetres
    gain_m: NonNegMetres | None
    loss_m: NonNegMetres | None
    min_elev_m: float | None
    max_elev_m: float | None
    high_point: LatLonElev | None
    start: LatLonElev
    end: LatLonElev
    is_loop: bool
    points: Annotated[list[TrackPoint], Field(min_length=2, max_length=MAX_SUMMARY_POINTS)]
    has_elevation: bool
    elevation_source: ElevationSource
    source_format: SourceFormat
    point_count_original: Annotated[int, Field(ge=2)]

# app/models/errors.py
ErrorCode = Literal["bad_request", "not_found", "method_not_allowed", "file_too_large", "invalid_gpx",
                    "too_few_points", "validation_error", "http_error", "internal_error"]

class FieldError(BaseModel):
    loc: list[str | int]
    msg: str
    type: str

class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    detail: list[FieldError] | None
```
```python
# app/errors.py
class ApiError(StarletteHTTPException):        # Starlette's HTTPException so FastAPI's body reader re-raises it
    code: ErrorCode
    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None: ...
def error_body(code: ErrorCode, message: str, detail: list[FieldError] | None = None) -> dict[str, object]: ...
def install_error_handlers(app: FastAPI) -> None: ...  # StarletteHTTPException + RequestValidationError
ERROR_RESPONSES: Final[dict[int | str, dict[str, Any]]]  # Any: FastAPI's `responses=` parameter type

# app/body_limit.py
class BodyLimitRequest(Request):
    def __init__(self, scope: Scope, receive: Receive, *, max_body_bytes: int) -> None: ...
    async def stream(self) -> AsyncGenerator[bytes, None]: ...  # raises ApiError(413, "file_too_large")
class UploadLimitRoute(APIRoute):
    max_body_bytes: ClassVar[int] = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]: ...  # Any: FastAPI's signature

# app/routers/routes.py
router = APIRouter(prefix="/v1/routes", tags=["routes"], route_class=UploadLimitRoute)

@router.post("/parse", responses=ERROR_RESPONSES, summary="Parse a GPX file into a route summary")
async def parse_route(
    file: Annotated[UploadFile, File(description="GPX 1.0/1.1 file, at most 10 MB")],
) -> RouteSummary: ...
    # read(MAX_UPLOAD_BYTES + 1) → 413 | run_in_threadpool(summarise_gpx, data, file.filename)
    # RouteParseError → ApiError(422, e.code, e.message)

# app/middleware.py — RequestIdMiddleware's 500 body becomes error_body("internal_error", "Internal Server Error")
# app/main.py — create_app: install_error_handlers(app); app.include_router(routes.router)
```
```mermaid
flowchart LR
  subgraph edge [I/O edge]
    RT[routers/routes.py parse_route] --> BL[body_limit.UploadLimitRoute]
    RT --> ER[errors.py ApiError + handlers]
  end
  subgraph pure [app/routes — pure]
    SUM[summary.summarise_gpx] --> XG[xml_guard] & PG[parse.parse_gpx → RawTrack] & GEO[geo] & ELE[elevation] & SIM[simplify] & NM[naming]
    PG --> GPXPY[(gpxpy)]
    SUM --> PAR[params]
  end
  RT -- run_in_threadpool --> SUM
  SUM --> MR[models/route.py]
  ER --> ME[models/errors.py]
  MR --> PAR
```
Imports point one way: `routers → routes → models`. `app/routes/*` never imports fastapi/starlette, and
`app/models/*` never imports from `app/routes/` except `params`. `params` imports nothing from the app.
`app/routes/__init__.py` stays **empty**, with no re-exports; otherwise `models.route → routes.params` would run
`routes/__init__` → `summary` → `models.route`, a circular import. Callers import `app.routes.summary` directly.

## Options considered
- **geographiclib (Karney)** — rejected: a new dependency, about 10–30× slower per pair, and its ≤ 0.56 % gain in
  accuracy is invisible inside a 2 % gate.
- **3-D distance** — rejected: source apps report horizontal length, and it would add up to about 0.5 % on steep
  routes.
- **Not counting segment jumps** — rejected: `dist_m` would be discontinuous on one drawn line, segment boundaries
  would have to run through smoothing and RDP, and the jump is distance the hiker walks.
- **Point-count moving average (checklist "5 points")** — rejected: not density-independent, so the > 10k fixture
  would barely be smoothed.
- **Distance window evaluated at the raw points (no resampling)** — rejected: mixed spacing within one file still
  weights dense stretches more, and the result isn't exactly reversal-symmetric.
- **Step accumulation ("add the change once |Δ| ≥ T, then reset the reference")** — rejected: it isn't symmetric
  under reversal (it fails the roadmap's property test) and under-counts every climb by up to T.
- **A median filter instead of a moving average** — not chosen: the checklist names a moving average. It is kept as
  the first escalation option (§3.4).
- **Smoothed elevations in `points[]` / smoothed min/max** — rejected for 1.2: raw values are what the file says,
  and they keep `max(points.elev_m) == max_elev_m` exact.
- **Partial elevation counted as `has_elevation: true` with gaps** — rejected: clients would draw holes, and gain
  would be computed over interpolated gaps. The lookup in 1.3 is the fix.
- **`0` instead of `null` for missing elevation** — rejected: it is indistinguishable from a flat route.
- **RDP binary search on ε** — rejected: about 30 full RDP runs, and it lands at "≤ 500" with an ε tolerance.
  Ranked significance gives exactly the budget in one pass.
- **Recursive RDP** — rejected: the recursion limit on long or pathological tracks would cause a 500.
- **Simplifying inputs of ≤ 500 points** — rejected: nothing gained under the cap.
- **Size check via a dependency, app-wide middleware, or reading the raw `Request`** — rejected: §3.10.
- **Reading the whole body and then checking its length** — rejected: unbounded memory on an in-memory filesystem.
- **defusedxml** — rejected: §3.11.
- **Trusting expat versions alone** — rejected: the Docker image's expat comes from Debian, not from us, and the
  guard is cheap.
- **`code: str` in `ErrorResponse`** — rejected: a typed union gives exhaustiveness checks in TypeScript. Forward
  compatibility comes from the "unknown code ⇒ generic error" client rule.
- **FastAPI's default `{"detail": …}` errors** — rejected: three shapes for clients to parse, and no stable codes.
- **Algorithm parameters in `Settings`/env** — rejected: environments could drift from the tuned, tested values.
- **github-action-benchmark `tool: pytest` (ops = 1/mean)** — rejected: the mean is outlier-sensitive on shared
  runners.
- **A gate against a stored baseline from another runner** — rejected: cross-machine noise is of the same order as
  the 20 % threshold, so a required check would flake.
- **gh-pages storage** — deferred: it needs a write token and a manager action, and the gate doesn't need it.
- **Artifact storage** — rejected: cross-run artifact plumbing.
- **Benchmarking through `TestClient`** — rejected for the regression gate: it adds HTTP and multipart noise. HTTP
  timing stays a checkpoint measurement.

## Consequences
- **Easier:**
  - One pure entry point, `summarise_gpx`, is what endpoint tests, property tests, the fuzz test and the benchmark
    all hit.
  - gpxpy is confined to one module, so replacing it later (e.g. with a streaming ElementTree parser for speed)
    touches only `parse.py`.
  - Every error the API returns has one shape and a stable code, and the client generated for 1.10/Expo is fully
    typed, errors included.
  - The gain method is density-independent and exactly reversal-symmetric, and its parameters are in metres.
  - XML attack surface: no DTDs, whatever expat or parser is present.
  - The benchmark gate is robust to runner variance, and it needs no manager console work.
- **Harder later:**
  - **Gain defaults are tuned on 3 AllTrails DEM routes in the low hills of central Israel.** When the Komoot,
    Strava and watch fixtures land (1.1 follow-ups), the tuning must be re-run across the whole corpus. A single
    threshold may then conflict across elevation sources (GPS/barometric vs DEM), which is a manager decision
    (§3.4 escalation options).
  - **A file with one missing `<ele>` loses its whole profile** until 1.3 supplies elevation. 1.3 may revisit this,
    for example by filling short gaps.
  - **UTF-8 only.** A GPX file declared in Latin-1 with non-ASCII bytes, or saved as UTF-16, gets `invalid_gpx`.
  - **Disjoint multi-segment files** (e.g. two days with a car shuttle between them) get a straight-line jump added
    to their distance.
  - **Changing the 500-point cap** changes the OpenAPI (`maxItems`), which is a visible contract diff, as intended.
  - **The 500 body change** breaks anything that parsed `{"detail": "Internal Server Error"}`. Nothing does today;
    the web client classifies errors by status.
  - **The benchmark compares PR against base.** A PR that changes the benchmark itself compares two different
    workloads, and reviewers must read the summary.
  - **A 10 MiB hostile file** (about 170k points) costs several CPU-seconds, and on one instance a handful of them
    stalls the API (follow-ups).

## How it is tested
All tests run with no network (`--disable-socket`). QA writes the acceptance, property, endpoint, fuzz and benchmark
tests red-first in `tests/routes/`. Backend adds unit tests for internals it introduces.

- **Pure units, fast and table-driven:**
  - **`geodesic_distance`:**
    - known pairs: one degree of latitude at the equator ≈ 111 195 m, and a few points around Tel Aviv against
      precomputed values;
    - symmetric; zero for equal points; antimeridian pairs.
  - **`drop_consecutive_duplicates`:** keeps the first; removes duplicates across a segment boundary; leaves
    non-consecutive repeats alone.
  - **`smooth_elevation`:**
    - constant → constant; a linear profile is returned unchanged, endpoints included;
    - window 0 → plain resample; endpoints equal raw;
    - L = 0 and repeated distances don't raise;
    - the sample count respects `max_samples`;
    - **density independence:** the series from a track and from its 14× linear densification agree within 0.05 m.
  - **`gain_loss`:**
    - monotone climb → (Δ, 0);
    - oscillations below T inside a climb add nothing;
    - T = 0 → total positive and negative variation;
    - band-only series → first-to-last leg;
    - the worked examples from §3.4 (`0, 5, −10` with T = 8 → (5, 15); reversed → (15, 5)).
  - **`is_loop`:**
    - **synthetic tracks, no fixtures:**
      - out-and-back: 2 km out along a bearing, back on a 10 m offset → `true`;
      - one-way: 2 km straight → `false`;
    - boundary: ends 199 m apart → `true`, 201 m → `false` (positions computed with `geodesic_distance`).
  - **`simplify` / `rdp_significance`:**
    - n ≤ 500 → identity;
    - n > 500 → exactly 500, sorted, containing 0, n−1 and the high point even when RDP alone would drop it (a
      spike on a straight line);
    - a loop with start == end works;
    - a 20 000-point straight line and a spiral don't hit the recursion limit;
    - `{i : sig(i) > ε}` equals a naive recursive reference RDP(ε), the latter written in the test.
  - **`route_name`:** metadata → track → `C:\x\My_Hike.GPX` gives "My Hike" → `None` gives "Untitled route";
    whitespace-only names skipped; control characters stripped; the 200 code-point cut; Hebrew names kept.
  - **`check_gpx_prolog`:**
    - billion-laughs document, XXE (`SYSTEM "file:///…"` pointing at a temp file whose content must not appear in
      any output), external DTD reference, internal subset → `InvalidGpx`;
    - KML root → `InvalidGpx`; GPX 1.0, 1.1 and no-namespace roots pass;
    - a UTF-8 BOM passes;
    - `pyexpat.EXPAT_VERSION ≥ 2.6.0`.
  - **`parse_gpx`:**
    - `trk` preferred over `rte`; `rte` fallback;
    - multiple tracks and segments merged in order;
    - lat 91, lon NaN or missing lat → `InvalidGpx`;
    - `<ele>nan</ele>` → `None`; non-UTF-8 bytes → `InvalidGpx`;
    - waypoint-only → empty points (and then `too_few_points` from the pipeline).
  - **`ParseParams`:** invalid values raise.
- **Fixture acceptance (parametrised with `tests.fixtures.loader`):**
  - **Distance:** within 2 % on every `valid_fixtures()`.
  - **Gain:** within 10 % on every valid fixture with `has_elevation`. QA's report prints the per-fixture % error
    table for `PROGRESS.md`.
  - **Invalid fixtures:** every `invalid_fixtures()` raises `RouteParseError` with `code == expected.expected_error`.
  - **Fixture fields:**
    - `has_elevation` and `is_loop` match `expected.json`;
    - the `rte` fixture has `source_format == "rte"`;
    - the no-elevation fixture has `gain_m`, `loss_m`, `min/max_elev_m` and `high_point` all `None`, every
      `elev_m` `None`, and `elevation_source == "none"`.
  - **Multi-segment jump counted:** `parent.distance_m − multi.distance_m < 5 m`; the alternative would be ≈ 34 m.
    Plus a synthetic two-segment track where distance == seg₁ + straight jump + seg₂.
  - **Invariants on every valid fixture:**
    - `len(points) ≤ 500`; `points[0]` == start and `points[-1]` == end;
    - `high_point` is in `points`, and `max(points.elev_m) == max_elev_m`;
    - `dist_m` never decreases, starts at 0 and ends at `distance_m`;
    - `point_count_original` ≥ `len(points)`.
- **Hypothesis properties (strategy: random tracks):**
  - The strategy draws 2–200 points: a start point anywhere, including near ±89.9° and the antimeridian, then
    steps of 0–500 m on random bearings, with random duplicates, finite elevations from −400 to 8 848 m, and
    optional missing `<ele>`.
  - The tracks are written to GPX by a test helper (gpxpy can write GPX) as `trk`, `rte` or multi-segment.
  - **Sign:** `distance_m ≥ 0`, `gain_m ≥ 0`, `loss_m ≥ 0` (or `None` without elevation).
  - **Reversal:** the reversed track has the same distance (rel 1e-9), and gain and loss swap (abs 1e-6 m). At the
    unit level, `gain_loss(reversed(y)) == (loss, gain)` **exactly**, for arbitrary finite floats and T ≥ 0.
  - **Telescoping:** `gain − loss ≈ smoothed[-1] − smoothed[0]`.
  - **Robustness:** `summarise_gpx` on any generated track either returns or raises `TooFewPoints`, never anything
    else.
  - Use `deadline=None` for pipeline-level properties (they run under coverage in CI).
- **Fuzz, "never 500":**
  - **Pure layer:** `summarise_gpx(st.binary(max_size=64 KiB))` and mutated fixtures (truncation at a random
    offset, byte flips, inserted XML fragments such as `<!DOCTYPE`, `<trkpt lat="x">` and deep nesting) raise only
    `RouteParseError`.
  - **HTTP layer:** a smaller set of the same inputs POSTed through `TestClient` with
    `raise_server_exceptions=True` must give a status in {200, 413, 422}. Any exception fails the test with its
    traceback.
- **Endpoint (`TestClient`):**
  - 200 for every valid fixture, with the body validating as `RouteSummary`;
  - 422 `invalid_gpx` (truncated, KML, empty file), 422 `too_few_points` (1-point file, and two identical points);
  - 422 `validation_error` with a missing `file` field, with `detail[0].loc == ["body", "file"]` and no `input` key;
  - **Size limits:**
    - 413 `file_too_large` for an 11 MB file (`Content-Length` path);
    - 413 for a chunked/streamed body with no `Content-Length` (generator body);
    - a valid GPX padded to exactly `MAX_UPLOAD_BYTES` → 200, and `MAX_UPLOAD_BYTES + 1` → 413;
  - 404/405 have the `ErrorResponse` shape, and 405 keeps `Allow`;
  - `X-Request-ID` is present on errors;
  - the updated `test_errors.py` asserts the `internal_error` body.
- **Contract:** `api-contract` regenerates `openapi.json`/`schema.d.ts`. A QA schema test asserts:
  - `parseRoute` exists;
  - the 200 schema is `RouteSummary`;
  - 400/413/422/500 reference `ErrorResponse`;
  - no `HTTPValidationError` component exists;
  - `points.maxItems == 500`;
  - the nullable fields are required with a `null` branch.
- **Benchmark:** §5, in the `benchmark` job. Under `api-test` the same test runs once with benchmarking disabled, as
  a correctness test.
- **Checkpoint (QA, recorded in `PROGRESS.md`):** the per-fixture table; `TestClient` timing of the > 10k fixture;
  the post-merge timing against the deployed URL (curl/httpx, outside unit tests); fuzz runs with 0 × 500.
- **No e2e in 1.2:** there is no screen. 1.10 adds the UI path.

## Manager decisions needed
1. **Approve the new dependencies:**
   - `python-multipart` (runtime);
   - `pytest-benchmark` (dev);
   - `benchmark-action/github-action-benchmark` (CI action, SHA-pinned).
2. **Confirm the path `/v1/routes/parse`** (already pending in the brief).
3. **Mark `benchmark` required** after merge (already in the brief).

Conditional: **only if** no parameter point in §3.4's grid meets 10 % on every fixture. In that case, backend stops
and the tech lead brings the grid table and the three options to the manager.

## Follow-ups (out of scope for this ADR)
- **CORS:** `create_app` allows only `GET, OPTIONS`. The 1.10 web upload needs `POST` in `allow_methods`; add it
  with 1.10, or in 1.2 if the tech lead prefers, since the checkpoint's deployed timing uses curl and needs no CORS.
- **Docker image expat:** `python:3.12-slim` builds against Debian's system expat. Devops could add a build-time
  `python -c "import pyexpat; print(pyexpat.EXPAT_VERSION)"` check. The DTD guard makes this defence-in-depth only.
- **CPU cost of hostile uploads:**
  - A 10 MiB file of about 170k points takes several seconds, through gpxpy and the O(n²) worst case of RDP.
  - With max-instances 1 this is a cheap DoS.
  - Options for a later step: a point cap (`too_many_points`), rate limiting before Phase 3 (which ADR 0003
    already flags), or a streaming parser.
- **Payload size:** about 500 × 4 unrounded floats ≈ 50 KB of JSON. Consider rounding at the edge (lat/lon 6 dp,
  metres 1 dp) or `GZipMiddleware` when 1.10/1.11 set the performance budget.
- **Elevation chart (1.10):** RDP is horizontal only, so a 500-point profile can lose small elevation features.
  The high point is kept. If UX wants a faithful profile, add a separate distance–elevation simplification.
- **Re-tune gain** when the deferred Komoot/Strava/watch fixtures land (see "Harder later").

## References
- gpxpy source, `gpxpy/parser.py`: lxml if importable, else `xml.etree` (c)ElementTree; bytes decoded with
  `.decode()`; XML errors → `GPXXMLSyntaxException`; no root-name check. https://github.com/tkrajina/gpxpy/blob/master/gpxpy/parser.py
- gpxpy `py.typed` and `package_data={"gpxpy": ["py.typed"]}`: https://github.com/tkrajina/gpxpy/tree/master/gpxpy ,
  https://github.com/tkrajina/gpxpy/blob/master/setup.py ; PyPI 1.6.2 (Apache-2.0): https://pypi.org/project/gpxpy/
- Python XML vulnerabilities table and expat footnotes (2.4.1 billion laughs/quadratic, 2.6.0 large tokens; etree
  external entities → `ParseError`): https://docs.python.org/3.12/library/xml.html
- FastAPI request files (python-multipart required; `SpooledTemporaryFile`): https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI custom Request and APIRoute class (`route_class`, Request subclass): https://fastapi.tiangolo.com/how-to/custom-request-and-route/
- FastAPI `fastapi/routing.py`: `from starlette.exceptions import HTTPException`; the body reader re-raises
  `HTTPException` and turns other exceptions into 400 "There was an error parsing the body"; default 422 added only
  when no 422/4XX/default response is declared. https://github.com/fastapi/fastapi/blob/master/fastapi/routing.py
- Starlette `requests.py` (`form()` parses from `self.stream()`; `max_files`/`max_fields`/`max_part_size` defaults)
  and `formparsers.py` (`spool_max_size = 1 MiB`; no total file-size limit; `MultiPartException` messages):
  https://github.com/encode/starlette/blob/master/starlette/requests.py , https://github.com/encode/starlette/blob/master/starlette/formparsers.py
- Cloud Run quotas (HTTP/1 request max 32 MiB; in-memory filesystem limited by instance memory): https://docs.cloud.google.com/run/quotas
- python-multipart 0.0.32 (Apache-2.0, maintainer Kludex): https://pypi.org/project/python-multipart/
- pytest-benchmark 5.3.0 (BSD-2-Clause) and its CLI options (`--benchmark-disable`/`--benchmark-enable`/`--benchmark-only`/`--benchmark-json`):
  https://pypi.org/project/pytest-benchmark/ , https://pytest-benchmark.readthedocs.io/en/latest/usage.html
- github-action-benchmark README (`alert-threshold`, `fail-on-alert`, `fail-threshold`, `external-data-json-path`
  with `actions/cache`, `save-data-file`, gh-pages permissions, advice against pushing from PRs; MIT):
  https://github.com/benchmark-action/github-action-benchmark ; `src/extract.ts` (`tool: pytest` uses `stats.ops`):
  https://github.com/benchmark-action/github-action-benchmark/blob/master/src/extract.ts
- WGS84 radii of curvature (a = 6 378 137 m, e² = 0.00669438) and the IUGG mean radius of 6 371 008.8 m; the
  sphere-error figures in §3.3 are computed from these.
- Repo: `docs/steps/1.2.md`, `docs/steps/1.1.md` ("Follow-ups for 1.2"), `api/tests/fixtures/gpx/expected.json`,
  `api/tests/fixtures/loader.py`, `api/app/main.py`, `api/app/middleware.py`, `api/tests/test_errors.py`,
  `.github/workflows/ci.yml`, ADRs 0001–0003.
