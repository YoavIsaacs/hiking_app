"""POST /v1/routes/parse with the elevation backfill, through the real wiring.

Every test builds the app with ``create_app`` and runs it WITH its lifespan
(``lifespan_client``), unless it says otherwise; Open-Meteo is the respx router in
``elevation_api``. Nothing here calls the client in isolation (ADR 0005 section 7).
"""

import json
import logging
import math
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.clients.elevation import ElevationClient, new_http_client
from app.config import Settings
from app.logging_config import JsonFormatter
from app.main import create_app
from app.middleware import REQUEST_ID_HEADER
from app.models.route import RouteSummary
from app.models.warnings import ELEVATION_UNAVAILABLE
from app.routes.params import DEFAULT_PARAMS
from app.routes.summary import lookup_point_count, summarise_gpx
from tests.elevation_support import (
    BEN_SHEMEN,
    MODIIN,
    TEL_HADID,
    ElevationApi,
    body_handler,
    connect_timeout,
    pair_of,
    query_pairs,
    raising_handler,
    read_timeout,
    recorded_table,
    status_handler,
    synthetic_elevation,
    synthetic_handler,
)
from tests.fixtures.loader import GPX_DIR, fixture_params, load_expected, valid_fixtures
from tests.routes.gpx_builders import Pt, gpx_bytes, straight_line
from tests.routes.http_helpers import URL, assert_error

NO_ELE = GPX_DIR / "derived-tel-hadid-no-ele.gpx"
PARENT = GPX_DIR / "alltrails-tel-hadid-loop.gpx"
ELE = re.compile(rb"<ele>[^<]*</ele>")
NULLABLE = ("gain_m", "loss_m", "min_elev_m", "max_elev_m", "high_point")
UNAVAILABLE = ELEVATION_UNAVAILABLE.model_dump()


def post(client: TestClient, data: bytes, name: str = "route.gpx") -> httpx.Response:
    response: httpx.Response = client.post(
        URL, files={"file": (name, data, "application/gpx+xml")}
    )
    return response


def no_ele_route(n: int, step_m: float = 135.0) -> tuple[bytes, list[Pt]]:
    pts = straight_line(n, step_m=step_m, ele=None)
    return gpx_bytes([pts]), pts


def assert_flagged(response: httpx.Response) -> dict[str, object]:
    """200, the stage-1 summary, and exactly the one warning (ADR 0005 section 6)."""
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    RouteSummary.model_validate(body)
    assert body["has_elevation"] is False
    assert body["elevation_source"] == "none"
    assert body["warnings"] == [UNAVAILABLE]
    assert all(body[f] is None for f in NULLABLE), body
    points = body["points"]
    assert isinstance(points, list) and 2 <= len(points) <= 400
    assert all(p["elev_m"] is None for p in points)
    assert body["start"]["elev_m"] is None and body["end"]["elev_m"] is None  # type: ignore[index]  # JSON object
    return body


def assert_backfilled(response: httpx.Response) -> dict[str, object]:
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    RouteSummary.model_validate(body)
    assert body["elevation_source"] == "lookup" and body["has_elevation"] is True
    assert body["warnings"] == []
    points = body["points"]
    assert isinstance(points, list) and all(p["elev_m"] is not None for p in points)
    return body


# --- the checkpoint: gain within 15 % of the reference, <= 5 calls ------------


def test_the_no_elevation_fixture_gets_gain_within_15_percent_of_103_m(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
) -> None:
    elevation_api.serve_recorded(TEL_HADID)
    response = post(lifespan_client, NO_ELE.read_bytes(), NO_ELE.name)
    body = assert_backfilled(response)

    gain = body["gain_m"]
    assert isinstance(gain, float)
    print(
        f"CHECKPOINT tel-hadid lookup gain {gain:.2f} m "
        "(reference 103 m, band 87.55-118.45)"
    )
    assert 87.55 <= gain <= 118.45

    reference = load_expected()[NO_ELE.name].reference_distance_m
    assert reference == 6400
    distance = body["distance_m"]
    assert isinstance(distance, float) and abs(distance - 6400) / 6400 <= 0.02
    assert elevation_api.call_count <= 5
    n = lookup_point_count(distance, DEFAULT_PARAMS)  # ADR 0005 Amendment 1
    assert len(body["points"]) == n  # type: ignore[arg-type]  # JSON list
    assert elevation_api.call_count == math.ceil(n / 100)  # no retry needed
    assert elevation_api.batch_sizes == [100] * (n // 100) + (
        [n % 100] if n % 100 else []
    )


