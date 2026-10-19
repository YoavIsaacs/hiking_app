"""What the expat reader reads and what it skips (ADR 0004 section 3.1, "What the
handlers read"): namespaces, structure, names, ``<ele>``, source choice, UTF-8.

Pure ``parse_gpx`` tests: bytes in, ``RawTrack`` or ``InvalidGpx`` out.
"""

import pytest

from app.routes.errors import InvalidGpx
from app.routes.parse import parse_gpx
from app.routes.track import RawPoint

NS11 = "http://www.topografix.com/GPX/1/1"
NS10 = "http://www.topografix.com/GPX/1/0"


def pt(tag: str, lat: float, lon: float, inner: str = "") -> str:
    return f'<{tag} lat="{lat}" lon="{lon}">{inner}</{tag}>'


def trk(*points: str, name: str = "") -> str:
    return f"<trk>{name}<trkseg>{''.join(points)}</trkseg></trk>"


def rte(*points: str, name: str = "") -> str:
    return f"<rte>{name}{''.join(points)}</rte>"


def gpx(body: str, *, ns: str = NS11) -> bytes:
    return f'<gpx version="1.1" creator="t" xmlns="{ns}">{body}</gpx>'.encode()


TWO = (pt("trkpt", 1, 1), pt("trkpt", 2, 2))
RTE_TWO = (pt("rtept", 3, 3), pt("rtept", 4, 4))


# --- namespaces ---


def test_a_prefixed_document_yields_its_points_elevations_and_names() -> None:
    doc = (
        f'<g:gpx xmlns:g="{NS11}" version="1.1" creator="t">'
        "<g:metadata><g:name>Meta</g:name></g:metadata>"
        "<g:trk><g:name>Trk</g:name><g:trkseg>"
        '<g:trkpt lat="1" lon="1"><g:ele>5</g:ele></g:trkpt>'
        '<g:trkpt lat="2" lon="2"><g:ele>6</g:ele></g:trkpt>'
        "</g:trkseg></g:trk></g:gpx>"
    )
    raw = parse_gpx(doc.encode())
    assert raw.points == (RawPoint(1, 1, 5.0), RawPoint(2, 2, 6.0))
    assert raw.metadata_name == "Meta"
    assert raw.track_name == "Trk"
    assert raw.source_format == "trk"


def test_a_prefixed_rte_document_yields_its_points() -> None:
    doc = (
        f'<g:gpx xmlns:g="{NS11}"><g:rte><g:rtept lat="3" lon="3"/>'
        '<g:rtept lat="4" lon="4"/></g:rte></g:gpx>'
    )
    raw = parse_gpx(doc.encode())
    assert raw.source_format == "rte"
    assert raw.points == (RawPoint(3, 3, None), RawPoint(4, 4, None))


def test_a_different_prefix_for_the_same_namespace_on_children_is_read() -> None:
    doc = (
        f'<gpx xmlns="{NS11}" xmlns:z="{NS11}"><z:trk><z:trkseg>'
        '<z:trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></z:trkseg></z:trk></gpx>'
    )
    assert len(parse_gpx(doc.encode()).points) == 2


def test_a_gpx_root_in_any_other_namespace_is_accepted_and_read() -> None:
    raw = parse_gpx(gpx(trk(*TWO), ns="urn:something-else"))
    assert len(raw.points) == 2


def test_a_gpx_10_root_is_read() -> None:
    assert len(parse_gpx(gpx(trk(*TWO), ns=NS10)).points) == 2


def test_a_foreign_namespace_trk_under_a_1_1_root_is_skipped() -> None:
    foreign = (
        '<trk xmlns="urn:other"><trkseg>'
        + "".join(pt("trkpt", 9, 9) for _ in range(5))
        + "</trkseg></trk>"
    )
    raw = parse_gpx(gpx(foreign + rte(*RTE_TWO)))
    assert raw.source_format == "rte"  # the foreign trk did not count as a track
    assert raw.points == (RawPoint(3, 3, None), RawPoint(4, 4, None))


def test_a_foreign_namespace_trk_does_not_add_points_to_the_real_one() -> None:
    foreign = (
        '<x:trk xmlns:x="urn:other"><x:trkseg>'
        '<x:trkpt lat="9" lon="9"/></x:trkseg></x:trk>'
    )
    raw = parse_gpx(gpx(foreign + trk(*TWO)))
    assert raw.points == (RawPoint(1, 1, None), RawPoint(2, 2, None))


