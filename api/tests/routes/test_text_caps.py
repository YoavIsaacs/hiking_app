"""Captured text is capped at MAX_CAPTURED_TEXT_CHARS = 65,536 characters
(ADR 0004 round-3 amendment, item 31; 3.1 "Text capture"; rows H6 and L4).

Above the cap a ``<name>`` keeps its first 65,536 characters and an ``<ele>`` counts as
missing. Nothing is rejected.
"""

import tracemalloc
from collections.abc import Callable

import pytest

from app.routes.params import MAX_CAPTURED_TEXT_CHARS
from app.routes.parse import _CHUNK_BYTES, parse_gpx
from app.routes.summary import summarise_gpx
from tests.routes.gpx_builders import gpx_bytes, out_and_back

CAP = 65_536
NS = "http://www.topografix.com/GPX/1/1"
TRK_BODY = '<trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg>'


def gpx(body: str) -> bytes:
    return f'<gpx xmlns="{NS}">{body}</gpx>'.encode()


def point_with_ele(*eles: str) -> bytes:
    inner = "".join(f"<ele>{e}</ele>" for e in eles)
    return gpx(f'<trk><trkseg><trkpt lat="1" lon="1">{inner}</trkpt></trkseg></trk>')


def test_the_cap_is_65536_characters() -> None:
    assert MAX_CAPTURED_TEXT_CHARS == CAP


# --- names ---


def name_body(where: str, text: str) -> str:
    if where == "metadata":
        return f"<metadata><name>{text}</name></metadata><trk>{TRK_BODY}</trk>"
    if where == "trk":
        return f"<trk><name>{text}</name>{TRK_BODY}</trk>"
    return (
        f"<rte><name>{text}</name>"
        '<rtept lat="1" lon="1"/><rtept lat="2" lon="2"/></rte>'
    )


def name_in(where: str, text: str) -> bytes:
    return gpx(name_body(where, text))


def read_name(where: str, text: str) -> str | None:
    raw = parse_gpx(name_in(where, text))
    return raw.metadata_name if where == "metadata" else raw.track_name


@pytest.mark.parametrize("where", ["metadata", "trk", "rte"])
def test_a_name_longer_than_the_cap_is_cut_to_exactly_65536_characters(
    where: str,
) -> None:
    text = "ab" * (CAP // 2) + "tail that must go"
    assert read_name(where, text) == text[:CAP]
    name = read_name(where, text)
    assert name is not None and len(name) == 65_536


@pytest.mark.parametrize("where", ["metadata", "trk", "rte"])
def test_a_name_of_exactly_the_cap_is_kept_whole(where: str) -> None:
    text = "x" * CAP
    assert read_name(where, text) == text


@pytest.mark.parametrize("where", ["metadata", "trk", "rte"])
def test_a_name_one_character_over_the_cap_loses_only_that_character(
    where: str,
) -> None:
    text = "x" * CAP + "y"
    assert read_name(where, text) == "x" * CAP


@pytest.mark.parametrize("where", ["metadata", "trk", "rte"])
def test_references_and_cdata_count_in_decoded_characters(where: str) -> None:
    text = "&amp;" * (CAP + 10)  # 5 source characters each, 1 decoded
    name = read_name(where, text)
    assert name == "&" * CAP
    cdata = "<![CDATA[" + "z" * (CAP + 10) + "]]>"
    assert read_name(where, cdata) == "z" * CAP


def test_a_skipped_child_inside_an_overflowed_name_does_not_resume_the_capture() -> (
    None
):
    text = "a" * (CAP + 5) + "<b>child text</b>" + "tail"
    assert read_name("trk", text) == "a" * CAP


def test_an_over_long_all_whitespace_trk_name_is_blank_and_the_next_one_is_used() -> (
    None
):
    blank = " " * (CAP + 100) + "x"  # not blank uncapped; blank once cut
    doc = gpx(
        f"<trk><name>{blank}</name>{TRK_BODY}</trk><trk><name>Second</name></trk>"
    )
    assert parse_gpx(doc).track_name == "Second"


def test_an_over_long_all_whitespace_rte_name_is_blank_and_the_next_one_is_used() -> (
    None
):
    blank = "\n" * (CAP + 100) + "x"
    points = '<rtept lat="1" lon="1"/><rtept lat="2" lon="2"/>'
    doc = gpx(f"<rte><name>{blank}</name>{points}</rte><rte><name>Second</name></rte>")
    assert parse_gpx(doc).track_name == "Second"


def test_an_over_long_blank_metadata_name_falls_through_to_the_track_name() -> None:
    blank = " " * (CAP + 100) + "x"
    data = gpx_bytes(
        [out_and_back()], metadata_name=blank, track_names=["Fallback track"]
    )
    assert summarise_gpx(data, "file.gpx").name == "Fallback track"


def test_an_over_long_blank_metadata_and_track_name_fall_through_to_the_filename() -> (
    None
):
    blank = " " * (CAP + 100) + "x"
    data = gpx_bytes(
        [out_and_back()], metadata_name=blank, track_names=[blank], version="1.1"
    )
    assert summarise_gpx(data, "from_file.gpx").name == "from file"


def test_an_over_long_name_is_not_a_rejection() -> None:
    data = gpx_bytes([out_and_back()], metadata_name="n" * (CAP * 3))
    assert summarise_gpx(data, "f.gpx").name == "n" * 200


# --- <ele> ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0" * (CAP - 4) + "12.5", 12.5),  # exactly the cap: kept, row L4
        ("0" * (CAP - 3) + "12.5", None),  # one character over
        ("0" * (CAP + 10_000) + "12.5", None),
        (" " * (CAP + 1) + "12.5", None),
    ],
    ids=["exactly-cap", "one-over", "far-over", "whitespace-padded"],
)
def test_an_ele_over_the_cap_counts_as_missing(
    text: str, expected: float | None
) -> None:
    assert parse_gpx(point_with_ele(text)).points[0].elev_m == expected


