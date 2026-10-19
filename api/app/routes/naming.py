"""Route name selection (ADR 0004 §3.9)."""

import re
import unicodedata

from app.routes.params import MAX_NAME_LENGTH, UNTITLED_ROUTE_NAME

_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str | None) -> str:
    """Strip control characters, collapse whitespace, trim, cut to the name limit."""
    if text is None:
        return ""
    kept = "".join(c for c in text if unicodedata.category(c) != "Cc")
    return _WHITESPACE.sub(" ", kept).strip()[:MAX_NAME_LENGTH].strip()


def _filename_stem(filename: str | None) -> str | None:
    if filename is None:
        return None
    base = re.split(r"[/\\]", filename)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem.replace("_", " ")


def route_name(
    metadata_name: str | None, track_name: str | None, filename: str | None
) -> str:
    """First non-blank of metadata name, track name, filename stem, else a default."""
    for candidate in (metadata_name, track_name, _filename_stem(filename)):
        name = _normalise(candidate)
        if name:
            return name
    return UNTITLED_ROUTE_NAME
