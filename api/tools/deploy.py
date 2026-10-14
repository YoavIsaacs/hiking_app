"""CI-only deploy helpers (stdlib only; not copied into the image).

See docs/adr/0002-deployment.md. Each CLI subcommand prints ``key=value`` lines
for ``$GITHUB_OUTPUT``. Exit codes: 0 ok, 1 check failed (``DeployCheckError``),
2 usage error.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


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
    raise NotImplementedError


def serving_revision(service: Mapping[str, object]) -> str:
    """The one revision at 100 % traffic; raise DeployCheckError otherwise."""
    raise NotImplementedError


def tagged_revision(service: Mapping[str, object], tag: str) -> tuple[str, str]:
    """Return ``(revision, url)`` for the traffic target carrying ``tag``."""
    raise NotImplementedError


def check_health(result: HttpResult, expected_sha: str, origin: str | None) -> None:
    """Raise DeployCheckError unless /health is 200, ok, has the expected git_sha
    and (if ``origin`` is given) echoes it in access-control-allow-origin."""
    raise NotImplementedError


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
    raise NotImplementedError


def urllib_fetch(url: str, headers: Mapping[str, str], timeout_s: float) -> HttpResult:
    """The only I/O in this module."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI.

    version | serving --service-json F | tagged --service-json F --tag T
    | smoke --url U --expected-sha S [--origin O]
    """
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
