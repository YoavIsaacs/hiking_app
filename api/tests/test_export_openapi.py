"""ADR 0001 decision 2: openapi.json is exported without a server, deterministically."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from app import export_openapi
from app.export_openapi import SCHEMA_VERSION, build_schema, main, render_schema


def _export(path: Path) -> bytes:
    assert main([str(path)]) == 0
    return path.read_bytes()


def test_main_returns_zero_and_writes_valid_openapi_3_json(tmp_path: Path) -> None:
    data = json.loads(_export(tmp_path / "openapi.json").decode("utf-8"))
    assert data["openapi"].startswith("3.")


def test_exported_schema_info_version_is_the_pinned_contract_version(
    tmp_path: Path,
) -> None:
    data = json.loads(_export(tmp_path / "openapi.json"))
    assert data["info"]["version"] == SCHEMA_VERSION == "0.0.0-contract"


def test_exported_file_ends_with_exactly_one_newline(tmp_path: Path) -> None:
    raw = _export(tmp_path / "openapi.json")
    assert raw.endswith(b"}\n")
    assert not raw.endswith(b"\n\n")


def test_exported_file_has_no_carriage_returns(tmp_path: Path) -> None:
    assert b"\r" not in _export(tmp_path / "openapi.json")


def test_exported_file_matches_sorted_indented_json_format(tmp_path: Path) -> None:
    raw = _export(tmp_path / "openapi.json")
    schema = json.loads(raw)
    expected = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert raw.decode("utf-8") == expected


def test_render_schema_sorts_keys_and_keeps_non_ascii_with_one_trailing_newline() -> (
    None
):
    text = render_schema({"b": 1, "a": {"d": 1, "c": "é"}})
    assert text == '{\n  "a": {\n    "c": "é",\n    "d": 1\n  },\n  "b": 1\n}\n'


def test_render_schema_is_stable_regardless_of_input_key_order() -> None:
    assert render_schema({"a": 1, "b": 2}) == render_schema({"b": 2, "a": 1})


def test_build_schema_is_deterministic_across_calls() -> None:
    assert render_schema(build_schema()) == render_schema(build_schema())


def test_two_exports_are_byte_identical(tmp_path: Path) -> None:
    assert _export(tmp_path / "a.json") == _export(tmp_path / "b.json")


def test_export_is_unaffected_by_version_git_sha_and_env_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _export(tmp_path / "base.json")
    for name, value in (
        ("VERSION", "123.456.789"),
        ("GIT_SHA", "deadbeef"),
        ("ENV", "production"),
    ):
        monkeypatch.setenv(name, value)
        monkeypatch.setenv(f"HIKE_{name}", value)
    monkeypatch.setenv("HIKE_CORS_ORIGINS", '["https://odd.test"]')
    monkeypatch.setenv("HIKE_CORS_FIREBASE_SITE", "hike-prep-abc")
    monkeypatch.setenv("HIKE_OPEN_METEO_BASE_URL", "http://odd.test")
    assert _export(tmp_path / "changed.json") == baseline


def test_export_ignores_a_stray_dotenv_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = _export(tmp_path / "base.json")
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".env").write_text(
        "VERSION=9.9.9\nGIT_SHA=feedface\nENV=prod\n"
        "HIKE_VERSION=8.8.8\nHIKE_GIT_SHA=cafe\nHIKE_ENV=prod\n"
        'HIKE_CORS_FIREBASE_SITE=hike-prep-abc\nHIKE_CORS_ORIGINS=["https://odd.test"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(workdir)
    assert _export(tmp_path / "changed.json") == baseline


def test_main_with_none_argv_writes_to_default_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "default.json"
    monkeypatch.setattr(export_openapi, "DEFAULT_OUTPUT", target)
    monkeypatch.setattr(sys, "argv", ["export_openapi"])
    assert main(None) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["openapi"].startswith("3.")


def test_main_with_empty_argv_writes_to_default_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "default.json"
    monkeypatch.setattr(export_openapi, "DEFAULT_OUTPUT", target)
    assert main([]) == 0
    assert target.is_file()


def test_exported_schema_contains_the_get_health_operation(tmp_path: Path) -> None:
    data = json.loads(_export(tmp_path / "openapi.json"))
    assert data["paths"]["/health"]["get"]["operationId"] == "getHealth"


def test_module_entry_point_exits_zero_and_writes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "via-main.json"
    monkeypatch.setattr(sys, "argv", ["export_openapi", str(out)])
    # runpy warns if the module is already imported; drop it so the run is clean.
    monkeypatch.delitem(sys.modules, "app.export_openapi", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("app.export_openapi", run_name="__main__")
    assert exc.value.code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["openapi"].startswith("3.")
