"""Red tests for api/tools/deploy.py (ADR 0002 section 4, 5 and "How it is tested").

No network: fetch/sleep are injected; urllib_fetch is exercised against a loopback
http.server (127.0.0.1 is the only host pytest-socket allows).
"""

from __future__ import annotations

import copy
import json
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tools import deploy
from tools.deploy import DeployCheckError, HttpResult

FIXTURES = Path(__file__).parent / "fixtures"
API_DIR = Path(__file__).resolve().parent.parent

SHA = "0123456789abcdef0123456789abcdef01234567"
ORIGIN = "https://hike-proj.web.app"
CANDIDATE_URL = "https://candidate---hike-api-123456789012.me-west1.run.app"
LIVE_URL = "https://hike-api-123456789012.me-west1.run.app"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def health(
    *,
    status: int = 200,
    sha: str | None = SHA,
    state: str = "ok",
    acao: str | None = ORIGIN,
    body: bytes | None = None,
) -> HttpResult:
    payload: dict[str, str] = {"status": state, "version": "0.1.0", "env": "production"}
    if sha is not None:
        payload["git_sha"] = sha
    headers = {"content-type": "application/json"}
    if acao is not None:
        headers["access-control-allow-origin"] = acao
    return HttpResult(
        status=status,
        headers=headers,
        body=json.dumps(payload).encode() if body is None else body,
    )


# --- check_health ---


def test_check_health_accepts_ok_response_with_sha_and_origin() -> None:
    deploy.check_health(health(), SHA, ORIGIN)


def test_check_health_without_origin_does_not_require_cors_header() -> None:
    deploy.check_health(health(acao=None), SHA, None)


def test_check_health_without_origin_ignores_a_cors_header_that_is_present() -> None:
    deploy.check_health(health(acao="https://anything.example"), SHA, None)


def test_check_health_rejects_wrong_sha() -> None:
    with pytest.raises(DeployCheckError, match="git_sha"):
        deploy.check_health(health(sha="f" * 40), SHA, ORIGIN)


def test_check_health_rejects_sha_that_is_only_a_prefix_match() -> None:
    with pytest.raises(DeployCheckError, match="git_sha"):
        deploy.check_health(health(sha=SHA[:7]), SHA, ORIGIN)


def test_check_health_rejects_missing_sha() -> None:
    with pytest.raises(DeployCheckError, match="git_sha"):
        deploy.check_health(health(sha=None), SHA, ORIGIN)


def test_check_health_rejects_unknown_sha_placeholder() -> None:
    # An image built without --build-arg GIT_SHA reports "unknown"; must never pass.
    with pytest.raises(DeployCheckError, match="git_sha"):
        deploy.check_health(health(sha="unknown"), SHA, ORIGIN)


def test_check_health_rejects_status_not_ok() -> None:
    with pytest.raises(DeployCheckError, match="status"):
        deploy.check_health(health(state="degraded"), SHA, ORIGIN)


@pytest.mark.parametrize("code", [201, 204, 301, 404, 500, 502, 503])
def test_check_health_rejects_non_200(code: int) -> None:
    with pytest.raises(DeployCheckError, match=str(code)):
        deploy.check_health(health(status=code), SHA, ORIGIN)


@pytest.mark.parametrize(
    "body",
    [b"", b"<html>502 Bad Gateway</html>", b"not json", b"\xff\xfe\x00", b"{"],
)
def test_check_health_rejects_non_json_body(body: bytes) -> None:
    with pytest.raises(DeployCheckError, match="JSON"):
        deploy.check_health(health(body=body), SHA, ORIGIN)


@pytest.mark.parametrize("body", [b"[]", b"null", b'"ok"', b"42"])
def test_check_health_rejects_json_that_is_not_an_object(body: bytes) -> None:
    with pytest.raises(DeployCheckError):
        deploy.check_health(health(body=body), SHA, ORIGIN)


def test_check_health_rejects_missing_cors_header_when_origin_given() -> None:
    with pytest.raises(DeployCheckError, match="access-control-allow-origin"):
        deploy.check_health(health(acao=None), SHA, ORIGIN)


