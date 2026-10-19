"""Hostile XML and the removal of gpxpy (ADR 0004 amendment 3: items 13-17, sections
3.11 and 3.13).

* depth cap 64 -> ``invalid_gpx`` (the root is depth 1);
* inputs that used to kill or stall the process run in a **subprocess**, so a crash or a
  hang fails the test instead of taking pytest down;
* no process-global state: ``xml.etree.ElementTree._namespace_map`` is untouched;
* gpxpy is not importable and not imported by the app;
* memory kept does not grow with skipped elements.
"""

import ast
import importlib.util
import json
import subprocess
import sys
import textwrap
import tracemalloc
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import pytest

from app.routes.errors import InvalidGpx
from app.routes.params import MAX_XML_DEPTH
from app.routes.parse import parse_gpx

API_DIR = Path(__file__).resolve().parents[2]
APP_DIR = API_DIR / "app"
MIB = 1024 * 1024

TWO_POINTS = (
    b'<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
)


def run_child(
    code: str, data: bytes = b"", *, timeout_s: float = 90.0
) -> subprocess.CompletedProcess[bytes]:
    """Runs ``code`` in a fresh interpreter with ``api/`` importable. ``data`` arrives
    on stdin (the child reads it with ``sys.stdin.buffer.read()``) and the child prints
    one JSON line. A hang fails the test; a crash shows up as a non-zero exit code."""
    prelude = f"import sys\nsys.path.insert(0, {str(API_DIR)!r})\n"
    try:
        return subprocess.run(
            [sys.executable, "-I", "-c", prelude + textwrap.dedent(code)],
            input=data,
            capture_output=True,
            timeout=timeout_s,
            cwd=API_DIR,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"the child process did not finish within {timeout_s} s")


