"""CORS policy (ADR 0002 section 7). Pure: settings in, middleware args out."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# Firebase default site ID: 6-30 chars, [a-z0-9-]; '--' is rejected separately.
FIREBASE_SITE_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


@dataclass(frozen=True)
class CorsPolicy:
    """CORSMiddleware arguments: exact origins plus an optional full-match regex."""

    allow_origins: tuple[str, ...]
    allow_origin_regex: str | None


def cors_policy(origins: Sequence[str], firebase_site: str | None) -> CorsPolicy:
    """Build the CORS policy from exact origins and an optional Firebase site ID.

    Raises ValueError for an invalid origin or site ID (implemented in the build step).
    """
    raise NotImplementedError