@pytest.mark.parametrize(
    "acao",
    [
        "*",
        "https://evil.example",
        ORIGIN + "/",
        "HTTPS://HIKE-PROJ.WEB.APP",
        "null",
        "",
    ],
)
def test_check_health_rejects_mismatched_cors_header(acao: str) -> None:
    with pytest.raises(DeployCheckError, match="access-control-allow-origin"):
        deploy.check_health(health(acao=acao), SHA, ORIGIN)


def test_check_health_error_message_names_expected_and_actual_sha() -> None:
    with pytest.raises(DeployCheckError) as info:
        deploy.check_health(health(sha="deadbeef"), SHA, ORIGIN)

    assert SHA in str(info.value)
    assert "deadbeef" in str(info.value)


def test_check_health_accepts_the_real_app_health_response() -> None:
    """Real wiring: the field names the tool reads are the ones create_app serves."""
    settings = Settings(
        _env_file=None,
        env="production",
        cors_origins=[ORIGIN],
        version="0.1.0",
        git_sha=SHA,
    )
    response = TestClient(create_app(settings)).get(
        "/health", headers={"Origin": ORIGIN}
    )
    result = HttpResult(
        status=response.status_code,
        headers={k.lower(): v for k, v in response.headers.items()},
        body=response.content,
    )

    deploy.check_health(result, SHA, ORIGIN)

    with pytest.raises(DeployCheckError):
        deploy.check_health(result, "f" * 40, ORIGIN)


# --- smoke ---


class FakeFetch:
    """Scripted fetch: each entry is an HttpResult to return or an exception to raise.

    The last entry repeats once the script is exhausted.
    """

    def __init__(self, script: Sequence[HttpResult | Exception]) -> None:
        self.script = script
        self.calls: list[tuple[str, Mapping[str, str], float]] = []

    def __call__(
        self, url: str, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResult:
        self.calls.append((url, headers, timeout_s))
        item = self.script[min(len(self.calls), len(self.script)) - 1]
        if isinstance(item, Exception):
            raise item
        return item


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def run_smoke(
    fetch: FakeFetch,
    sleep: FakeSleep,
    *,
    url: str = CANDIDATE_URL,
    origin: str | None = ORIGIN,
    **kwargs: Any,
) -> None:
    deploy.smoke(url, SHA, origin=origin, fetch=fetch, sleep=sleep, **kwargs)


def test_smoke_passes_first_try_without_sleeping() -> None:
    fetch, sleep = FakeFetch([health()]), FakeSleep()

    run_smoke(fetch, sleep)

    assert len(fetch.calls) == 1
    assert sleep.calls == []


def test_smoke_requests_health_under_the_given_url() -> None:
    fetch = FakeFetch([health()])

    run_smoke(fetch, FakeSleep())

    assert fetch.calls[0][0] == CANDIDATE_URL + "/health"


def test_smoke_sends_origin_header_when_origin_given() -> None:
    fetch = FakeFetch([health()])

    run_smoke(fetch, FakeSleep())

    sent = {k.lower(): v for k, v in fetch.calls[0][1].items()}
    assert sent["origin"] == ORIGIN


def test_smoke_sends_no_origin_header_when_origin_absent() -> None:
    fetch = FakeFetch([health(acao=None)])

    run_smoke(fetch, FakeSleep(), origin=None)

    assert "origin" not in {k.lower() for k in fetch.calls[0][1]}


def test_smoke_uses_a_ten_second_timeout_per_attempt() -> None:
    fetch = FakeFetch([health()])

    run_smoke(fetch, FakeSleep())

    assert fetch.calls[0][2] == 10.0


def test_smoke_rides_out_a_cold_start_then_succeeds() -> None:
    fetch = FakeFetch([health(status=503), health(status=503), health()])
    sleep = FakeSleep()

    run_smoke(fetch, sleep)

    assert len(fetch.calls) == 3
    assert sleep.calls == [5.0, 5.0]


def test_smoke_succeeds_on_the_last_allowed_attempt() -> None:
    fetch = FakeFetch([health(status=503)] * 5 + [health()])
    sleep = FakeSleep()

    run_smoke(fetch, sleep)

    assert len(fetch.calls) == 6
    assert len(sleep.calls) == 5


def test_smoke_gives_up_after_default_six_attempts_five_seconds_apart() -> None:
    fetch, sleep = FakeFetch([health(status=503)]), FakeSleep()

    with pytest.raises(DeployCheckError):
        run_smoke(fetch, sleep)

    assert len(fetch.calls) == 6
    assert sleep.calls == [5.0] * 5


def test_smoke_honours_custom_attempts_and_delay() -> None:
    fetch, sleep = FakeFetch([health(status=503)]), FakeSleep()

    with pytest.raises(DeployCheckError):
        run_smoke(fetch, sleep, attempts=3, delay_s=0.5)

    assert len(fetch.calls) == 3
    assert sleep.calls == [0.5, 0.5]


def test_smoke_single_attempt_does_not_sleep() -> None:
    fetch, sleep = FakeFetch([health(status=503)]), FakeSleep()

    with pytest.raises(DeployCheckError):
        run_smoke(fetch, sleep, attempts=1)

    assert len(fetch.calls) == 1
    assert sleep.calls == []


def test_smoke_failure_reports_the_last_reason() -> None:
    fetch = FakeFetch([health(status=503), health(sha="f" * 40)])

    with pytest.raises(DeployCheckError, match="git_sha"):
        run_smoke(fetch, FakeSleep(), attempts=2)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionRefusedError("refused"),
        OSError("network down"),
    ],
)
def test_smoke_retries_when_fetch_raises_a_network_error(error: OSError) -> None:
    fetch = FakeFetch([error, error, health()])
    sleep = FakeSleep()

    run_smoke(fetch, sleep)

    assert len(fetch.calls) == 3


