"""Pins for the namespace URI cap that the red tests could not state (ADR 0004 items
37 and 45-51).

The constant itself, the reader's default coming from it, the reader letting go of
the parser's namespace handler, and two cases that only the built code can answer.
"""

import inspect
from xml.parsers.expat import ParserCreate, XMLParserType

import pytest

from app.routes import parse as parse_module
from app.routes.errors import InvalidGpx
from app.routes.params import MAX_NAMESPACE_URI_CHARS
from app.routes.parse import _GpxReader, parse_gpx

TOO_COMPLEX = "The file is too complex to parse."
NOT_WELL_FORMED = "The file is not well-formed XML"


def long_uri(n: int) -> str:
    return "urn:" + "u" * (n - 4)


def new_reader(**kwargs: int) -> tuple[XMLParserType, _GpxReader]:
    parser = ParserCreate(encoding="UTF-8", namespace_separator="|", intern=None)
    return parser, _GpxReader(parser, max_points=100, **kwargs)


def test_the_cap_constant_is_256() -> None:
    value: int = MAX_NAMESPACE_URI_CHARS  # widened: the constant is a Final literal
    assert value == 256


def test_the_reader_default_comes_from_the_constant() -> None:
    default = (
        inspect.signature(_GpxReader.__init__)
        .parameters["max_namespace_uri_chars"]
        .default
    )
    assert default == MAX_NAMESPACE_URI_CHARS


def test_a_reader_built_with_the_default_refuses_one_character_over_the_constant() -> (
    None
):
    parser, reader = new_reader()
    try:
        parser.Parse(f'<gpx xmlns:x="{long_uri(256)}"/>'.encode(), True)
    finally:
        reader.detach()
    parser, reader = new_reader()
    try:
        with pytest.raises(InvalidGpx) as excinfo:
            parser.Parse(f'<gpx xmlns:x="{long_uri(257)}"/>'.encode(), True)
    finally:
        reader.detach()
    assert excinfo.value.message == TOO_COMPLEX


def test_a_reader_built_with_the_default_refuses_a_short_non_ascii_uri() -> None:
    parser, reader = new_reader()
    try:
        with pytest.raises(InvalidGpx) as excinfo:
            parser.Parse('<gpx xmlns:x="urn:é"/>'.encode(), True)
    finally:
        reader.detach()
    assert excinfo.value.message == TOO_COMPLEX
    assert excinfo.value.__cause__ is None


def test_a_reader_built_with_the_default_accepts_xmlns_empty() -> None:
    parser, reader = new_reader()
    try:
        parser.Parse(b'<gpx xmlns="urn:x"><a xmlns=""/></gpx>', True)
    finally:
        reader.detach()


def test_a_reader_honours_an_explicit_limit() -> None:
    parser, reader = new_reader(max_namespace_uri_chars=10)
    try:
        with pytest.raises(InvalidGpx):
            parser.Parse(f'<gpx xmlns:x="{long_uri(11)}"/>'.encode(), True)
    finally:
        reader.detach()


def test_detach_clears_the_namespace_declaration_handler() -> None:
    parser, reader = new_reader()
    assert parser.StartNamespaceDeclHandler is not None  # the guard: it was set
    reader.detach()
    assert parser.StartNamespaceDeclHandler is None


def test_detach_clears_every_handler_the_reader_installed() -> None:
    parser, reader = new_reader()
    reader.detach()
    for handler in (
        "XmlDeclHandler",
        "StartDoctypeDeclHandler",
        "EntityDeclHandler",
        "StartNamespaceDeclHandler",
        "StartElementHandler",
        "EndElementHandler",
        "CharacterDataHandler",
    ):
        assert getattr(parser, handler) is None, handler


@pytest.fixture
def captured_parsers(monkeypatch: pytest.MonkeyPatch) -> list[XMLParserType]:
    made: list[XMLParserType] = []
    real = parse_module._new_parser

    def spy(
        *, alloc_threshold_bytes: int, alloc_max_amplification: float
    ) -> XMLParserType:
        parser = real(
            alloc_threshold_bytes=alloc_threshold_bytes,
            alloc_max_amplification=alloc_max_amplification,
        )
        made.append(parser)
        return parser

    monkeypatch.setattr(parse_module, "_new_parser", spy)
    return made


def test_parse_gpx_lets_go_of_the_namespace_handler_after_returning(
    captured_parsers: list[XMLParserType],
) -> None:
    parse_gpx(b'<gpx xmlns="urn:x"><trk><trkseg/></trk></gpx>')
    assert len(captured_parsers) == 1
    assert captured_parsers[0].StartNamespaceDeclHandler is None


def test_parse_gpx_lets_go_of_the_namespace_handler_after_a_cap_refusal(
    captured_parsers: list[XMLParserType],
) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(f'<gpx xmlns="{long_uri(257)}"/>'.encode())
    assert len(captured_parsers) == 1
    assert captured_parsers[0].StartNamespaceDeclHandler is None


# --- the two ADR cases that were not reachable before the build ---


def test_xmlns_prefix_bound_to_empty_is_not_well_formed_not_too_complex() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(b'<gpx xmlns:p=""><trk><trkseg/></trk></gpx>')
    assert excinfo.value.message.startswith(NOT_WELL_FORMED)


def nested_to_65(declaration: str) -> bytes:
    """<gpx> plus 63 levels, then the element at depth 65 carrying ``declaration``."""
    return (
        "<gpx>" + "<a>" * 63 + f"<b {declaration}/>" + "</a>" * 63 + "</gpx>"
    ).encode()


def test_guard_depth_65_alone_is_nested_too_deeply() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(nested_to_65(""))
    assert excinfo.value.message == "The file's XML is nested too deeply."


def test_guard_depth_64_with_a_short_declaration_parses() -> None:
    data = (
        "<gpx>" + "<a>" * 62 + '<b xmlns:x="urn:x"/>' + "</a>" * 62 + "</gpx>"
    ).encode()
    assert parse_gpx(data).points == ()


def test_a_long_uri_at_depth_65_gives_too_complex_not_nested_too_deeply() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(nested_to_65(f'xmlns:x="{long_uri(257)}"'))
    assert excinfo.value.message == TOO_COMPLEX


def test_a_short_uri_on_the_element_at_depth_65_still_gives_nested_too_deeply() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(nested_to_65('xmlns:x="urn:x"'))
    assert excinfo.value.message == "The file's XML is nested too deeply."
