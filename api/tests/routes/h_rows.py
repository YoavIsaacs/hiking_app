"""The ADR 0004 section 3.13 hostile rows (H1 to H12) as generators, and a runner.

QA's measurement harness. It is not collected by pytest (the name does not start with
``test_``) and imports only the standard library, ``app`` and ``hostile_shapes``, so it
runs inside the production image, which has no pytest:

    docker run --rm --memory=512m -v <api>/tests:/app/tests:ro \
        --entrypoint python hike-api:1.3 -m tests.routes.h_rows --repeat 3

Each run is a fresh interpreter (``run_python``) that parses one document with the
defaults and reports the outcome, the wall time, P (peak-RSS growth over the post-import
baseline, input bytes included) and the child's absolute RSS high-water mark.

``test_h11_repeated_names.py`` runs H11 and H12 under pytest with the same generators.
"""

import argparse
import json
import sys
from collections.abc import Callable
from functools import partial

from app.routes.params import MAX_UPLOAD_BYTES
from tests.routes.hostile_shapes import (
    MEASURED_PARSE_CHILD,
    burst,
    last_json_line,
    prefixed_attribute_burst,
    run_python,
    shortest_first_names,
    xmlns_binding_burst,
)

SIZE = MAX_UPLOAD_BYTES
VALID = '<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
FOUR_BYTE = "\U00010000"
TOO_COMPLEX = "The file is too complex to parse."

# The same child, but through the whole pure pipeline (parse, summarise): for H10.
MEASURED_SUMMARISE_CHILD = MEASURED_PARSE_CHILD.replace(
    "from app.routes.parse import parse_gpx",
    "from app.routes.summary import summarise_gpx",
).replace("parse_gpx(data).points", "summarise_gpx(data, None).points")
assert MEASURED_SUMMARISE_CHILD != MEASURED_PARSE_CHILD


def uri(n: int) -> str:
    """An ASCII URI of exactly ``n`` characters."""
    return "urn:" + "u" * (n - 4)