def test_smoke_network_errors_that_never_clear_end_in_deploy_check_error() -> None:
    fetch = FakeFetch([TimeoutError("timed out")])

    with pytest.raises(DeployCheckError, match="timed out"):
        run_smoke(fetch, FakeSleep(), attempts=2)


def test_smoke_wrong_sha_every_time_fails_this_is_the_checkpoint_scenario() -> None:
    fetch = FakeFetch([health(sha="f" * 40)])

    with pytest.raises(DeployCheckError):
        run_smoke(fetch, FakeSleep())

    assert len(fetch.calls) == 6


def test_smoke_never_really_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(seconds: float) -> None:
        raise AssertionError("smoke must use the injected sleep")

    monkeypatch.setattr(time, "sleep", forbidden)

    with pytest.raises(DeployCheckError):
        run_smoke(FakeFetch([health(status=503)]), FakeSleep())


# --- read_version ---


def test_read_version_reads_project_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")

    assert deploy.read_version(pyproject) == "1.2.3"


def test_read_version_ignores_version_keys_in_other_tables(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[tool.other]\nversion = "9.9.9"\n[project]\nname = "x"\nversion = "0.4.0"\n',
        encoding="utf-8",
    )

    assert deploy.read_version(pyproject) == "0.4.0"


def test_read_version_reads_the_real_api_pyproject() -> None:
    version = deploy.read_version(API_DIR / "pyproject.toml")

    assert version.count(".") == 2
    assert f'version = "{version}"' in (API_DIR / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_read_version_raises_when_version_is_missing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "x"\n', encoding="utf-8")

    with pytest.raises(DeployCheckError, match="version"):
        deploy.read_version(pyproject)


def test_read_version_raises_when_project_table_is_missing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.x]\nversion = "1.0.0"\n', encoding="utf-8")

    with pytest.raises(DeployCheckError, match="version"):
        deploy.read_version(pyproject)


def test_read_version_raises_when_version_is_dynamic(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "x"\ndynamic = ["version"]\n', encoding="utf-8"
    )

    with pytest.raises(DeployCheckError, match="version"):
        deploy.read_version(pyproject)


