"""How our namespace rule differs from the retired gpxpy reader (ADR 0004 round-3
amendment, item 32; 3.1 "Namespaces"): one test per listed case.

Ours: an element is read iff its namespace, as expat resolves it, is the root's
namespace N and its path is in the reader's table. gpxpy deleted the first textual
``xmlns="..."`` and then matched children by local name.

Cases 1-3 are read by gpxpy and skipped by us; 4-6 are read by us and not by gpxpy.
These are *documentation tests*: the current reader already behaves this way, so they
pass today, and they pin the rule so a later change to it is an ADR amendment.
"""

import pytest

from app.routes.errors import TooFewPoints
from app.routes.parse import parse_gpx
from app.routes.summary import summarise_gpx

NS11 = "http://www.topografix.com/GPX/1/1"
POINTS = '<trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/>'
SEG = f"<trkseg>{POINTS}</trkseg>"
SEG_PREFIXED = (
    '<g:trkseg><g:trkpt lat="1" lon="1"/><g:trkpt lat="2" lon="2"/></g:trkseg>'
)


def points_read(doc: str) -> int:
    return len(parse_gpx(doc.encode()).points)


# --- gpxpy read these, we skip them ---

CASE_1 = f'<gpx><trk xmlns="{NS11}">{SEG}</trk></gpx>'
CASE_2 = f'<g:gpx xmlns:g="{NS11}"><trk>{SEG}</trk></g:gpx>'
CASE_3 = f'<gpx xmlns="{NS11}"><trk><trkseg xmlns="">{POINTS}</trkseg></trk></gpx>'


def test_case_1_a_no_namespace_root_with_a_default_namespace_child() -> None:
    assert points_read(CASE_1) == 0


def test_case_2_a_prefixed_root_with_unprefixed_namespace_free_children() -> None:
    assert points_read(CASE_2) == 0


def test_case_3_a_default_namespace_root_with_a_child_that_undeclares_it() -> None:
    assert points_read(CASE_3) == 0


@pytest.mark.parametrize("doc", [CASE_1, CASE_2, CASE_3], ids=["1", "2", "3"])
def test_a_whole_track_in_cases_1_to_3_is_too_few_points_through_the_pipeline(
    doc: str,
) -> None:
    with pytest.raises(TooFewPoints):
        summarise_gpx(doc.encode(), "f.gpx")


def test_cases_1_to_3_lose_only_the_affected_part_of_a_track() -> None:
    """A route's other, correctly namespaced segment is still read."""
    doc = (
        f'<gpx xmlns="{NS11}"><trk>'
        f'<trkseg xmlns=""><trkpt lat="9" lon="9"/><trkpt lat="8" lon="8"/></trkseg>'
        f"{SEG}</trk></gpx>"
    )
    assert [(p.lat, p.lon) for p in parse_gpx(doc.encode()).points] == [
        (1.0, 1.0),
        (2.0, 2.0),
    ]


# --- we read these, gpxpy did not ---


def test_case_4_a_default_root_with_a_child_that_redeclares_the_same_default() -> None:
    doc = f'<gpx xmlns="{NS11}"><trk xmlns="{NS11}">{SEG}</trk></gpx>'
    assert points_read(doc) == 2


def test_case_5_the_first_textual_xmlns_is_inside_a_comment_before_the_root() -> None:
    doc = f'<!-- xmlns="urn:decoy" --><gpx xmlns="{NS11}"><trk>{SEG}</trk></gpx>'
    assert points_read(doc) == 2


def test_case_5_the_first_textual_xmlns_is_inside_a_processing_instruction() -> None:
    doc = f'<?note xmlns="urn:decoy"?><gpx xmlns="{NS11}"><trk>{SEG}</trk></gpx>'
    assert points_read(doc) == 2


def test_case_5_the_first_textual_xmlns_is_in_an_attribute_value_before_the_root() -> (
    None
):
    doc = (
        f'<gpx creator=\'a xmlns="urn:decoy" b\' xmlns="{NS11}"><trk>{SEG}</trk></gpx>'
    )
    assert points_read(doc) == 2


def test_case_6_prefixed_elements_in_the_roots_namespace_under_a_default_root() -> None:
    doc = f'<gpx xmlns="{NS11}" xmlns:g="{NS11}"><g:trk>{SEG_PREFIXED}</g:trk></gpx>'
    assert points_read(doc) == 2


def test_case_6_prefixed_elements_under_a_prefixed_root() -> None:
    doc = f'<g:gpx xmlns:g="{NS11}"><g:trk>{SEG_PREFIXED}</g:trk></g:gpx>'
    assert points_read(doc) == 2


def test_case_6_mixed_prefixed_and_default_spellings_of_the_same_namespace() -> None:
    doc = (
        f'<gpx xmlns="{NS11}" xmlns:g="{NS11}">'
        f"<g:trk><trkseg>{POINTS}</trkseg></g:trk></gpx>"
    )
    assert points_read(doc) == 2
