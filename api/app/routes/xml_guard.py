"""Stdlib-only XML prolog guard: forbids DTDs, checks the root is <gpx> (ADR 0004)."""

import re
from itertools import islice
from typing import Final
from xml.parsers import expat

from app.routes.errors import InvalidGpx
from app.routes.params import MAX_RAW_POINTS

# <trkpt / <rtept start tags, optionally prefixed (<gpx:trkpt>); over-counting is safe.
_POINT_START_TAG: Final = re.compile(rb"<(?:[^\s<>/]*:)?(?:trkpt|rtept)[\s/>]")


class _RootSeenError(Exception):
    """Raised by the start-element handler to stop the scan after the root."""


def _local_name(name: str) -> str:
    # With namespace_separator expat reports "uri|local"; plain names are bare.
    return name.rsplit("|", 1)[-1]


def check_gpx_prolog(data: bytes) -> None:
    """Raise InvalidGpx on DTD/entity, malformed prolog, no root, or root != gpx.

    Drives expat over the raw bytes only until the root element starts. A DOCTYPE
    can only precede the root, so the cost is the size of the prolog.
    """
    parser = expat.ParserCreate(namespace_separator="|")
    root: list[str] = []

    def reject_dtd(*_args: object) -> None:
        raise InvalidGpx("DTDs and entity declarations are not allowed in GPX files.")

    def on_start(name: str, _attrs: dict[str, str]) -> None:
        root.append(_local_name(name))
        raise _RootSeenError

    parser.StartDoctypeDeclHandler = reject_dtd
    parser.EntityDeclHandler = reject_dtd
    parser.StartElementHandler = on_start
    try:
        parser.Parse(data, True)
    except _RootSeenError:
        pass
    except expat.ExpatError as exc:
        raise InvalidGpx(
            f"The file is not well-formed XML (line {exc.lineno}, column {exc.offset})."
        ) from exc
    except (LookupError, ValueError) as exc:
        # expat: unknown encoding name -> LookupError; multi-byte/unsupported ones
        # (utf-32, utf-7, shift_jis, ...) -> ValueError. Our handlers raise neither.
        raise InvalidGpx("The file declares an unsupported XML encoding.") from exc
    if not root:
        raise InvalidGpx("The file has no XML root element.")
    if root[0] != "gpx":
        raise InvalidGpx("The file is not GPX (the root element is not <gpx>).")


def exceeds_point_cap(data: bytes, *, max_points: int = MAX_RAW_POINTS) -> bool:
    """True when data has more than max_points point start tags (ADR 0004 3.12).

    Linear: one pass of a compiled regex, stopping at the first max_points + 1 matches.
    """
    matches = islice(_POINT_START_TAG.finditer(data), max_points + 1)
    return sum(1 for _ in matches) > max_points
