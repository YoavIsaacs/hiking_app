"""GPX bytes to RawTrack: our own single-pass reader on stdlib expat (ADR 0004 3.1).

Handlers build only what RawTrack needs; every other element is skipped with a counter.
DTD rejection, the root check, the depth cap and the point cap are handlers of the
same pass, so nothing is scanned twice and nothing grows with skipped elements.
"""

import codecs
import math
from collections.abc import Sequence
from typing import Final, NoReturn
from xml.parsers.expat import (
    ExpatError,
    ParserCreate,
    XMLParserType,
    errors,
    version_info,
)

from app.models.route import SourceFormat
from app.routes.errors import InvalidGpx, TooManyPoints
from app.routes.params import (
    EXPAT_ALLOC_ACTIVATION_BYTES,
    EXPAT_ALLOC_MAX_AMPLIFICATION,
    MAX_CAPTURED_TEXT_CHARS,
    MAX_NAMESPACE_URI_CHARS,
    MAX_PLAUSIBLE_ELEV_M,
    MAX_RAW_POINTS,
    MAX_XML_DEPTH,
    MIN_PLAUSIBLE_ELEV_M,
)
from app.routes.track import RawPoint, RawTrack

_META_NAME: Final = 1
_TRK_NAME: Final = 2
_RTE_NAME: Final = 3
_TRKPT: Final = 4
_RTEPT: Final = 5
_ELE: Final = 6
# Expat copies a large single Parse() buffer; feeding slices keeps its memory constant.
_CHUNK_BYTES: Final = 64 * 1024
_MIN_EXPAT_VERSION: Final = (2, 7, 2)
_NESTED_POINT: Final = 7  # a point tag inside a point: counted for the cap, never read
# ADR 0004 3.1 step 5: the message for an expat resource refusal (tests assert it)
TOO_COMPLEX_MESSAGE: Final = "The file is too complex to parse."
_RESOURCE_ERROR_CODES: Final[frozenset[int]] = frozenset(
    {
        errors.codes[
            errors.XML_ERROR_NO_MEMORY
        ],  # what an allocation-tracker refusal reports
        errors.codes[errors.XML_ERROR_AMPLIFICATION_LIMIT_BREACH],  # defensive
    }
)


def require_alloc_tracker(
    parser_type: type[object] = XMLParserType,
    expat_version: tuple[int, int, int] = version_info,
) -> None:
    """Raise RuntimeError unless the expat allocation tracker exists (ADR 0004 3.11)."""
    missing = [
        name
        for name in (
            "SetAllocTrackerActivationThreshold",
            "SetAllocTrackerMaximumAmplification",
        )
        if not hasattr(parser_type, name)
    ]
    if missing:
        raise RuntimeError(
            "The expat allocation tracker is missing: the parser lacks "
            + " and ".join(missing)
            + "; it needs libexpat 2.7.2 and CPython 3.12.13 or later."
        )
    if expat_version < _MIN_EXPAT_VERSION:
        found = ".".join(map(str, expat_version))
        raise RuntimeError(
            f"The expat allocation tracker needs libexpat 2.7.2+, found {found}."
        )


# no tracker, no app: this runs when app.routes.parse (and so app.main) is imported
require_alloc_tracker()


def _new_parser(
    *, alloc_threshold_bytes: int, alloc_max_amplification: float
) -> XMLParserType:
    """The only ParserCreate call in app/ (ADR 0004 3.11)."""
    parser = ParserCreate(encoding="UTF-8", namespace_separator="|", intern=None)
    parser.ordered_attributes = True
    parser.buffer_text = True
    parser.SetAllocTrackerActivationThreshold(alloc_threshold_bytes)
    parser.SetAllocTrackerMaximumAmplification(alloc_max_amplification)
    return parser


def _invalid_gpx_from(exc: ExpatError) -> InvalidGpx:
    """Map an ExpatError to InvalidGpx; resource codes get TOO_COMPLEX_MESSAGE."""
    if exc.code in _RESOURCE_ERROR_CODES:
        return InvalidGpx(TOO_COMPLEX_MESSAGE)
    return InvalidGpx(
        f"The file is not well-formed XML (line {exc.lineno}, column {exc.offset})."
    )


