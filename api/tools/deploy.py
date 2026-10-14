"""CI-only deploy helpers (stdlib only; not copied into the image).

See docs/adr/0002-deployment.md. Each CLI subcommand prints ``key=value`` lines
for ``$GITHUB_OUTPUT`` (``version`` prints the bare version). Exit codes: 0 ok,
1 check failed (``DeployCheckError``), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
SMOKE_TIMEOUT_S = 10.0


class DeployCheckError(RuntimeError):
    """A deploy check failed (wrong revision, bad health response, ...)."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]  # lower-cased names
    body: bytes


# (url, request headers, timeout_s)
Fetch = Callable[[str, Mapping[str, str], float], HttpResult]


def read_version(pyproject: Path) -> str:
    """Return ``[project].version`` from a pyproject.toml."""
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise DeployCheckError(
            f"cannot read version from {pyproject}: {error}"
        ) from error
    project = data.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version:
        raise DeployCheckError(
            f"{pyproject}: [project].version is missing, dynamic or not a string"
        )
    return version


def _traffic(service: Mapping[str, object]) -> list[Mapping[str, object]]:
    status = service.get("status")
    if not isinstance(status, dict):
        raise DeployCheckError("service document has no status")
    traffic = status.get("traffic")
    if not isinstance(traffic, list):
        raise DeployCheckError("service status has no traffic list")
    entries: list[Mapping[str, object]] = []
    for entry in traffic:
        if not isinstance(entry, dict):
            raise DeployCheckError("service status.traffic holds a non-object entry")
        entries.append(entry)
    return entries


def serving_revision(service: Mapping[str, object]) -> str:
    """The one revision at 100 % traffic; raise DeployCheckError otherwise."""
    entries = _traffic(service)
    serving = [e for e in entries if isinstance(e.get("percent"), int) and e["percent"]]
    if len(serving) != 1 or serving[0]["percent"] != 100:
        raise DeployCheckError(
            "expected exactly one revision serving 100% of traffic, got "
            f"{[(e.get('revisionName'), e.get('percent')) for e in serving]}"
        )
    name = serving[0].get("revisionName")
    if not isinstance(name, str) or not name:
        raise DeployCheckError("the revision serving 100% has no revisionName")
    return name


def tagged_revision(service: Mapping[str, object], tag: str) -> tuple[str, str]:
    """Return ``(revision, url)`` for the traffic target carrying ``tag``."""
    for entry in _traffic(service):
        if entry.get("tag") != tag:
            continue
        name = entry.get("revisionName")
        url = entry.get("url")
        if not isinstance(name, str) or not name:
            raise DeployCheckError(f"traffic target tagged {tag!r} has no revisionName")
        if not isinstance(url, str) or not url:
            raise DeployCheckError(f"traffic target tagged {tag!r} has no url")
        return name, url
    raise DeployCheckError(f"no traffic target is tagged {tag!r}")


def check_health(result: HttpResult, expected_sha: str, origin: str | None) -> None:
    """Raise DeployCheckError unless /health is 200, ok, has the expected git_sha
    and (if ``origin`` is given) echoes it in access-control-allow-origin."""
    if result.status != 200:
        raise DeployCheckError(f"/health returned HTTP {result.status}, expected 200")
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except ValueError as error:  # includes UnicodeDecodeError and JSONDecodeError
        raise DeployCheckError(f"/health body is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise DeployCheckError("/health JSON is not an object")
    if payload.get("status") != "ok":
        raise DeployCheckError(
            f"/health status is {payload.get('status')!r}, expected 'ok'"
        )
    if payload.get("git_sha") != expected_sha:
        raise DeployCheckError(
            f"/health git_sha is {payload.get('git_sha')!r}, expected {expected_sha!r}"
        )
    if origin is not None:
        actual = result.headers.get("access-control-allow-origin")
        if actual != origin:
            raise DeployCheckError(
                f"access-control-allow-origin is {actual!r}, expected {origin!r}"
            )


def smoke(
    url: str,
    expected_sha: str,
    *,
    origin: str | None,
    fetch: Fetch,
    sleep: Callable[[float], None],
    attempts: int = 6,
    delay_s: float = 5.0,
) -> None:
    """GET ``<url>/health`` up to ``attempts`` times, ``delay_s`` apart.

    Raise DeployCheckError if no attempt passes.
    """
    headers = {"Origin": origin} if origin is not None else {}
    reason = "no attempt made"
    for attempt in range(1, attempts + 1):
        try:
            result = fetch(url + "/health", headers, SMOKE_TIMEOUT_S)
            check_health(result, expected_sha, origin)
            return
        except (DeployCheckError, OSError) as error:
            reason = str(error)
            print(f"smoke attempt {attempt}/{attempts}: {reason}", file=sys.stderr)
        if attempt < attempts:
            sleep(delay_s)
    raise DeployCheckError(f"smoke failed after {attempts} attempts: {reason}")


def urllib_fetch(url: str, headers: Mapping[str, str], timeout_s: float) -> HttpResult:
    """The only I/O in this module."""
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return HttpResult(
                response.status,
                {k.lower(): v for k, v in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as error:
        with error:
            return HttpResult(
                error.code,
                {k.lower(): v for k, v in error.headers.items()},
                error.read(),
            )


def _load_service(path: str) -> dict[str, object]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise DeployCheckError(f"cannot read service JSON {path}: {error}") from error
    if not isinstance(data, dict):
        raise DeployCheckError(f"service JSON {path} is not an object")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    """CLI.

    version | serving --service-json F | tagged --service-json F --tag T
    | smoke --url U --expected-sha S [--origin O]
    """
    parser = argparse.ArgumentParser(prog="python -m tools.deploy")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version")
    serving = commands.add_parser("serving")
    serving.add_argument("--service-json", required=True)
    tagged = commands.add_parser("tagged")
    tagged.add_argument("--service-json", required=True)
    tagged.add_argument("--tag", required=True)
    smoke_cmd = commands.add_parser("smoke")
    smoke_cmd.add_argument("--url", required=True)
    smoke_cmd.add_argument("--expected-sha", required=True)
    smoke_cmd.add_argument("--origin")
    args = parser.parse_args(argv)

    try:
        if args.command == "version":
            print(read_version(PYPROJECT))
        elif args.command == "serving":
            print(
                f"previous_revision={serving_revision(_load_service(args.service_json))}"
            )
        elif args.command == "tagged":
            revision, url = tagged_revision(_load_service(args.service_json), args.tag)
            print(f"candidate_revision={revision}")
            print(f"candidate_url={url}")
        else:
            smoke(
                args.url,
                args.expected_sha,
                origin=args.origin,
                fetch=urllib_fetch,
                sleep=time.sleep,
            )
    except DeployCheckError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