def fill(head: str, unit: str, tail: str, size: int = SIZE) -> bytes:
    """``head + unit * n + tail`` with the largest n that fits in ``size`` bytes."""
    fixed = len((head + tail).encode())
    return (head + unit * ((size - fixed) // len(unit.encode())) + tail).encode()


# --- H1 to H5: start tags, names, declarations ----------------------------------------


def h1() -> bytes:
    return ("<gpx" + burst(' %s=""', SIZE - 200) + ">" + VALID + "</gpx>").encode()


def h2(u: int) -> bytes:
    return prefixed_attribute_burst(SIZE, u)


def h3_shared(u: int) -> bytes:
    return xmlns_binding_burst(SIZE, u)


def h3_distinct(u: int) -> bytes:
    out: list[str] = []
    total = 0
    for name in shortest_first_names():
        piece = f' xmlns:{name}="{(name + "u" * u)[:u]}"'
        total += len(piece)
        if total > SIZE - 8:
            break
        out.append(piece)
    return ("<gpx" + "".join(out) + "/>").encode()


def h4(u: int, *, prefixed: bool) -> bytes:
    if prefixed:
        head = f'<gpx xmlns:p="{uri(u)}">'
        return (head + burst("<p:%s/>", SIZE - len(head) - 6) + "</gpx>").encode()
    return (
        "<gpx>" + burst("<%s/>", SIZE - 12 - len(VALID)) + VALID + "</gpx>"
    ).encode()


def h5_declarations(u: int, depth: int = 63) -> bytes:
    """63 nested levels, each start tag declaring distinct prefixes bound to U-long
    URIs, sized to 10 MiB (the bindings stay alive while their elements are open)."""
    budget = (SIZE - 200) // depth
    names = shortest_first_names()
    levels: list[str] = []
    for _ in range(depth):
        used = 0
        decls: list[str] = []
        for name in names:
            piece = f' xmlns:{name}="{uri(u)}"'
            if used + len(piece) > budget - 4:
                break
            used += len(piece)
            decls.append(piece)
        levels.append("<e" + "".join(decls) + ">")
    return ("<gpx>" + "".join(levels) + "</e>" * depth + VALID + "</gpx>").encode()


def h5_cycles(depth: int = 63) -> bytes:
    return fill("<gpx>", "<a>" * depth + "</a>" * depth, VALID + "</gpx>")


# --- H6 to H8: long text, skipped elements, large tokens ------------------------------

PTS = '<trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/>'
TEXT_FORMS: dict[str, Callable[[int], str]] = {
    "plain": lambda n: "x" * n,
    "cdata": lambda n: "<![CDATA[" + "x" * n + "]]>",
    "amp": lambda n: "&amp;" * (n // 5),
}
TEXT_PLACES: dict[str, Callable[[str], str]] = {
    "metadata/name": lambda t: (
        f"<gpx><metadata><name>{t}</name></metadata>{VALID}</gpx>"
    ),
    "trk/name": lambda t: (
        f"<gpx><trk><name>{t}</name><trkseg>{PTS}</trkseg></trk></gpx>"
    ),
    "rte/name": lambda t: (
        f'<gpx><rte><name>{t}</name><rtept lat="1" lon="1"/><rtept lat="2" lon="2"/>'
        "</rte></gpx>"
    ),
    "trkpt/ele": lambda t: (
        '<gpx><trk><trkseg><trkpt lat="1" lon="1">'
        f'<ele>{t}</ele></trkpt><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
    ),
    "skipped desc": lambda t: (
        f"<gpx><metadata><desc>{t}</desc></metadata>{VALID}</gpx>"
    ),
}


def h6(place: str, form: str) -> bytes:
    n = SIZE - 400
    return TEXT_PLACES[place](TEXT_FORMS[form](n)).encode()


FLOODS = {
    "<trk/>": "<trk/>",
    "<wpt/>": '<wpt lat="0" lon="0"/>',
    "<trkseg/>": "<trkseg/>",
    "<a/>": "<a/>",
}


def h7_flood(unit: str) -> bytes:
    return fill("<gpx>", unit, "</gpx>")


def h7_extensions() -> bytes:
    head = '<gpx><trk><trkseg><trkpt lat="1" lon="1"><extensions>'
    tail = '</extensions></trkpt><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
    return (head + burst("<%s/>", SIZE - len(head) - len(tail)) + tail).encode()


def h8_gpx() -> bytes:
    return fill('<gpx creator="', "x", f'">{VALID}</gpx>')


def h8_trkpt() -> bytes:
    head = '<gpx><trk><trkseg><trkpt lat="1" lon="1" x="'
    tail = '"/><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
    return fill(head, "x", tail)


# --- H9 and H10 -----------------------------------------------------------------------


def h9(u: int = 256) -> bytes:
    """100,001 points, then H4 (prefixed) at U, trimmed to 10 MiB in all."""
    head = f'<gpx xmlns:p="{uri(u)}"><trk><trkseg>'
    points = '<trkpt lat="1" lon="1"/>' * 100_001 + "</trkseg></trk>"
    room = SIZE - len(head) - len(points) - 6
    return (head + points + burst("<p:%s/>", room) + "</gpx>").encode()


def h10() -> bytes:
    """100,000 points that zigzag, each with an elevation (the adversarial simplify)."""
    pts = []
    for i in range(100_000):
        lat = 31.0 + i * 1e-5
        lon = 34.0 + (5e-4 if i % 2 else -5e-4)
        pts.append(
            f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>{100 + i % 7}</ele></trkpt>'
        )
    return ("<gpx><trk><trkseg>" + "".join(pts) + "</trkseg></trk></gpx>").encode()


# --- H11 and H12 ----------------------------------------------------------------------


def h11(shape: str, u_chars: int = 256) -> bytes:
    """One name repeated to fill 10 MiB, at a URI of ``u_chars`` ASCII characters."""
    u = uri(u_chars)
    tail = VALID + "</gpx>"
    if shape == "a":  # default namespace
        return fill(f'<gpx xmlns="{u}">', "<a/>", tail)
    if shape == "b":  # prefixed elements
        return fill(f'<gpx xmlns:p="{u}">', "<p:a/>", tail)
    if shape == "c":  # prefixed attributes on skipped elements
        unit = "<a " + " ".join(f'p:{c}=""' for c in "abcdefgh") + "/>"
        return fill(f'<gpx xmlns:p="{u}">', unit, tail)
    if shape == "d":  # a non-ASCII local name under the default namespace
        return fill(f'<gpx xmlns="{u}">', "<Ā/>", tail)
    if shape == "control":  # H7's <a/> flood with no namespace
        return fill("<gpx>", "<a/>", tail)
    raise KeyError(shape)


def h12(shape: str, declared: str) -> bytes:
    """The H11 shapes over the cap: ``declared`` is the URI text."""
    tail = VALID + "</gpx>"
    if shape == "a":
        return fill(f'<gpx xmlns="{declared}">', "<a/>", tail)
    if shape == "b":
        return fill(f'<gpx xmlns:p="{declared}">', "<p:a/>", tail)
    unit = "<a " + " ".join(f'p:{c}=""' for c in "abcdefgh") + "/>"
    return fill(f'<gpx xmlns:p="{declared}">', unit, tail)


def round4_file() -> bytes:
    return fill(f'<gpx xmlns="{FOUR_BYTE * 1024}">', "<a/>", VALID + "</gpx>")


# --- the table and the runner ---------------------------------------------------------


def rows() -> dict[str, tuple[Callable[[], bytes], str]]:
    """name -> (generator, child code). The generators run lazily, one at a time."""
    table: dict[str, tuple[Callable[[], bytes], str]] = {}
    p = MEASURED_PARSE_CHILD
    table["H1"] = (h1, p)
    for u in (1, 256, 257):
        table[f"H2 U={u}"] = (partial(h2, u), p)
        table[f"H3 shared U={u}"] = (partial(h3_shared, u), p)
        table[f"H4 prefixed U={u}"] = (partial(h4, u, prefixed=True), p)
    table["H3 distinct U=256"] = (partial(h3_distinct, 256), p)
    table["H3 distinct U=257"] = (partial(h3_distinct, 257), p)
    table["H4 unprefixed"] = (partial(h4, 0, prefixed=False), p)
    table["H5 nested declarations U=256"] = (partial(h5_declarations, 256), p)
    table["H5 nested declarations U=5"] = (partial(h5_declarations, 5), p)
    table["H5 63-deep cycles"] = (h5_cycles, p)
    for place in TEXT_PLACES:
        for form in TEXT_FORMS:
            table[f"H6 {place} {form}"] = (partial(h6, place, form), p)
    for name, unit in FLOODS.items():
        table[f"H7 {name}"] = (partial(h7_flood, unit), p)
    table["H7 extensions"] = (h7_extensions, p)
    table["H8 gpx attribute"] = (h8_gpx, p)
    table["H8 trkpt attribute"] = (h8_trkpt, p)
    table["H9 U=256"] = (h9, p)
    table["H10 zigzag (summarise)"] = (h10, MEASURED_SUMMARISE_CHILD)
    for shape in ("control", "a", "b", "c", "d"):
        table[f"H11({shape})"] = (partial(h11, shape), p)
    for shape in ("a", "b", "c"):
        table[f"H12({shape}) U=257"] = (partial(h12, shape, uri(257)), p)
        table[f"H12({shape}) U+10000"] = (partial(h12, shape, FOUR_BYTE), p)
    table["H12 round-4 file"] = (round4_file, p)
    return table


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("select", nargs="*", help="row-name prefixes, e.g. H11 H3")
    args = parser.parse_args(argv)
    for name, (make, child) in rows().items():
        if args.select and not any(name.startswith(s) for s in args.select):
            continue
        data = make()
        for run in range(args.repeat):
            out = last_json_line(run_python(child, data, timeout_s=300))
            print(
                json.dumps(
                    {"row": name, "run": run + 1, "mib": round(len(data) / 2**20, 2)}
                    | {
                        k: (round(v, 3) if isinstance(v, float) else v)
                        for k, v in out.items()
                    }
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