class _Node:
    """One element path the reader cares about (ADR 0004 3.1 table)."""

    __slots__ = ("children", "kind")

    def __init__(self, kind: int = 0, **children: "_Node") -> None:
        self.kind = kind
        self.children = children


_TRKPT_NODE: Final = _Node(_TRKPT, ele=_Node(_ELE))
_RTEPT_NODE: Final = _Node(_RTEPT, ele=_Node(_ELE))
for _point_node, _tag in ((_TRKPT_NODE, "trkpt"), (_RTEPT_NODE, "rtept")):
    # An unclosed <trkpt> nests the next one. It is not a point, but it is counted,
    # so a file of bare start tags still hits the cap (ADR 0004 3.12).
    _nested = _Node(_NESTED_POINT)
    _nested.children[_tag] = _nested
    _point_node.children[_tag] = _nested

# <gpx> itself; its children are the paths below it that the reader keeps.
_GPX: Final = _Node(
    metadata=_Node(name=_Node(_META_NAME)),
    name=_Node(_META_NAME),
    trk=_Node(
        name=_Node(_TRK_NAME),
        trkseg=_Node(trkpt=_TRKPT_NODE),
    ),
    rte=_Node(name=_Node(_RTE_NAME), rtept=_RTEPT_NODE),
)


def _reject_dtd(*_args: object) -> NoReturn:
    raise InvalidGpx("DTDs and entity declarations are not allowed in GPX files.")


def _encoding_supported(name: str) -> bool:
    """pyexpat's rule: UTF-8, or a codec mapping 256 byte values to 256 characters."""
    try:
        if codecs.lookup(name).name == "utf-8":
            return True
        return len(bytes(range(256)).decode(name, "replace")) == 256
    except (LookupError, ValueError):
        return False


