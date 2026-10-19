"""CORS policy (ADR 0002 section 7). Pure: settings in, middleware args out."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# Firebase default site ID: 6-30 chars, [a-z0-9-]; '--' is rejected separately.
FIREBASE_SITE_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")


# Exact origin: http(s) scheme, host, optional port; no path/query/fragment/wildcard.
_ORIGIN_RE: Final[re.Pattern[str]] = re.compile(
    r"https?://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?\Z"
)


@dataclass(frozen=True)
class CorsPolicy:
    """CORSMiddleware arguments: exact origins plus an optional full-match regex."""

    allow_origins: tuple[str, ...]
    allow_origin_regex: str | None


def cors_policy(origins: Sequence[str], firebase_site: str | None) -> CorsPolicy:
    """Build the CORS policy from exact origins and an optional Firebase site ID.

    Raises ValueError for an invalid origin or site ID.
    """
    for origin in origins:
        if _ORIGIN_RE.fullmatch(origin) is None:
            raise ValueError(f"invalid CORS origin: {origin!r}")
    if firebase_site is None:
        return CorsPolicy(tuple(dict.fromkeys(origins)), None)
    if FIREBASE_SITE_RE.fullmatch(firebase_site) is None or "--" in firebase_site:
        raise ValueError("invalid Firebase site ID")
    site = re.escape(firebase_site)
    all_origins = (
        *origins,
        f"https://{firebase_site}.web.app",
        f"https://{firebase_site}.firebaseapp.com",
    )
    return CorsPolicy(
        tuple(dict.fromkeys(all_origins)),
        rf"https://{site}--pr-[0-9]+-[a-z0-9]+\.web\.app",
    )
