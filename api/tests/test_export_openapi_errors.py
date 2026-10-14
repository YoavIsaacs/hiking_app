"""Unit tests for export_openapi failure modes (tech-lead rulings on ADR 0001)."""

from pathlib import Path

import pytest
from fastapi import FastAPI

from app import export_openapi
from app.operation_ids import OperationIdError


def test_missing_parent_directory_raises_and_is_not_created(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "openapi.json"
    with pytest.raises(OSError):
        export_openapi.main([str(target)])
    assert not target.parent.exists()


def test_extra_positional_argument_exits_with_code_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        export_openapi.main([str(tmp_path / "a.json"), str(tmp_path / "b.json")])
    assert exc.value.code == 2


def test_unknown_option_exits_with_code_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        export_openapi.main(["--bogus"])
    assert exc.value.code == 2


def test_operation_id_error_from_create_app_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_create_app(*_args: object, **_kwargs: object) -> FastAPI:
        raise OperationIdError("boom")

    monkeypatch.setattr(export_openapi, "create_app", broken_create_app)
    target = tmp_path / "openapi.json"
    with pytest.raises(OperationIdError):
        export_openapi.main([str(target)])
    assert not target.exists()