def test_an_overflowed_first_ele_is_still_the_first_so_a_valid_second_is_ignored() -> (
    None
):
    doc = point_with_ele("0" * (CAP + 1) + "12.5", "100")
    assert parse_gpx(doc).points[0].elev_m is None


def test_a_valid_first_ele_wins_over_an_overflowed_second() -> None:
    doc = point_with_ele("100", "0" * (CAP + 1) + "12.5")
    assert parse_gpx(doc).points[0].elev_m == 100.0


def test_an_overflowed_ele_makes_the_summary_report_no_elevation_but_still_200() -> (
    None
):
    body = "".join(
        f'<trkpt lat="{p.lat!r}" lon="{p.lon!r}"><ele>'
        + ("0" * (CAP + 1) + "5" if i == 0 else f"{p.ele!r}")
        + "</ele></trkpt>"
        for i, p in enumerate(out_and_back())
    )
    summary = summarise_gpx(gpx(f"<trk><trkseg>{body}</trkseg></trk>"), "f.gpx")
    assert summary.has_elevation is False


def test_a_metadata_name_of_exactly_the_cap_is_cut_to_200_by_route_name() -> None:
    data = gpx_bytes([out_and_back()], metadata_name="m" * CAP)
    assert summarise_gpx(data, "f.gpx").name == "m" * 200


# --- memory: a 10 MiB text node keeps nothing ---


def peak_of(parse_input: bytes) -> int:
    tracemalloc.start()
    try:
        parse_gpx(parse_input)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("where", ["metadata", "ele"])
def test_a_10_mib_text_node_costs_no_more_memory_than_a_1_kib_one(where: str) -> None:
    def doc(size: int) -> bytes:
        text = "a" * size if where == "metadata" else "0" * size
        if where == "metadata":
            return name_in("metadata", text)
        return point_with_ele(text)

    small, huge = doc(1024), doc(10 * 1024 * 1024)
    parse_gpx(small)  # warm up imports and caches
    assert peak_of(huge) - peak_of(small) <= 2 * 1024 * 1024


# --- more character data in a later callback once the capture is exactly full ---

# parse_gpx feeds expat 64 KiB at a time and pyexpat flushes its text buffer at the
# end of each feed, so character data arrives in a separate callback whenever it
# crosses a feed boundary. Padding with whitespace puts the start of the text exactly
# on a boundary: the first callback is then exactly the cap and `extra` arrives in a
# second one, which is the reader's "no room left" branch. (A CDATA section, a
# reference, a comment or a PI inside one feed is merged into the same callback by
# buffer_text, so on their own they would not do.)
LATER_CALLBACK = {
    "plain": "more",
    "cdata": "<![CDATA[more]]>",
    "entity": "&amp;",
    "char-ref": "&#65;",
    "comment": "<!--c-->more",
    "pi": "<?p x?>more",
}


def starts_on_a_feed_boundary(build: Callable[[str], bytes], text: str) -> bytes:
    """build(pad) with `pad` spaces so that `text` begins at byte _CHUNK_BYTES."""
    probe = build("")
    pad = _CHUNK_BYTES - probe.index(text[:20].encode())
    assert pad >= 0
    doc = build(" " * pad)
    assert doc.index(text[:20].encode()) == _CHUNK_BYTES
    return doc


@pytest.mark.parametrize("where", ["metadata", "trk", "rte"])
@pytest.mark.parametrize("extra", LATER_CALLBACK.values(), ids=LATER_CALLBACK.keys())
def test_a_name_exactly_full_then_more_text_in_a_later_callback_keeps_the_first_cap(
    where: str, extra: str
) -> None:
    def build(pad: str) -> bytes:
        return gpx(pad + name_body(where, "x" * CAP + extra))

    doc = starts_on_a_feed_boundary(build, "x" * CAP)
    raw = parse_gpx(doc)
    name = raw.metadata_name if where == "metadata" else raw.track_name
    assert name == "x" * CAP


@pytest.mark.parametrize("extra", LATER_CALLBACK.values(), ids=LATER_CALLBACK.keys())
def test_an_ele_exactly_full_then_more_text_in_a_later_callback_counts_as_missing(
    extra: str,
) -> None:
    text = "0" * (CAP - 4) + "12.5"

    def build(pad: str) -> bytes:
        return gpx(
            pad
            + '<trk><trkseg><trkpt lat="1" lon="1">'
            + f"<ele>{text}{extra}</ele></trkpt></trkseg></trk>"
        )

    doc = starts_on_a_feed_boundary(build, text)
    assert parse_gpx(doc).points[0].elev_m is None


def test_an_ele_exactly_full_with_nothing_after_it_is_still_kept() -> None:
    assert parse_gpx(point_with_ele("0" * (CAP - 4) + "12.5")).points[0].elev_m == 12.5