def test_read_version_raises_when_version_is_not_a_string(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nversion = 3\n", encoding="utf-8")

    with pytest.raises(DeployCheckError, match="version"):
        deploy.read_version(pyproject)


# --- serving_revision ---


def test_serving_revision_returns_the_revision_at_100_percent() -> None:
    assert (
        deploy.serving_revision(load("run_service_before.json")) == "hike-api-00007-abc"
    )


def test_serving_revision_ignores_zero_percent_tagged_candidate() -> None:
    assert (
        deploy.serving_revision(load("run_service_after_candidate.json"))
        == "hike-api-00007-abc"
    )


def test_serving_revision_rejects_a_traffic_split() -> None:
    with pytest.raises(DeployCheckError, match="100"):
        deploy.serving_revision(load("run_service_split.json"))


def test_serving_revision_rejects_traffic_that_does_not_sum_to_100() -> None:
    service = load("run_service_before.json")
    service["status"]["traffic"][0]["percent"] = 60

    with pytest.raises(DeployCheckError):
        deploy.serving_revision(service)


def test_serving_revision_rejects_empty_traffic() -> None:
    service = load("run_service_before.json")
    service["status"]["traffic"] = []

    with pytest.raises(DeployCheckError):
        deploy.serving_revision(service)


def test_serving_revision_rejects_missing_status() -> None:
    with pytest.raises(DeployCheckError):
        deploy.serving_revision(load("run_service_no_status.json"))


@pytest.mark.parametrize(
    "service", [{}, {"status": None}, {"status": {}}, {"status": []}]
)
def test_serving_revision_rejects_malformed_documents(service: dict[str, Any]) -> None:
    with pytest.raises(DeployCheckError):
        deploy.serving_revision(service)


def test_serving_revision_rejects_traffic_entry_without_revision_name() -> None:
    service = load("run_service_before.json")
    del service["status"]["traffic"][0]["revisionName"]

    with pytest.raises(DeployCheckError):
        deploy.serving_revision(service)


def test_serving_revision_rejects_traffic_that_is_not_a_list() -> None:
    service = load("run_service_before.json")
    service["status"]["traffic"] = {"percent": 100}

    with pytest.raises(DeployCheckError):
        deploy.serving_revision(service)


# --- tagged_revision ---


def test_tagged_revision_returns_revision_and_url_of_the_candidate() -> None:
    assert deploy.tagged_revision(
        load("run_service_after_candidate.json"), "candidate"
    ) == (
        "hike-api-00008-def",
        CANDIDATE_URL,
    )


def test_tagged_revision_works_when_the_tagged_target_also_has_traffic() -> None:
    assert deploy.tagged_revision(load("run_service_split.json"), "candidate") == (
        "hike-api-00008-def",
        CANDIDATE_URL,
    )


def test_tagged_revision_raises_when_tag_is_absent() -> None:
    with pytest.raises(DeployCheckError, match="candidate"):
        deploy.tagged_revision(load("run_service_before.json"), "candidate")


def test_tagged_revision_does_not_match_a_different_tag() -> None:
    with pytest.raises(DeployCheckError, match="canary"):
        deploy.tagged_revision(load("run_service_after_candidate.json"), "canary")


def test_tagged_revision_does_not_match_tag_by_prefix() -> None:
    service = load("run_service_after_candidate.json")
    service["status"]["traffic"][1]["tag"] = "candidate-old"

    with pytest.raises(DeployCheckError):
        deploy.tagged_revision(service, "candidate")


def test_tagged_revision_rejects_tag_target_without_url() -> None:
    service = load("run_service_after_candidate.json")
    del service["status"]["traffic"][1]["url"]

    with pytest.raises(DeployCheckError, match="url"):
        deploy.tagged_revision(service, "candidate")


def test_tagged_revision_never_derives_the_url_by_hand() -> None:
    service = load("run_service_after_candidate.json")
    service["status"]["traffic"][1]["url"] = "https://from-the-document.example"

    assert (
        deploy.tagged_revision(service, "candidate")[1]
        == "https://from-the-document.example"
    )


def test_tagged_revision_does_not_read_spec_traffic() -> None:
    service = load("run_service_after_candidate.json")
    service["status"]["traffic"] = [service["status"]["traffic"][0]]

    with pytest.raises(DeployCheckError):
        deploy.tagged_revision(service, "candidate")


@pytest.mark.parametrize(
    "service", [{}, {"status": None}, {"status": {}}, {"status": {"traffic": 5}}]
)
def test_tagged_revision_rejects_malformed_documents(service: dict[str, Any]) -> None:
    with pytest.raises(DeployCheckError):
        deploy.tagged_revision(service, "candidate")


def test_tagged_revision_does_not_mutate_the_document() -> None:
    service = load("run_service_after_candidate.json")
    before = copy.deepcopy(service)

    deploy.tagged_revision(service, "candidate")
    deploy.serving_revision(service)

    assert service == before


# --- main (CLI) ---


def run_main(argv: list[str]) -> int:
    """main() returns its exit code; argparse's SystemExit(2) is tolerated."""
    try:
        return deploy.main(argv)
    except SystemExit as exit_:
        assert isinstance(exit_.code, int)
        return exit_.code


def kv(output: str) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in output.splitlines() if line.strip())
    return {key: value for key, value in pairs}


