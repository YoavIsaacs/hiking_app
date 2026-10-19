"""Independent reading of the (trusted, DTD-free) corpus files: a test oracle."""

import xml.etree.ElementTree as ET
from pathlib import Path

from tests.routes.gpx_builders import Pt

PRIMARY = ("trkpt", "rtept")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_points(path: Path) -> list[Pt]:
    """Every trkpt/rtept of the file in document order, as the file has them."""
    root = ET.fromstring(path.read_bytes())
    points: list[Pt] = []
    for el in root.iter():
        if _local(el.tag) in PRIMARY:
            ele: float | None = None
            for child in el:
                if _local(child.tag) == "ele" and child.text:
                    ele = float(child.text)
            points.append(Pt(float(el.attrib["lat"]), float(el.attrib["lon"]), ele))
    return points


def metadata_name(path: Path) -> str | None:
    root = ET.fromstring(path.read_bytes())
    for el in root.iter():
        if _local(el.tag) == "metadata":
            for child in el:
                if _local(child.tag) == "name":
                    return (child.text or "").strip() or None
    return None
