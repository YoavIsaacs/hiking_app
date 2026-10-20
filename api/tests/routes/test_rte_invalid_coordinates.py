"""An invalid coordinate in the chosen rte is invalid_gpx (ADR 0004 3.1 step 8).

Found in verify: the branch that records the first bad ``<rtept>`` was never run.
"""

import pytest
from fastapi.testclient import TestClient

from app.routes.errors import InvalidGpx
from app.routes.parse import parse_gpx
from tests.routes.http_helpers import URL, assert_error

GOOD_TRK = (
    '<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
)
BAD_VALUES = ["x", "", "NaN", "inf", "91", "-91"]


def rte(*points: str) -> bytes:
    return f"<gpx><rte>{''.join(points)}</rte></gpx>".encode()


def rtept(lat: str, lon: str = "2") -> str:
    return f'<rtept lat="{lat}" lon="{lon}"/>'


@pytest.mark.parametrize("bad", BAD_VALUES)
def test_a_bad_latitude_in_the_chosen_rte_is_invalid_gpx(bad: str) -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(rte(rtept("1", "1"), rtept(bad), rtept("3", "3")))


def test_a_bad_longitude_in_the_chosen_rte_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(rte(rtept("1", "1"), rtept("2", "181")))


def test_only_the_first_bad_rtept_is_needed_for_the_error() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(rte(rtept("x"), rtept("y"), rtept("3", "3")))


def test_a_bad_rte_is_ignored_when_the_trk_is_chosen() -> None:
    doc = f"<gpx>{GOOD_TRK}<rte>{rtept('x')}{rtept('2')}</rte></gpx>".encode()
    track = parse_gpx(doc)
    assert track.source_format == "trk"
    assert len(track.points) == 2


def test_a_bad_rtept_is_422_invalid_gpx_over_http(client: TestClient) -> None:
    response = client.post(
        URL,
        files={
            "file": (
                "r.gpx",
                rte(rtept("1", "1"), rtept("x")),
                "application/gpx+xml",
            )
        },
    )
    assert_error(response, 422, "invalid_gpx")