def test_main_serving_prints_previous_revision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_main(
        ["serving", "--service-json", str(FIXTURES / "run_service_before.json")]
    )

    assert code == 0
    assert kv(capsys.readouterr().out) == {"previous_revision": "hike-api-00007-abc"}


def test_main_tagged_prints_candidate_revision_and_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_main(
        [
            "tagged",
            "--service-json",
            str(FIXTURES / "run_service_after_candidate.json"),
            "--tag",
            "candidate",
        ]
    )

    assert code == 0
    assert kv(capsys.readouterr().out) == {
        "candidate_revision": "hike-api-00008-def",
        "candidate_url": CANDIDATE_URL,
    }


def test_main_version_prints_the_real_api_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_main(["version"])

    assert code == 0
    assert deploy.read_version(API_DIR / "pyproject.toml") in capsys.readouterr().out


def test_main_serving_with_split_traffic_exits_1_and_explains_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_main(
        ["serving", "--service-json", str(FIXTURES / "run_service_split.json")]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "100" in captured.err


def test_main_tagged_with_absent_tag_exits_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_main(
        [
            "tagged",
            "--service-json",
            str(FIXTURES / "run_service_before.json"),
            "--tag",
            "candidate",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "candidate" in captured.err


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["serving"],
        ["tagged", "--service-json", "x.json"],
        ["tagged", "--tag", "candidate"],
        ["smoke", "--url", LIVE_URL],
        ["smoke", "--expected-sha", SHA],
        ["serving", "--service-json"],
        ["version", "--no-such-flag"],
    ],
)
def test_main_usage_errors_exit_2(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main(argv) == 2
    assert capsys.readouterr().out == ""


def test_main_unreadable_service_json_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_main(["serving", "--service-json", str(tmp_path / "missing.json")])

    assert code in (1, 2)
    assert capsys.readouterr().out == ""


def test_main_malformed_service_json_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    code = run_main(["serving", "--service-json", str(bad)])

    assert code in (1, 2)
    assert capsys.readouterr().out == ""


def test_main_service_json_that_is_not_an_object_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "list.json"
    bad.write_text("[]", encoding="utf-8")

    assert run_main(["serving", "--service-json", str(bad)]) == 1
    assert capsys.readouterr().out == ""


def test_main_smoke_passes_with_matching_health(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fetch = FakeFetch([health()])
    monkeypatch.setattr(deploy, "urllib_fetch", fetch)

    code = run_main(
        ["smoke", "--url", CANDIDATE_URL, "--expected-sha", SHA, "--origin", ORIGIN]
    )

    assert code == 0
    assert [call[0] for call in fetch.calls] == [CANDIDATE_URL + "/health"]
    assert {k.lower(): v for k, v in fetch.calls[0][1].items()}["origin"] == ORIGIN
    assert capsys.readouterr().err == ""


def test_main_smoke_without_origin_does_not_check_cors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deploy, "urllib_fetch", FakeFetch([health(acao=None)]))

    assert run_main(["smoke", "--url", LIVE_URL, "--expected-sha", SHA]) == 0


def test_main_smoke_with_wrong_sha_exits_1_after_all_attempts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fetch, sleep = FakeFetch([health(sha="f" * 40)]), FakeSleep()
    monkeypatch.setattr(deploy, "urllib_fetch", fetch)
    monkeypatch.setattr(time, "sleep", sleep)

    code = run_main(
        ["smoke", "--url", CANDIDATE_URL, "--expected-sha", SHA, "--origin", ORIGIN]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert len(fetch.calls) == 6
    assert sleep.calls == [5.0] * 5
    assert "git_sha" in captured.err


# --- urllib_fetch (loopback) ---


def make_handler(
    status: int,
    body: bytes,
    extra_headers: Mapping[str, str],
    seen: list[dict[str, str]],
    release: threading.Event,
    stall: bool,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(
                {k.lower(): v for k, v in self.headers.items()} | {"path": self.path}
            )
            if stall:
                release.wait(5)
                return
            self.send_response(status)
            for key, value in extra_headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


@contextmanager
def loopback(
    status: int = 200,
    body: bytes = b"",
    headers: Mapping[str, str] | None = None,
    *,
    stall: bool = False,
) -> Iterator[tuple[str, list[dict[str, str]]]]:
    seen: list[dict[str, str]] = []
    release = threading.Event()
    server = HTTPServer(
        ("127.0.0.1", 0),
        make_handler(status, body, headers or {}, seen, release, stall),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_urllib_fetch_returns_status_body_and_lowercased_headers() -> None:
    with loopback(
        200,
        b'{"status":"ok"}',
        {"X-Custom": "Yes", "Access-Control-Allow-Origin": ORIGIN},
    ) as (base, _):
        result = deploy.urllib_fetch(base + "/health", {}, 5.0)

    assert result.status == 200
    assert result.body == b'{"status":"ok"}'
    assert result.headers["x-custom"] == "Yes"
    assert result.headers["access-control-allow-origin"] == ORIGIN
    assert all(name == name.lower() for name in result.headers)


def test_urllib_fetch_sends_the_path_and_request_headers() -> None:
    with loopback(200, b"{}") as (base, seen):
        deploy.urllib_fetch(base + "/health", {"Origin": ORIGIN}, 5.0)

    assert seen[0]["path"] == "/health"
    assert seen[0]["origin"] == ORIGIN


@pytest.mark.parametrize("code", [404, 500, 503])
def test_urllib_fetch_returns_http_error_statuses_as_results(code: int) -> None:
    with loopback(code, b"upstream said no") as (base, _):
        result = deploy.urllib_fetch(base + "/health", {}, 5.0)

    assert result.status == code
    assert result.body == b"upstream said no"


def test_urllib_fetch_times_out_with_an_oserror() -> None:
    with loopback(stall=True) as (base, _), pytest.raises(OSError):
        deploy.urllib_fetch(base + "/health", {}, 0.2)


def test_urllib_fetch_connection_refused_raises_oserror() -> None:
    with loopback() as (base, _):
        pass  # server is closed again: the port now refuses connections

    with pytest.raises(OSError):
        deploy.urllib_fetch(base + "/health", {}, 2.0)


def test_smoke_through_the_real_urllib_fetch_against_loopback() -> None:
    body = json.dumps({"status": "ok", "git_sha": SHA}).encode()
    sleep = FakeSleep()
    with loopback(200, body, {"Access-Control-Allow-Origin": ORIGIN}) as (base, seen):
        deploy.smoke(
            base, SHA, origin=ORIGIN, fetch=deploy.urllib_fetch, sleep=sleep, attempts=2
        )

    assert seen[0]["origin"] == ORIGIN
    assert sleep.calls == []


def test_smoke_through_the_real_urllib_fetch_fails_on_wrong_sha() -> None:
    body = json.dumps({"status": "ok", "git_sha": "f" * 40}).encode()
    sleep = FakeSleep()
    with (
        loopback(200, body) as (base, seen),
        pytest.raises(DeployCheckError, match="git_sha"),
    ):
        deploy.smoke(
            base, SHA, origin=None, fetch=deploy.urllib_fetch, sleep=sleep, attempts=2
        )

    assert len(seen) == 2
    assert sleep.calls == [5.0]