def test_a_foreign_namespace_name_and_ele_are_ignored() -> None:
    doc = gpx(
        '<x:name xmlns:x="urn:o">Foreign</x:name>'
        + trk(
            '<trkpt lat="1" lon="1"><x:ele xmlns:x="urn:o">77</x:ele></trkpt>',
            pt("trkpt", 2, 2),
        )
    )
    raw = parse_gpx(doc)
    assert raw.metadata_name is None
    assert raw.points[0].elev_m is None


@pytest.mark.parametrize(
    "doc",
    [
        pytest.param(f'<g:gpx xmlns:h="{NS11}"/>', id="root-prefix-unbound"),
        pytest.param("<gpx><x:foo/></gpx>", id="child-prefix-unbound"),
        pytest.param(
            f'<gpx xmlns="{NS11}"><trk><trkseg><z:trkpt lat="1" lon="1"/>'
            "</trkseg></trk></gpx>",
            id="point-prefix-unbound",
        ),
        pytest.param('<gpx><trk x:attr="1"/></gpx>', id="attribute-prefix-unbound"),
        pytest.param(
            f'<g:gpx xmlns:g="{NS11}"><h:trk/></g:gpx>', id="sibling-prefix-unbound"
        ),
    ],
)
def test_an_unbound_prefix_is_invalid_gpx(doc: str) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(doc.encode())


def test_xmlns_declarations_do_not_reach_the_point_attributes() -> None:
    doc = gpx(
        trk(
            '<trkpt lat="1" lon="1" xmlns:foo="urn:foo" foo:bar="x"/>',
            '<trkpt lat="2" lon="2" xmlns:bar="urn:bar"/>',
        )
    )
    assert [(p.lat, p.lon) for p in parse_gpx(doc).points] == [(1, 1), (2, 2)]


# --- structure ---


def test_trkpt_inside_extensions_wpt_comment_or_cdata_is_not_a_point() -> None:
    doc = gpx(
        '<wpt lat="5" lon="5"><extensions>'
        + pt("trkpt", 5, 5)
        + "</extensions></wpt>"
        + "<!-- "
        + pt("trkpt", 6, 6)
        + " -->"
        + "<name><![CDATA["
        + pt("trkpt", 7, 7)
        + "]]></name>"
        + "<trk><trkseg>"
        + pt("trkpt", 1, 1, "<extensions>" + pt("trkpt", 8, 8) + "</extensions>")
        + pt("trkpt", 2, 2)
        + "<extensions>"
        + pt("trkpt", 9, 9)
        + "</extensions></trkseg><extensions>"
        + pt("trkpt", 4, 4)
        + "</extensions></trk>"
    )
    assert parse_gpx(doc).points == (RawPoint(1, 1, None), RawPoint(2, 2, None))


def test_a_trkpt_directly_under_trk_is_not_a_point() -> None:
    doc = gpx("<trk>" + "".join(TWO) + "</trk>")
    assert parse_gpx(doc).points == ()


def test_a_rtept_directly_under_gpx_is_not_a_point() -> None:
    assert parse_gpx(gpx("".join(RTE_TWO))).points == ()


def test_a_trkpt_nested_inside_a_trkpt_is_not_a_point() -> None:
    doc = gpx(trk(pt("trkpt", 1, 1, pt("trkpt", 9, 9)), pt("trkpt", 2, 2)))
    assert [p.lat for p in parse_gpx(doc).points] == [1, 2]


def test_waypoints_are_never_points() -> None:
    doc = gpx(pt("wpt", 1, 1) + pt("wpt", 2, 2))
    raw = parse_gpx(doc)
    assert raw.points == ()


def test_ele_inside_a_points_extensions_is_ignored() -> None:
    doc = gpx(
        trk(
            pt("trkpt", 1, 1, "<extensions><ele>99</ele></extensions>"),
            pt("trkpt", 2, 2, "<extensions><ele>99</ele></extensions><ele>7</ele>"),
        )
    )
    assert [p.elev_m for p in parse_gpx(doc).points] == [None, 7.0]


def test_an_ele_of_a_nested_element_is_not_the_points_ele() -> None:
    doc = gpx(trk(pt("trkpt", 1, 1, "<x><ele>99</ele></x>"), pt("trkpt", 2, 2)))
    assert parse_gpx(doc).points[0].elev_m is None


# --- source choice and validation ---


def test_rte_before_trk_in_the_document_still_chooses_trk() -> None:
    raw = parse_gpx(gpx(rte(*RTE_TWO) + trk(*TWO)))
    assert raw.source_format == "trk"
    assert raw.points == (RawPoint(1, 1, None), RawPoint(2, 2, None))