def _parse_float(text: str | None) -> float | None:
    """float(text.strip()); None when missing, unparseable or not finite."""
    if text is None:
        return None
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class _GpxReader:
    """The expat handlers of one parse. Created per call, never shared."""

    def __init__(
        self,
        parser: XMLParserType,
        *,
        max_points: int,
        max_depth: int = MAX_XML_DEPTH,
        max_text_chars: int = MAX_CAPTURED_TEXT_CHARS,
        max_namespace_uri_chars: int = MAX_NAMESPACE_URI_CHARS,
    ) -> None:
        self._parser = parser
        self._max_namespace_uri_chars = max_namespace_uri_chars
        self._max_text_chars = max_text_chars
        self._max_points = max_points
        self._max_depth = max_depth
        self._depth = 0
        self._skip = 0  # >0: inside an element we ignore; counts its open levels
        self._ns = ""
        self._stack: list[_Node] = []
        self._capturing = False
        self._chunks: list[str] = []
        self._text_len = 0
        self._overflow = False
        self._meta_seen = False
        self._meta_name: str | None = None
        self._trk_name: str | None = None
        self._rte_name: str | None = None
        self._total = 0
        self._trk_count = 0
        self._rte_count = 0
        self._trk: list[RawPoint] = []
        self._rte: list[RawPoint] = []
        self._trk_error: str | None = None
        self._rte_error: str | None = None
        self._lat = 0.0
        self._lon = 0.0
        self._point_error: str | None = None
        self._ele: float | None = None
        self._ele_seen = False
        parser.XmlDeclHandler = self.on_xml_decl
        parser.StartDoctypeDeclHandler = _reject_dtd
        parser.EntityDeclHandler = _reject_dtd
        parser.StartNamespaceDeclHandler = self.on_namespace_decl
        parser.StartElementHandler = self.on_start
        parser.EndElementHandler = self.on_end

    def detach(self) -> None:
        """Drop the parser's references to us (breaks the parser <-> reader cycle)."""
        parser = self._parser
        parser.XmlDeclHandler = None
        parser.StartDoctypeDeclHandler = None
        parser.EntityDeclHandler = None
        parser.StartNamespaceDeclHandler = None
        parser.StartElementHandler = None
        parser.EndElementHandler = None
        parser.CharacterDataHandler = None

    def on_xml_decl(
        self, version: str | None, encoding: str | None, standalone: int
    ) -> None:
        if encoding is not None and not _encoding_supported(encoding):
            raise InvalidGpx("The file declares an unsupported XML encoding.")

    def on_namespace_decl(self, prefix: str | None, uri: str | None) -> None:
        """ADR 0004 3.1 step 4: a namespace URI over the cap is too complex."""
        if uri is not None and len(uri) > self._max_namespace_uri_chars:
            raise InvalidGpx(TOO_COMPLEX_MESSAGE)

    def _skip_element(self) -> None:
        self._skip = 1
        if self._capturing:
            self._parser.CharacterDataHandler = None  # child text is not ours

    def on_start(self, name: str, attrs: list[str]) -> None:
        depth = self._depth + 1
        self._depth = depth
        if depth > self._max_depth:
            raise InvalidGpx("The file's XML is nested too deeply.")
        if self._skip:
            self._skip += 1
            return
        ns, _, local = name.rpartition("|")
        if depth == 1:
            if local != "gpx":
                raise InvalidGpx("The file is not GPX (the root is not <gpx>).")
            self._ns = ns
            self._stack.append(_GPX)
            return
        node = self._stack[-1].children.get(local) if ns == self._ns else None
        if node is None:
            self._skip_element()
            return
        self._stack.append(node)
        kind = node.kind
        if kind in (_TRKPT, _RTEPT):
            self._start_point(kind, attrs)
        elif kind == _NESTED_POINT:
            self._count_point()
        elif kind == _ELE:
            if not self._ele_seen:
                self._ele_seen = True
                self._begin_capture()
        elif kind == _META_NAME:
            if not self._meta_seen:
                self._meta_seen = True
                self._begin_capture()
        elif kind == _TRK_NAME:
            if self._trk_name is None:
                self._begin_capture()
        elif kind == _RTE_NAME and self._rte_name is None:
            self._begin_capture()

    def _begin_capture(self) -> None:
        self._capturing = True
        self._chunks = []
        self._text_len = 0
        self._overflow = False
        self._parser.CharacterDataHandler = self.on_text

    def on_text(self, data: str) -> None:
        if self._overflow:
            return  # never swap the handler from inside it; just keep nothing
        room = self._max_text_chars - self._text_len
        if len(data) > room:
            self._chunks.append(data[:room])
            self._text_len = self._max_text_chars
            self._overflow = True
        else:
            self._chunks.append(data)
            self._text_len += len(data)

    def _count_point(self) -> None:
        self._total += 1
        if self._total > self._max_points:
            raise TooManyPoints(
                f"The file has more than {self._max_points:,} track points."
            )

    def _start_point(self, kind: int, attrs: list[str]) -> None:
        self._count_point()
        if kind == _TRKPT:
            self._trk_count += 1
            if self._trk_count == 2:  # rte can no longer be chosen
                self._rte = []
                self._rte_error = None
        else:
            self._rte_count += 1
        lat_text: str | None = None
        lon_text: str | None = None
        for i in range(0, len(attrs), 2):
            key = attrs[i]
            if key == "lat":
                lat_text = attrs[i + 1]
            elif key == "lon":
                lon_text = attrs[i + 1]
        lat = _parse_float(lat_text)
        lon = _parse_float(lon_text)
        if lat is None or lon is None:
            self._point_error = "A track point has a missing or invalid coordinate."
        elif not -90.0 <= lat <= 90.0:
            self._point_error = "A track point has a latitude outside -90..90."
        elif not -180.0 <= lon <= 180.0:
            self._point_error = "A track point has a longitude outside -180..180."
        else:
            self._point_error = None
            self._lat = lat
            self._lon = lon
        self._ele = None
        self._ele_seen = False

    def on_end(self, name: str) -> None:
        self._depth -= 1
        if self._skip:
            self._skip -= 1
            if not self._skip and self._capturing and not self._overflow:
                self._parser.CharacterDataHandler = self.on_text
            return
        kind = self._stack.pop().kind
        if self._capturing:
            self._capturing = False
            self._parser.CharacterDataHandler = None
            overflow = self._overflow
            self._overflow = False
            self._finish_capture(kind, "".join(self._chunks), overflow)
            self._chunks = []
        elif kind in (_TRKPT, _RTEPT):
            self._end_point(kind)

    def _finish_capture(self, kind: int, text: str, overflow: bool) -> None:
        if kind == _ELE:
            ele = None if overflow else _parse_float(text)
            if ele is not None and MIN_PLAUSIBLE_ELEV_M <= ele <= MAX_PLAUSIBLE_ELEV_M:
                self._ele = ele
        elif kind == _META_NAME:
            self._meta_name = text
        elif text.strip():
            if kind == _TRK_NAME:
                self._trk_name = text
            else:
                self._rte_name = text

    def _end_point(self, kind: int) -> None:
        error = self._point_error
        if kind == _TRKPT:
            if error is None:
                self._trk.append(RawPoint(self._lat, self._lon, self._ele))
            elif self._trk_error is None:
                self._trk_error = error
        elif self._trk_count < 2:
            if error is None:
                self._rte.append(RawPoint(self._lat, self._lon, self._ele))
            elif self._rte_error is None:
                self._rte_error = error

    def result(self) -> RawTrack:
        """Choose the source, then validate that kind only (ADR 0004 3.1 steps 6-8)."""
        trk_n, rte_n = self._trk_count, self._rte_count
        source: SourceFormat
        if trk_n >= 2:
            source = "trk"
        elif rte_n >= 2:
            source = "rte"
        else:
            source = "rte" if rte_n > trk_n else "trk"
        if source == "trk":
            error, points, track_name = self._trk_error, self._trk, self._trk_name
        else:
            error, points, track_name = self._rte_error, self._rte, self._rte_name
        if error is not None:
            raise InvalidGpx(error)
        return RawTrack(
            points=tuple(points),
            source_format=source,
            metadata_name=self._meta_name,
            track_name=track_name,
        )