def test_looked_up_values_are_the_recorded_ones_as_returned_not_smoothed(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    elevation_api.serve_recorded(TEL_HADID)
    body = assert_backfilled(post(lifespan_client, NO_ELE.read_bytes(), NO_ELE.name))
    table = recorded_table(TEL_HADID)
    points = body["points"]
    n = lookup_point_count(body["distance_m"], DEFAULT_PARAMS)  # type: ignore[arg-type]  # JSON number
    assert isinstance(points, list) and len(points) == n
    values = [table[pair_of(p["lat"], p["lon"])] for p in points]
    assert [p["elev_m"] for p in points] == values
    assert body["max_elev_m"] == max(values) and body["min_elev_m"] == min(values)
    high = body["high_point"]
    assert isinstance(high, dict) and high["elev_m"] == max(values)
    assert max(p["elev_m"] for p in points) == body["max_elev_m"]
    assert body["start"]["elev_m"] == values[0] and body["end"]["elev_m"] == values[-1]  # type: ignore[index]  # JSON object
    assert (high["lat"], high["lon"]) in {(p["lat"], p["lon"]) for p in points}


@pytest.mark.parametrize("stem", [MODIIN, BEN_SHEMEN])
def test_informational_lookup_gain_of_the_other_two_parents_is_reported_not_asserted(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    stem: str,
) -> None:
    """ADR 0005 section 3: reported in the QA report, not gated (Tel Hadid only)."""
    elevation_api.serve_recorded(stem)
    data = ELE.sub(b"", (GPX_DIR / f"{stem}.gpx").read_bytes())
    assert b"<ele>" not in data
    body = assert_backfilled(post(lifespan_client, data, f"{stem}.gpx"))
    reference = load_expected()[f"{stem}.gpx"].reference_gain_m
    assert reference is not None
    gain = body["gain_m"]
    assert isinstance(gain, float)
    print(
        f"INFORMATIONAL {stem}: lookup gain {gain:.2f} m vs reference {reference:g} m "
        f"({(gain - reference) / reference:+.1%}), {elevation_api.call_count} calls"
    )
    assert elevation_api.call_count <= 5


# --- batch counts -------------------------------------------------------------


def test_250_points_make_exactly_3_requests_of_100_100_50(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    data, pts = no_ele_route(250)
    body = assert_backfilled(post(lifespan_client, data))
    assert elevation_api.call_count == 3
    assert sorted(elevation_api.batch_sizes) == [50, 100, 100]
    for request in elevation_api.requests:
        pairs = query_pairs(request)  # equal lengths, <= 100, only the two params
        for lat, lon in pairs:
            assert re.fullmatch(r"-?\d+\.\d{5}", lat) and re.fullmatch(
                r"-?\d+\.\d{5}", lon
            )
    sent = sorted(p for r in elevation_api.requests for p in query_pairs(r))
    assert sent == sorted(pair_of(p.lat, p.lon) for p in pts)
    points = body["points"]
    assert isinstance(points, list) and len(points) == 250
    assert [p["elev_m"] for p in points] == [
        synthetic_elevation(*pair_of(p["lat"], p["lon"])) for p in points
    ]


@pytest.mark.parametrize(
    ("n", "calls", "points"),
    [
        (2, 1, 2),
        (99, 1, 99),
        (100, 1, 100),
        (101, 2, 101),
        (399, 4, 399),
        (400, 4, 400),
        (401, 4, 400),
        (1000, 4, 400),
        (3000, 4, 400),
    ],
)
def test_calls_follow_the_simplified_point_count_and_never_exceed_4_without_a_retry(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    n: int,
    calls: int,
    points: int,
) -> None:
    data, _ = no_ele_route(n, step_m=135.0)
    body = assert_backfilled(post(lifespan_client, data))
    assert elevation_api.call_count == calls
    assert len(body["points"]) == points  # type: ignore[arg-type]  # JSON list
    assert all(size <= 100 for size in elevation_api.batch_sizes)


def test_only_the_simplified_points_are_looked_up_not_every_track_point(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    data, _ = no_ele_route(1000, step_m=135.0)
    body = assert_backfilled(post(lifespan_client, data))
    looked_up = {p for r in elevation_api.requests for p in query_pairs(r)}
    assert looked_up == {pair_of(p["lat"], p["lon"]) for p in body["points"]}  # type: ignore[attr-defined]  # JSON list
    assert body["point_count_original"] == 1000


def test_a_globe_spanning_hostile_line_is_backfilled_within_budget(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    pts = [
        Pt(-90.0 + 180.0 * i / 599, -180.0 + 360.0 * i / 599, None) for i in range(600)
    ]
    body = assert_backfilled(post(lifespan_client, gpx_bytes([pts])))
    assert elevation_api.call_count == 4
    assert body["gain_m"] is not None and body["loss_m"] is not None


# --- files that already have elevation: no lookup at all ----------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    fixture_params([f for f in valid_fixtures() if f[1].has_elevation]),
)
def test_a_file_that_already_has_elevation_makes_0_requests(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    caplog: pytest.LogCaptureFixture,
    path: Path,
    expected: object,
) -> None:
    caplog.set_level(logging.INFO)
    response = post(lifespan_client, path.read_bytes(), path.name)
    assert response.status_code == 200, response.text
    body = response.json()
    assert elevation_api.call_count == 0
    assert body["elevation_source"] == "file" and body["warnings"] == []
    assert RouteSummary.model_validate(body) == summarise_gpx(
        path.read_bytes(), path.name
    )
    assert [r for r in caplog.records if r.name == "app.elevation"] == []


def test_a_file_with_elevation_is_served_by_an_app_without_lifespan(
    settings: Settings, elevation_api: ElevationApi
) -> None:
    client = TestClient(create_app(settings))  # no `with`: the lifespan never runs
    response = post(client, PARENT.read_bytes(), PARENT.name)
    assert response.status_code == 200 and response.json()["elevation_source"] == "file"
    assert elevation_api.call_count == 0


def test_a_no_elevation_file_without_lifespan_is_a_loud_500_not_a_silent_warning(
    settings: Settings, elevation_api: ElevationApi
) -> None:
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    response = post(client, NO_ELE.read_bytes(), NO_ELE.name)
    assert_error(response, 500, "internal_error")
    assert "lifespan" not in response.text  # the cause stays in the server log
    assert elevation_api.call_count == 0


# --- implausible and partly missing elevation is backfilled too ---------------


def replace_nth_ele(data: bytes, n: int, replacement: bytes) -> bytes:
    matches = list(ELE.finditer(data))
    m = matches[n]
    return data[: m.start()] + replacement + data[m.end() :]


@pytest.mark.parametrize(
    ("index", "replacement"),
    [
        (0, b"<ele>99999</ele>"),
        (400, b"<ele>99999</ele>"),
        (-2, b"<ele>-1000.5</ele>"),
        (0, b""),
        (400, b""),
        (-2, b""),
        (200, b"<ele>nan</ele>"),
        (200, b"<ele>" + b"0" * 65_537 + b"5</ele>"),
    ],
    ids=[
        "first-99999",
        "middle-99999",
        "last-kept-below-range",
        "first-removed",
        "middle-removed",
        "last-kept-removed",
        "middle-nan",
        "middle-overflowed",
    ],
)
def test_one_implausible_or_missing_ele_is_backfilled_to_the_same_answer_as_no_ele(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    index: int,
    replacement: bytes,
) -> None:
    elevation_api.serve_recorded(TEL_HADID)
    baseline = assert_backfilled(post(lifespan_client, NO_ELE.read_bytes(), "x.gpx"))
    elevation_api.requests.clear()

    modified = replace_nth_ele(PARENT.read_bytes(), index, replacement)
    # premise: the edit really makes the profile unusable (not a dropped duplicate)
    assert summarise_gpx(modified, "x.gpx").elevation_source == "none"
    body = assert_backfilled(post(lifespan_client, modified, "x.gpx"))

    assert body["elevation_source"] == "lookup"
    assert body["gain_m"] == baseline["gain_m"]  # exactly: same points, same values
    assert body == baseline
    n = lookup_point_count(baseline["distance_m"], DEFAULT_PARAMS)  # type: ignore[arg-type]  # JSON number
    assert elevation_api.call_count == math.ceil(n / 100)


# --- failure: the route is still returned, flagged, never a 500 ---------------


@pytest.mark.parametrize(
    "exc", [read_timeout, connect_timeout], ids=["read", "connect"]
)
def test_a_timeout_returns_the_route_flagged_after_one_retry(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    exc: Callable[[], Exception],
) -> None:
    elevation_api.serve(raising_handler(exc))
    data, pts = no_ele_route(60)
    body = assert_flagged(post(lifespan_client, data))
    assert elevation_api.call_count == 2
    assert body["distance_m"] == summarise_gpx(data, "route.gpx").distance_m
    assert len(body["points"]) == 60  # type: ignore[arg-type]  # JSON list


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_persistent_5xx_is_retried_once_then_flagged(
    lifespan_client: TestClient, elevation_api: ElevationApi, status: int
) -> None:
    elevation_api.serve(status_handler(status))
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 2


def test_503_then_200_is_a_success_with_calls_equal_batches_plus_one(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    def blip_once(request: httpx.Request) -> httpx.Response:
        if elevation_api.call_count == 1:
            return httpx.Response(503)
        return synthetic_handler(request)

    elevation_api.serve(blip_once)
    assert_backfilled(post(lifespan_client, no_ele_route(250)[0]))
    assert elevation_api.call_count == 3 + 1


def test_503_twice_on_one_batch_flags_the_route_and_that_batch_got_exactly_2_calls(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    data, pts = no_ele_route(250)
    second = pair_of(pts[100].lat, pts[100].lon)

    def second_batch_down(request: httpx.Request) -> httpx.Response:
        if query_pairs(request)[0] == second:
            return httpx.Response(503)
        return synthetic_handler(request)

    elevation_api.serve(second_batch_down)
    assert_flagged(post(lifespan_client, data))
    assert elevation_api.calls_for_batch_starting_at(second) == 2
    assert elevation_api.call_count <= 5


@pytest.mark.parametrize("status", [429, 400, 404, 301])
def test_429_and_other_non_5xx_statuses_are_flagged_without_a_retry(
    lifespan_client: TestClient, elevation_api: ElevationApi, status: int
) -> None:
    elevation_api.serve(status_handler(status))
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 1


def test_a_redirect_is_not_followed(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    def moved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302, headers={"location": "http://open-meteo.test/elsewhere"}
        )

    elevation_api.serve(moved)
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 1


BAD_BODIES = {
    "not-json": b"<html>Bad Gateway</html>",
    "empty-object": b"{}",
    "wrong-count": b'{"elevation": [1, 2, 3]}',
    "null": b"null",
    "string-value": b'{"elevation": ["12"' + b', "12"' * 59 + b"]}",
    "bool-value": b'{"elevation": [' + b",".join([b"true"] * 60) + b"]}",
    "nan": b'{"elevation": [' + b",".join([b"NaN"] * 60) + b"]}",
    "overflow": b'{"elevation": [' + b",".join([b"1e999"] * 60) + b"]}",
    "implausible": b'{"elevation": [' + b",".join([b"20000"] * 60) + b"]}",
    "over-64-kib": b'{"elevation": '
    + b"["
    + b",".join([b"1"] * 60)
    + b'], "p": "'
    + b"x" * 70_000
    + b'"}',
}


@pytest.mark.parametrize("body", BAD_BODIES.values(), ids=BAD_BODIES.keys())
def test_a_malformed_200_body_is_flagged_and_not_retried(
    lifespan_client: TestClient, elevation_api: ElevationApi, body: bytes
) -> None:
    elevation_api.serve(body_handler(body))
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 1


@pytest.mark.parametrize(
    "exc", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError]
)
def test_transport_errors_are_retried_once_then_flagged(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    exc: type[httpx.TransportError],
) -> None:
    elevation_api.serve(raising_handler(lambda: exc("boom")))
    assert_flagged(post(lifespan_client, no_ele_route(60)[0]))
    assert elevation_api.call_count == 2


def test_one_failed_batch_of_3_leaves_every_elev_m_null(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    data, pts = no_ele_route(203)
    last = pair_of(pts[200].lat, pts[200].lon)

    def last_batch_garbage(request: httpx.Request) -> httpx.Response:
        if query_pairs(request)[0] == last:
            return httpx.Response(200, json={"elevation": []})
        return synthetic_handler(request)

    elevation_api.serve(last_batch_garbage)
    body = assert_flagged(post(lifespan_client, data))
    assert len(body["points"]) == 203  # type: ignore[arg-type]  # JSON list


def test_the_warning_never_carries_upstream_detail(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    elevation_api.serve(
        status_handler(503, b'{"error": true, "reason": "UPSTREAM-SECRET-DETAIL-9d2"}')
    )
    response = post(lifespan_client, no_ele_route(60)[0])
    assert_flagged(response)
    assert "UPSTREAM-SECRET" not in response.text and "503" not in str(
        response.json()["warnings"]
    )


def test_a_failed_lookup_returns_the_same_route_as_the_pure_stage(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    elevation_api.serve(status_handler(500))
    data, _ = no_ele_route(1000, step_m=135.0)
    body = assert_flagged(post(lifespan_client, data))
    stage1 = summarise_gpx(data, "route.gpx").model_dump(mode="json")
    stage1["warnings"] = [UNAVAILABLE]
    assert body == stage1
    assert len(body["points"]) == 400  # type: ignore[arg-type]  # JSON list


FAILURES = [
    "ok",
    "s500",
    "s503",
    "s429",
    "s404",
    "timeout",
    "connect",
    "garbage",
    "short",
]


@settings(
    max_examples=40,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(st.lists(st.sampled_from(FAILURES), max_size=10))
def test_any_failure_pattern_on_a_400_point_route_is_200_and_within_5_calls(
    lifespan_client: TestClient, elevation_api: ElevationApi, pattern: list[str]
) -> None:
    elevation_api.reset()

    def scripted(request: httpx.Request) -> httpx.Response:
        kind = (
            pattern[elevation_api.call_count - 1]
            if elevation_api.call_count <= len(pattern)
            else "ok"
        )
        if kind == "ok":
            return synthetic_handler(request)
        if kind[0] == "s" and kind[1:].isdigit():
            return httpx.Response(int(kind[1:]))
        if kind == "timeout":
            raise httpx.ReadTimeout("t")
        if kind == "connect":
            raise httpx.ConnectError("c")
        return httpx.Response(
            200, content=b"garbage" if kind == "garbage" else b'{"elevation":[1]}'
        )

    elevation_api.serve(scripted)
    response = post(lifespan_client, no_ele_route(1000, step_m=135.0)[0])
    assert response.status_code == 200, response.text
    body = response.json()
    assert elevation_api.call_count <= 5
    flagged = {"code": "elevation_unavailable"} in [
        {"code": w["code"]} for w in body["warnings"]
    ]
    assert (body["elevation_source"] == "none") == flagged  # the contract invariant
    assert (body["elevation_source"] == "lookup") == (not flagged)


# --- the contract invariant ---------------------------------------------------


def test_source_none_if_and_only_if_the_warning_is_present(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    data, _ = no_ele_route(60)
    ok = post(lifespan_client, data).json()
    elevation_api.serve(status_handler(500))
    failed = post(lifespan_client, data).json()
    file_route = post(lifespan_client, PARENT.read_bytes(), PARENT.name).json()
    assert (ok["elevation_source"], ok["warnings"]) == ("lookup", [])
    assert (failed["elevation_source"], failed["warnings"]) == ("none", [UNAVAILABLE])
    assert (file_route["elevation_source"], file_route["warnings"]) == ("file", [])


# --- wiring: lifespan, settings, client options -------------------------------


def test_the_lifespan_owns_the_elevation_client(
    settings: Settings, elevation_api: ElevationApi
) -> None:
    app = create_app(settings)
    assert app.state.elevation_lookup is None  # before startup
    with TestClient(app):
        assert isinstance(app.state.elevation_lookup, ElevationClient)
    assert app.state.elevation_lookup is None  # reset on shutdown


def test_each_startup_builds_its_own_client(
    settings: Settings, elevation_api: ElevationApi
) -> None:
    app = create_app(settings)
    with TestClient(app):
        first = app.state.elevation_lookup
    with TestClient(app):
        second = app.state.elevation_lookup
    assert first is not second


def test_the_request_carries_the_app_user_agent_and_goes_to_the_configured_host(
    lifespan_client: TestClient, elevation_api: ElevationApi
) -> None:
    assert_backfilled(post(lifespan_client, no_ele_route(20)[0]))
    (request,) = elevation_api.requests
    assert request.headers["user-agent"] == "hike-prep-api/9.9.9-test"
    assert request.url.host == "open-meteo.test"
    assert request.url.path == "/v1/elevation"


def test_the_timeout_setting_is_read_from_the_environment_and_bounds_the_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HIKE_ELEVATION_TIMEOUT_S", "0.05")
    configured = Settings(
        _env_file=None,
        env="test",
        cors_origins=["http://allowed.test"],
        version="9.9.9-test",
        open_meteo_base_url="http://open-meteo.test",
    )
    assert configured.elevation_timeout_s == 0.05

    async def sleeper(request: httpx.Request) -> httpx.Response:
        await anyio.sleep(10)
        return synthetic_handler(request)

    from tests.elevation_support import elevation_mock

    with (
        elevation_mock("http://open-meteo.test") as api,
        TestClient(create_app(configured)) as client,
    ):
        api.serve(sleeper)
        started = time.monotonic()
        assert_flagged(post(client, no_ele_route(30)[0]))
        elapsed = time.monotonic() - started
        assert api.call_count == 2
    assert elapsed < 5.0, "two attempts of 0.05 s, not the 5 s default"


@pytest.mark.parametrize("value", ["0", "-1", "31", "abc", "nan"])
def test_a_bad_timeout_setting_is_rejected_at_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HIKE_ELEVATION_TIMEOUT_S", value)
    with pytest.raises(ValueError, match="elevation_timeout_s"):
        Settings(_env_file=None)


def test_the_timeout_default_and_upper_bound() -> None:
    assert Settings(_env_file=None).elevation_timeout_s == 5.0
    assert Settings(_env_file=None, elevation_timeout_s=30).elevation_timeout_s == 30


@pytest.mark.anyio
async def test_new_http_client_follows_the_adr_options(settings: Settings) -> None:
    http = new_http_client(settings)
    try:
        assert http.base_url.host == "open-meteo.test"
        assert http.timeout == httpx.Timeout(settings.elevation_timeout_s)
        assert http.follow_redirects is False
        assert http.headers["user-agent"] == "hike-prep-api/9.9.9-test"
    finally:
        await http.aclose()


# --- observability ------------------------------------------------------------


class JsonLines(logging.Handler):
    """Formats records with the app's own formatter inside the request context."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.lines: list[dict[str, object]] = []
        self.setFormatter(JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "app.elevation":
            self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def elevation_log() -> Iterator[JsonLines]:
    handler = JsonLines()
    logger = logging.getLogger("app.elevation")
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


def test_a_backfill_logs_one_info_line_with_the_request_id(
    lifespan_client: TestClient, elevation_api: ElevationApi, elevation_log: JsonLines
) -> None:
    response = post(lifespan_client, no_ele_route(250)[0])
    assert response.status_code == 200
    assert len(elevation_log.lines) == 1, elevation_log.lines
    (line,) = elevation_log.lines
    assert line["message"] == "elevation_lookup" and line["level"] == "INFO"
    assert line["points"] == 250 and line["batches"] == 3 and line["calls"] == 3
    assert line["outcome"] == "ok" and line["status_code"] is None
    assert isinstance(line["duration_ms"], float) and line["duration_ms"] >= 0
    assert line["request_id"] == response.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize(
    ("handler", "outcome", "status", "calls"),
    [
        (status_handler(503), "http_status", 503, 2),
        (status_handler(429), "http_status", 429, 1),
        (body_handler(b"junk"), "bad_response", None, 1),
        (raising_handler(read_timeout), "timeout", None, 2),
        (raising_handler(lambda: httpx.ConnectError("c")), "transport_error", None, 2),
    ],
    ids=["503", "429", "junk", "timeout", "connect"],
)
def test_a_failed_backfill_logs_one_warning_line_with_outcome_status_and_calls(
    lifespan_client: TestClient,
    elevation_api: ElevationApi,
    elevation_log: JsonLines,
    handler: object,
    outcome: str,
    status: int | None,
    calls: int,
) -> None:
    elevation_api.serve(handler)  # type: ignore[arg-type]  # parametrised handler
    response = post(lifespan_client, no_ele_route(60)[0])
    assert_flagged(response)
    assert len(elevation_log.lines) == 1, elevation_log.lines
    (line,) = elevation_log.lines
    assert line["message"] == "elevation_lookup" and line["level"] == "WARNING"
    assert (line["points"], line["batches"], line["calls"]) == (60, 1, calls)
    assert line["outcome"] == outcome and line["status_code"] == status
    assert line["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "UPSTREAM" not in json.dumps(line)


def test_no_log_line_without_a_lookup(
    lifespan_client: TestClient, elevation_api: ElevationApi, elevation_log: JsonLines
) -> None:
    post(lifespan_client, PARENT.read_bytes(), PARENT.name)
    assert elevation_log.lines == []