def test_rte_before_trk_is_not_chosen_even_with_more_rte_points() -> None:
    raw = parse_gpx(gpx(rte(*RTE_TWO, pt("rtept", 5, 5)) + trk(*TWO)))
    assert raw.source_format == "trk"


def test_trk_with_one_point_in_each_of_two_segments_counts_as_two() -> None:
    doc = gpx(
        "<trk><trkseg>"
        + pt("trkpt", 1, 1)
        + "</trkseg><trkseg>"
        + pt("trkpt", 2, 2)
        + "</trkseg></trk>"
        + rte(*RTE_TWO)
    )
    assert parse_gpx(doc).source_format == "trk"


def test_multiple_tracks_and_segments_merge_in_document_order() -> None:
    doc = gpx(
        trk(pt("trkpt", 1, 1), pt("trkpt", 2, 2))
        + "<trk><trkseg>"
        + pt("trkpt", 3, 3)
        + "</trkseg><trkseg>"
        + pt("trkpt", 4, 4)
        + "</trkseg></trk>"
    )
    assert [p.lat for p in parse_gpx(doc).points] == [1, 2, 3, 4]


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param('<rtept lat="95" lon="0"/>', id="lat-out-of-range"),
        pytest.param('<rtept lat="x" lon="0"/>', id="lat-unparseable"),
        pytest.param('<rtept lon="0"/>', id="lat-missing"),
        pytest.param('<rtept lat="0" lon="nan"/>', id="lon-nan"),
        pytest.param('<rtept lat="0" lon="200"/>', id="lon-out-of-range"),
        pytest.param("<rtept/>", id="no-attributes"),
    ],
)
def test_a_bad_coordinate_in_the_unchosen_source_is_accepted(bad: str) -> None:
    raw = parse_gpx(gpx(trk(*TWO) + "<rte>" + bad + pt("rtept", 1, 1) + "</rte>"))
    assert raw.source_format == "trk"
    assert len(raw.points) == 2


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param('<trkpt lat="91" lon="0"/>', id="lat-91"),
        pytest.param('<trkpt lat="-91" lon="0"/>', id="lat-minus-91"),
        pytest.param('<trkpt lat="0" lon="nan"/>', id="lon-nan"),
        pytest.param('<trkpt lat="inf" lon="0"/>', id="lat-inf"),
        pytest.param('<trkpt lon="0"/>', id="lat-missing"),
        pytest.param('<trkpt lat="0"/>', id="lon-missing"),
        pytest.param('<trkpt lat="" lon="0"/>', id="lat-empty"),
        pytest.param('<trkpt lat="0" lon="180.0001"/>', id="lon-just-over"),
    ],
)
def test_a_bad_coordinate_in_the_chosen_source_is_invalid_gpx(bad: str) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(gpx(trk(pt("trkpt", 1, 1), bad, pt("trkpt", 2, 2))))


def test_invalid_points_still_count_towards_choosing_the_source() -> None:
    """Counts include invalid points: trk holds 2 (one bad), so trk is chosen."""
    doc = gpx(trk(pt("trkpt", 1, 1), '<trkpt lat="x" lon="1"/>') + rte(*RTE_TWO))
    with pytest.raises(InvalidGpx):
        parse_gpx(doc)


def test_coordinates_may_carry_whitespace_and_exponents() -> None:
    doc = gpx(trk('<trkpt lat=" 1.5e0 " lon="\t2\n"/>', pt("trkpt", 2, 2)))
    assert parse_gpx(doc).points[0] == RawPoint(1.5, 2.0, None)


def test_the_boundary_coordinates_are_accepted() -> None:
    doc = gpx(trk('<trkpt lat="-90" lon="-180"/>', '<trkpt lat="90" lon="180"/>'))
    assert len(parse_gpx(doc).points) == 2


# --- names ---


def test_a_gpx_1_0_gpx_name_is_the_metadata_name() -> None:
    doc = gpx("<name>Old Style</name>" + trk(*TWO), ns=NS10)
    assert parse_gpx(doc).metadata_name == "Old Style"


def test_the_first_name_met_wins_between_gpx_name_and_metadata_name() -> None:
    doc = gpx("<name>One</name><metadata><name>Two</name></metadata>")
    assert parse_gpx(doc).metadata_name == "One"
    doc = gpx("<metadata><name>Two</name></metadata><name>One</name>")
    assert parse_gpx(doc).metadata_name == "Two"


def test_a_name_deeper_than_metadata_is_not_the_metadata_name() -> None:
    doc = gpx("<metadata><author><name>Not Me</name></author></metadata>")
    assert parse_gpx(doc).metadata_name is None