def parse_gpx(
    data: bytes,
    *,
    max_points: int = MAX_RAW_POINTS,
    alloc_threshold_bytes: int = EXPAT_ALLOC_ACTIVATION_BYTES,
    alloc_max_amplification: float = EXPAT_ALLOC_MAX_AMPLIFICATION,
) -> RawTrack:
    """Read the GPX bytes in one expat pass. Raises InvalidGpx or TooManyPoints only."""
    if not data:
        raise InvalidGpx("The file is empty.")
    if b"\x00" in data:
        # XML 1.0 forbids U+0000, and every UTF-16/UTF-32 document contains it.
        raise InvalidGpx("The file must be UTF-8 encoded.")
    parser = _new_parser(
        alloc_threshold_bytes=alloc_threshold_bytes,
        alloc_max_amplification=alloc_max_amplification,
    )
    reader = _GpxReader(parser, max_points=max_points)
    try:
        view = memoryview(data)
        for start in range(0, len(view), _CHUNK_BYTES):
            parser.Parse(view[start : start + _CHUNK_BYTES], False)
        parser.Parse(b"", True)
    except ExpatError as exc:
        raise _invalid_gpx_from(exc) from exc
    finally:
        reader.detach()
    return reader.result()


def drop_consecutive_duplicates(points: Sequence[RawPoint]) -> tuple[RawPoint, ...]:
    """Drop points whose (lat, lon) equals the previous kept point's; first one wins."""
    out: list[RawPoint] = []
    for p in points:
        if not out or (out[-1].lat, out[-1].lon) != (p.lat, p.lon):
            out.append(p)
    return tuple(out)