def child_json(result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    stderr = result.stderr.decode(errors="replace")[-600:]
    assert result.returncode == 0, (
        f"the child process died (exit {result.returncode}): {stderr}"
    )
    loaded = json.loads(result.stdout.decode().strip().splitlines()[-1])
    assert isinstance(loaded, dict)
    return loaded


PARSE_CHILD = """
    import json, time
    from app.routes.errors import InvalidGpx
    from app.routes.parse import parse_gpx
    data = sys.stdin.buffer.read()
    started = time.perf_counter()
    try:
        outcome = f"{len(parse_gpx(data).points)} points"
    except InvalidGpx:
        outcome = "invalid_gpx"
    print(json.dumps({"outcome": outcome, "seconds": time.perf_counter() - started}))
"""


# --- depth ---


def nested(levels: int, tag: str = "a") -> bytes:
    """A document whose deepest element is at depth ``levels`` (the root is depth 1)."""
    inner = levels - 1
    return (
        b"<gpx>"
        + f"<{tag}>".encode() * inner
        + f"</{tag}>".encode() * inner
        + b"</gpx>"
    )


def test_the_depth_cap_is_64() -> None:
    assert MAX_XML_DEPTH == 64


def test_a_document_whose_deepest_element_is_at_depth_64_parses() -> None:
    assert parse_gpx(nested(64)).points == ()


def test_a_document_whose_deepest_element_is_at_depth_65_is_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(nested(65))


def test_a_depth_65_message_says_nothing_about_the_content() -> None:
    with pytest.raises(InvalidGpx) as excinfo:
        parse_gpx(nested(65, tag="SECRET-TAG-5521"))
    assert "SECRET-TAG-5521" not in excinfo.value.message


def extensions_depth(levels: int) -> bytes:
    """gpx(1)/trk(2)/trkseg(3)/trkpt(4), then nested <extensions> down to ``levels``."""
    extra = levels - 4
    return (
        b'<gpx><trk><trkseg><trkpt lat="1" lon="1">'
        + b"<extensions>" * extra
        + b"</extensions>" * extra
        + b'</trkpt><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
    )


def test_extensions_nested_to_depth_64_inside_a_trkpt_parse() -> None:
    assert len(parse_gpx(extensions_depth(64)).points) == 2


def test_extensions_nested_to_depth_65_inside_a_trkpt_are_invalid_gpx() -> None:
    with pytest.raises(InvalidGpx):
        parse_gpx(extensions_depth(65))


@pytest.mark.parametrize(
    ("root", "open_tag", "close_tag"),
    [
        pytest.param(b"<gpx>", b"<wpt>", b"</wpt>", id="wpt"),
        pytest.param(b"<gpx>", b"<metadata>", b"</metadata>", id="metadata"),
        pytest.param(
            b'<gpx xmlns:f="urn:f">', b"<f:x>", b"</f:x>", id="foreign-namespace"
        ),
    ],
)
def test_depth_65_is_invalid_inside_any_skipped_subtree(
    root: bytes, open_tag: bytes, close_tag: bytes
) -> None:
    """The subtree's own root is at depth 2, so 62 nested <a> reach depth 64."""
    at_64 = b"<a>" * 62 + b"</a>" * 62
    at_65 = b"<a>" * 63 + b"</a>" * 63
    ok = root + open_tag + at_64 + close_tag + TWO_POINTS + b"</gpx>"
    assert len(parse_gpx(ok).points) == 2
    with pytest.raises(InvalidGpx):
        parse_gpx(root + open_tag + at_65 + close_tag + TWO_POINTS + b"</gpx>")


def test_depth_is_per_open_element_not_cumulative() -> None:
    siblings = (b"<a>" * 62 + b"</a>" * 62) * 20  # 20 deep subtrees one after another
    assert len(parse_gpx(b"<gpx>" + siblings + TWO_POINTS + b"</gpx>").points) == 2


def test_points_after_a_deep_skipped_subtree_are_still_read() -> None:
    wpt = b"<wpt lat='1' lon='1'>" + b"<a>" * 50 + b"</a>" * 50 + b"</wpt>"
    assert len(parse_gpx(b"<gpx>" + wpt + TWO_POINTS + b"</gpx>").points) == 2


def test_a_third_of_a_megabyte_of_open_tags_is_invalid_gpx_in_a_child_process() -> None:
    out = child_json(run_child(PARSE_CHILD, b"<gpx>" + b"<a>" * (350 * 1024)))
    assert out["outcome"] == "invalid_gpx"


# The round-2 file: about 140 KB of nested <extensions> inside a trkpt, which killed the
# process (gpxpy's copy.deepcopy recursion).
ROUND_2_LEVELS = (
    5_700  # 5,700 * (len("<extensions>") + len("</extensions>")) = 142,500 B
)
ROUND_2_FILE = (
    b'<gpx><trk><trkseg><trkpt lat="1" lon="1">'
    + b"<extensions>" * ROUND_2_LEVELS
    + b"</extensions>" * ROUND_2_LEVELS
    + b'</trkpt><trkpt lat="2" lon="2"/></trkseg></trk></gpx>'
)


def test_the_round_2_nested_extensions_file_is_invalid_gpx_in_a_child_process() -> None:
    assert len(ROUND_2_FILE) >= 140_000
    out = child_json(run_child(PARSE_CHILD, ROUND_2_FILE))
    assert out["outcome"] == "invalid_gpx"
    assert isinstance(out["seconds"], float) and out["seconds"] < 2.0


def test_the_round_2_file_is_422_over_http_and_the_process_lives() -> None:
    result = run_child(
        """
        import json
        from fastapi.testclient import TestClient
        from app.config import Settings
        from app.main import create_app
        settings = Settings(_env_file=None, env="test", log_level="INFO",
                            cors_origins=["http://a.test"], version="9.9.9-test",
                            git_sha="abc1234test",
                            open_meteo_base_url="http://open-meteo.test")
        client = TestClient(create_app(settings), raise_server_exceptions=False)
        data = sys.stdin.buffer.read()
        first = client.post("/v1/routes/parse",
                            files={"file": ("deep.gpx", data, "application/gpx+xml")})
        health = client.get("/health")  # the app still answers afterwards
        print(json.dumps({"status": first.status_code, "code": first.json().get("code"),
                          "health": health.status_code}))
        """,
        ROUND_2_FILE,
    )
    assert child_json(result) == {"status": 422, "code": "invalid_gpx", "health": 200}


# --- no process-global state ---


def namespace_map() -> dict[str, str]:
    return dict(ET._namespace_map)  # type: ignore[attr-defined]  # private map, ADR 3.11


@pytest.mark.parametrize("prefix", ["qaone", "qatwo", "qathree"])
def test_parsing_xmlns_declarations_leaves_the_etree_namespace_map_unchanged(
    prefix: str,
) -> None:
    uri = f"urn:qa:namespace-map:{prefix}"
    doc = (
        f'<gpx xmlns="http://www.topografix.com/GPX/1/1" xmlns:{prefix}="{uri}">'
        f"<trk><trkseg><trkpt lat='1' lon='1'><extensions><{prefix}:x/></extensions>"
        "</trkpt><trkpt lat='2' lon='2'/></trkseg></trk></gpx>"
    ).encode()
    before = namespace_map()
    assert len(parse_gpx(doc).points) == 2
    assert namespace_map() == before
    assert uri not in namespace_map()


def test_a_failed_parse_leaves_the_etree_namespace_map_unchanged_too() -> None:
    before = namespace_map()
    with pytest.raises(InvalidGpx):
        parse_gpx(b'<gpx xmlns:qafour="urn:qa:namespace-map:qafour"><<')
    assert namespace_map() == before


# --- gpxpy is gone ---


def test_gpxpy_is_not_importable() -> None:
    assert importlib.util.find_spec("gpxpy") is None


def _imports(path: Path) -> list[tuple[str, int]]:
    """(module name, relative level) of every import in ``path``."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_parse_py_imports_only_the_stdlib_and_app() -> None:
    stdlib = set(sys.stdlib_module_names)
    for module, level in _imports(APP_DIR / "routes" / "parse.py"):
        assert level == 0, "relative imports are not used in this codebase"
        top = module.split(".")[0]
        assert top in stdlib or top == "app", f"parse.py imports {module}"


def test_parse_py_reads_xml_with_the_stdlib_expat() -> None:
    modules = {m for m, _ in _imports(APP_DIR / "routes" / "parse.py")}
    assert any(m.startswith("xml.parsers.expat") or m == "pyexpat" for m in modules)


def test_nothing_in_app_imports_gpxpy_or_the_retired_xml_guard() -> None:
    offenders = [
        f"{path.relative_to(APP_DIR)}: {module}"
        for path in APP_DIR.rglob("*.py")
        for module, _ in _imports(path)
        if module.split(".")[0] == "gpxpy" or module.endswith("xml_guard")
    ]
    assert offenders == []


def test_the_xml_guard_module_is_deleted() -> None:
    assert not (APP_DIR / "routes" / "xml_guard.py").exists()
    assert importlib.util.find_spec("app.routes.xml_guard") is None


def test_the_project_no_longer_declares_gpxpy() -> None:
    assert "gpxpy" not in (API_DIR / "pyproject.toml").read_text(encoding="utf-8")


def test_nothing_in_the_tests_imports_gpxpy_or_the_retired_xml_guard() -> None:
    offenders = [
        f"{path.relative_to(API_DIR)}: {module}"
        for path in (API_DIR / "tests").rglob("*.py")
        for module, _ in _imports(path)
        if module.split(".")[0] == "gpxpy" or module.endswith("xml_guard")
    ]
    assert offenders == []


# --- xmlns shapes that made gpxpy quadratic (review round 2), in a child process ---

TRK_2 = b'<trk><trkseg><trkpt lat="1" lon="1"/><trkpt lat="2" lon="2"/></trkseg></trk>'
END = TRK_2 + b"</gpx>"

XMLNS_SHAPES = {
    # ~200 KB of " xmlns" with no "=" after the last "=" of the document, in a comment
    # after the root: gpxpy's \sxmlns:?[^=]*=... regex rescanned to the end each time
    # (6.5 s)
    "repeated-xmlns-in-a-comment": (
        b"<gpx>" + TRK_2 + b"</gpx><!-- " + b" xmlns" * 33_000 + b" -->"
    ),
    "repeated-xmlns-in-a-comment-before-the-points": (
        b"<gpx><!-- " + b" xmlns" * 33_000 + b" -->" + END
    ),
    "repeated-xmlns-equals-in-a-comment": (
        b"<gpx><!-- " + b' xmlns="u"' * 25_000 + b" -->" + END
    ),
    # one element declaring 20k distinct prefixes
    "many-distinct-xmlns-prefixes": (
        b"<gpx"
        + b"".join(b' xmlns:p%d="urn:u%d"' % (i, i) for i in range(20_000))
        + b">"
        + END
    ),
    # ~1 MiB of siblings, each re-declaring the default namespace
    "siblings-redeclaring-the-default-namespace": (
        b"<gpx>" + b'<a xmlns="urn:x"/>' * 58_000 + END
    ),
}


@pytest.mark.parametrize("shape", list(XMLNS_SHAPES))
def test_xmlns_shapes_parse_in_linear_time(shape: str) -> None:
    out = child_json(run_child(PARSE_CHILD, XMLNS_SHAPES[shape], timeout_s=60))
    assert out["outcome"] == "2 points"
    assert isinstance(out["seconds"], float) and out["seconds"] < 3.0, out


# --- memory kept does not grow with skipped elements ---

SKIPPED: dict[str, tuple[bytes, bytes, bytes]] = {
    "trk": (b"<gpx>", b"<trk/>", b"</gpx>"),
    "wpt": (b"<gpx>", b'<wpt lat="0" lon="0"/>', b"</gpx>"),
    "trkseg": (b"<gpx><trk>", b"<trkseg/>", b"</trk></gpx>"),
    "a": (b"<gpx><trk>", b"<a/>", b"</trk></gpx>"),
}


def traced_peak(parse: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        parse()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def skipped_doc(shape: str, size: int) -> bytes:
    head, unit, tail = SKIPPED[shape]
    return head + unit * (size // len(unit)) + tail


@pytest.mark.parametrize("shape", list(SKIPPED))
def test_retention_does_not_grow_with_skipped_elements(shape: str) -> None:
    parse_gpx(skipped_doc(shape, 1024))  # warm up imports and caches
    small = skipped_doc(shape, 1 * MIB)
    large = skipped_doc(shape, 4 * MIB)
    peak_small = traced_peak(lambda: parse_gpx(small))
    peak_large = traced_peak(lambda: parse_gpx(large))
    assert peak_large - peak_small <= 1 * MIB, (peak_small, peak_large)