def test_a_wpt_name_is_not_a_route_name() -> None:
    doc = gpx('<wpt lat="1" lon="1"><name>Waypoint</name></wpt>' + trk(*TWO))
    raw = parse_gpx(doc)
    assert raw.metadata_name is None
    assert raw.track_name is None


def test_a_point_name_is_not_the_track_name() -> None:
    doc = gpx(trk(pt("trkpt", 1, 1, "<name>Point</name>"), pt("trkpt", 2, 2)))
    assert parse_gpx(doc).track_name is None


@pytest.mark.parametrize(
    ("name_xml", "expected"),
    [
        pytest.param("<![CDATA[Cafe <&> Trail]]>", "Cafe <&> Trail", id="cdata"),
        pytest.param("Fish &amp; Chips", "Fish & Chips", id="entity"),
        pytest.param("&#x5D0;&#1489;", "אב", id="character-references"),
        pytest.param("A<b>X</b>B", "AB", id="child-text-excluded"),
        pytest.param("Pre<![CDATA[Mid]]>Post", "PreMidPost", id="mixed-chunks"),
        pytest.param("  Two\n  Lines \n", "  Two\n  Lines \n", id="whitespace-raw"),
        pytest.param("מסלול", "מסלול", id="hebrew"),
    ],
)
def test_names_are_read_raw_with_cdata_and_entities_decoded(
    name_xml: str, expected: str
) -> None:
    doc = gpx(f"<metadata><name>{name_xml}</name></metadata>").decode()
    assert parse_gpx(doc.encode()).metadata_name == expected
    doc = gpx(trk(*TWO, name=f"<name>{name_xml}</name>")).decode()
    assert parse_gpx(doc.encode()).track_name == expected


def test_a_name_split_across_a_comment_is_joined() -> None:
    doc = gpx("<metadata><name>Ab<!-- c -->Cd</name></metadata>")
    assert parse_gpx(doc).metadata_name == "AbCd"


def test_the_track_name_is_the_first_non_blank_one() -> None:
    doc = gpx(
        trk(*TWO, name="<name>   </name>")
        + trk(pt("trkpt", 5, 5), name="<name>Second</name>")
        + trk(pt("trkpt", 6, 6), name="<name>Third</name>")
    )
    assert parse_gpx(doc).track_name == "Second"


def test_the_rte_name_is_used_for_an_rte_source_and_the_trk_name_is_not() -> None:
    doc = gpx(
        "<trk><name>OnlyOnePoint</name><trkseg>"
        + pt("trkpt", 1, 1)
        + "</trkseg></trk>"
        + rte(*RTE_TWO, name="<name>Route</name>")
    )
    raw = parse_gpx(doc)
    assert raw.source_format == "rte"
    assert raw.track_name == "Route"


def test_a_trk_name_is_not_used_when_rte_is_chosen_without_a_rte_name() -> None:
    doc = gpx(
        "<trk><name>OnlyOnePoint</name><trkseg>"
        + pt("trkpt", 1, 1)
        + "</trkseg></trk>"
        + rte(*RTE_TWO)
    )
    assert parse_gpx(doc).track_name is None


# --- <ele> ---


def ele_of(inner: str) -> float | None:
    doc = gpx(trk(pt("trkpt", 1, 1, inner), pt("trkpt", 2, 2)))
    return parse_gpx(doc).points[0].elev_m


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        pytest.param("<ele>  12.5\n </ele>", 12.5, id="whitespace-trimmed"),
        pytest.param("<ele><![CDATA[12]]></ele>", 12.0, id="cdata"),
        pytest.param("<ele>1<![CDATA[2]]></ele>", 12.0, id="text-then-cdata"),
        pytest.param("<ele>1e2</ele>", 100.0, id="exponent"),
        pytest.param("<ele>-3</ele>", -3.0, id="negative"),
        pytest.param("<ele>5</ele><ele>7</ele>", 5.0, id="first-wins"),
        pytest.param("<ele>x</ele><ele>7</ele>", None, id="first-garbage-wins"),
        pytest.param("<ele></ele>", None, id="empty"),
        pytest.param("<ele/>", None, id="self-closed"),
        pytest.param("<ele>   </ele>", None, id="blank"),
        pytest.param("<ele>high</ele>", None, id="garbage"),
        pytest.param("<ele>nan</ele>", None, id="nan"),
        pytest.param("<ele>1 2</ele>", None, id="two-numbers"),
        pytest.param("<ele>1<b>2</b></ele>", 1.0, id="child-text-excluded"),
        pytest.param("", None, id="absent"),
    ],
)
def test_ele_is_the_first_ele_directly_in_the_point(
    inner: str, expected: float | None
) -> None:
    assert ele_of(inner) == expected


