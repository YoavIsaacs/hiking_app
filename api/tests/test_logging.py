import json
import logging
import sys
from collections.abc import Callable, Iterator

import pytest

from app.logging_config import (
    LOGGED_MARK,
    JsonFormatter,
    configure_logging,
    request_id_var,
)


def _record(
    msg: str = "hello %s", args: tuple[str, ...] = ("world",), **extra: object
) -> logging.LogRecord:
    record = logging.LogRecord(
        "test.logger", logging.WARNING, __file__, 1, msg, args, None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_formatter_emits_single_json_line_with_request_id() -> None:
    token = request_id_var.set("rid-42")
    try:
        line = JsonFormatter().format(_record())
    finally:
        request_id_var.reset(token)
    data = json.loads(line)
    assert "\n" not in line
    assert data["request_id"] == "rid-42"
    assert data["message"] == "hello world"
    assert data["level"] == "WARNING"
    assert data["logger"] == "test.logger"
    assert "timestamp" in data


def test_formatter_defaults_request_id_outside_request() -> None:
    assert json.loads(JsonFormatter().format(_record()))["request_id"] == "-"


def test_formatter_includes_extra_fields() -> None:
    data = json.loads(JsonFormatter().format(_record(status=200)))
    assert data["status"] == 200


def test_formatter_records_exception_type_and_traceback() -> None:
    try:
        raise ValueError("secret detail")
    except ValueError:
        record = _record()
        record.exc_info = sys.exc_info()
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert data["exc_type"] == "ValueError"
    assert "Traceback" in data["exc_info"]
    assert "ValueError: secret detail" in data["exc_info"]
    assert "\n" not in line


def test_configure_logging_is_idempotent_and_sets_level() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    uv_saved = {
        n: list(logging.getLogger(n).handlers) for n in ("uvicorn", "uvicorn.error")
    }
    try:
        configure_logging("DEBUG")
        configure_logging("WARNING")
        ours = [h for h in root.handlers if isinstance(h.formatter, JsonFormatter)]
        assert len(ours) == 1
        assert root.level == logging.WARNING
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        root.handlers[:] = before
        root.setLevel(level)
        for n, handlers in uv_saved.items():
            logging.getLogger(n).handlers[:] = handlers
        logging.getLogger("uvicorn.access").disabled = False


def test_output_is_json_on_stream(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO")
        logging.getLogger("x").info("ping")
        err = capsys.readouterr().err.strip().splitlines()[-1]
        assert json.loads(err)["message"] == "ping"
    finally:
        root.handlers[:] = before


@pytest.fixture
def install_logging() -> Iterator[Callable[[], logging.Logger]]:
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {
        n: (
            list(logging.getLogger(n).handlers),
            list(logging.getLogger(n).filters),
            logging.getLogger(n).propagate,
            logging.getLogger(n).disabled,
        )
        for n in names
    }

    def install() -> logging.Logger:
        # Called from the test body so the handler binds to capsys's stderr.
        configure_logging("INFO")
        return logging.getLogger("uvicorn.error")

    try:
        yield install
    finally:
        root.handlers[:] = before
        root.setLevel(level)
        for n, (handlers, filters, propagate, disabled) in saved.items():
            lg = logging.getLogger(n)
            lg.handlers[:] = handlers
            lg.filters[:] = filters
            lg.propagate = propagate
            lg.disabled = disabled


def test_uvicorn_filter_drops_already_logged_exception(
    capsys: pytest.CaptureFixture[str], install_logging: Callable[[], logging.Logger]
) -> None:
    uvicorn_logger = install_logging()
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        setattr(exc, LOGGED_MARK, True)
        uvicorn_logger.error("Exception in ASGI application", exc_info=True)
    assert capsys.readouterr().err == ""


def test_uvicorn_filter_emits_unmarked_exception(
    capsys: pytest.CaptureFixture[str], install_logging: Callable[[], logging.Logger]
) -> None:
    uvicorn_logger = install_logging()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        uvicorn_logger.error("Exception in ASGI application", exc_info=True)
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["logger"] == "uvicorn.error"
    assert data["exc_type"] == "RuntimeError"
    assert "Traceback" in data["exc_info"]


def test_uvicorn_filter_emits_record_without_exc_info(
    capsys: pytest.CaptureFixture[str], install_logging: Callable[[], logging.Logger]
) -> None:
    uvicorn_logger = install_logging()
    uvicorn_logger.info("Started server process")
    lines = capsys.readouterr().err.strip().splitlines()
    assert json.loads(lines[-1])["message"] == "Started server process"