def test_a_trkpt_ele_does_not_leak_into_the_next_point() -> None:
    doc = gpx(trk(pt("trkpt", 1, 1, "<ele>5</ele>"), pt("trkpt", 2, 2)))
    assert [p.elev_m for p in parse_gpx(doc).points] == [5.0, None]


def test_an_ele_on_a_waypoint_or_in_metadata_is_not_a_point_ele() -> None:
    doc = gpx(
        pt("wpt", 9, 9, "<ele>500</ele>")
        + "<metadata><ele>5</ele></metadata>"
        + trk(*TWO)
    )
    assert [p.elev_m for p in parse_gpx(doc).points] == [None, None]


# --- UTF-8, validated by expat (an invalid sequence anywhere is invalid_gpx) ---

HEAD = (
    b'<gpx><trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
)

BAD_UTF8 = [
    pytest.param(b"\xff", id="ff"),
    pytest.param(b"\xc0\xaf", id="overlong-slash"),
    pytest.param(b"\xe0\x80\xaf", id="overlong-3-byte"),
    pytest.param(b"\xed\xa0\x80", id="surrogate"),
    pytest.param(b"\xf4\x90\x80\x80", id="above-U+10FFFF"),
    pytest.param(b"\xf8\x88\x80\x80\x80", id="five-byte-form"),
    pytest.param(b"\x80", id="lone-continuation"),
    pytest.param(b"\xc3", id="truncated-two-byte"),
]

PLACES = {
    "in-a-name": lambda bad: HEAD + b"<name>a" + bad + b"b</name></gpx>",
    "in-a-comment": lambda bad: HEAD + b"<!-- a" + bad + b"b --></gpx>",
    "in-cdata": lambda bad: HEAD + b"<name><![CDATA[a" + bad + b"b]]></name></gpx>",
    "in-an-attribute": lambda bad: HEAD + b'<extensions x="a' + bad + b'b"/></gpx>',
    "after-the-root": lambda bad: HEAD + b"</gpx>" + bad,
    "in-an-element-name": lambda bad: HEAD + b"<a" + bad + b"/></gpx>",
    "in-a-pi": lambda bad: HEAD + b"<?p a" + bad + b"b?></gpx>",
}


@pytest.mark.parametrize("place", list(PLACES))
@pytest.mark.parametrize("bad", BAD_UTF8)
def test_invalid_utf8_anywhere_is_invalid_gpx(place: str, bad: bytes) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(PLACES[place](bad))


def test_a_sequence_truncated_at_the_end_of_the_file_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(HEAD + b"</gpx>\xe2\x82")


def test_valid_multibyte_utf8_is_accepted_everywhere() -> None:
    text = "א€\U0001f600"
    doc = (
        f"<gpx><!-- {text} --><metadata><name>{text}</name></metadata>"
        f'<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
        f'<extensions x="{text}"/></gpx>'
    )
    raw = parse_gpx(doc.encode())
    assert raw.metadata_name == text


def test_a_utf8_bom_is_skipped() -> None:
    assert len(parse_gpx(b"\xef\xbb\xbf" + gpx(trk(*TWO))).points) == 2


def test_a_nul_byte_is_invalid_gpx_even_inside_a_comment() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(HEAD + b"<!-- \x00 --></gpx>")


@pytest.mark.parametrize("codec", ["utf-16", "utf-16-le", "utf-16-be", "utf-32"])
def test_utf16_and_utf32_files_are_invalid_gpx(codec: str) -> None:
    text = '<?xml version="1.0"?>' + HEAD.decode() + "</gpx>"
    with pytest.raises(InvalidGpx):
        parse_gpx(text.encode(codec))


# --- no entity expansion, no DTD ---


@pytest.mark.parametrize(
    "prolog",
    [
        b'<!DOCTYPE gpx [<!ENTITY a "b">]>',
        b"<!DOCTYPE gpx>",
        b'<!DOCTYPE gpx SYSTEM "http://127.0.0.1:9/x.dtd">',
        b'<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///etc/passwd">]>',
        b'<!DOCTYPE gpx [<!ENTITY % p "x">]>',
    ],
)
def test_any_doctype_is_invalid_gpx(prolog: bytes) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(prolog + HEAD + b"</gpx>")


def test_an_undefined_entity_reference_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(HEAD + b"<name>&nope;</name></gpx>")


def test_a_non_gpx_root_is_invalid_even_when_it_contains_points() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(b'<kml><trk><trkseg><trkpt lat="1" lon="1"/></trkseg></trk></kml>')
