"""app/timing/ stays pure (ADR 0006 §7): allow-listed imports, no clock reads."""

import ast
from pathlib import Path

import pytest

TIMING_DIR = Path(__file__).parents[2] / "app" / "timing"
ALLOWED = {
    "math",
    "bisect",
    "itertools",
    "collections.abc",
    "typing",
    "datetime",
    "app.models.route",
    "app.models.timing",
}
CLOCK_CALLS = {"now", "utcnow", "today"}


def imported_modules(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "app.timing" if node.level else ""
            module = node.module or ""
            name = f"{base}.{module}" if base and module else base or module
            found.append(name)
            if not module:  # "from . import x"
                found += [f"{name}.{a.name}" for a in node.names]
    return found


def violations(source: str) -> list[str]:
    tree = ast.parse(source)
    problems = [
        f"import {m}"
        for m in imported_modules(tree)
        if m not in ALLOWED and not (m == "app.timing" or m.startswith("app.timing."))
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if called in CLOCK_CALLS:
                problems.append(f"call {called}()")
    return problems


def timing_sources() -> list[Path]:
    return sorted(TIMING_DIR.glob("*.py"))


def test_the_timing_package_has_its_three_modules() -> None:
    names = {p.name for p in timing_sources()}
    assert {"estimate.py", "tobler.py", "params.py"} <= names


@pytest.mark.parametrize("path", timing_sources(), ids=lambda p: p.name)
def test_timing_module_is_pure(path: Path) -> None:
    assert violations(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import os", ["import os"]),
        ("import time", ["import time"]),
        ("import random", ["import random"]),
        ("import logging", ["import logging"]),
        ("import httpx", ["import httpx"]),
        ("from app.config import Settings", ["import app.config"]),
        ("from app import config", ["import app"]),
        ("from datetime import datetime\nx = datetime.now()", ["call now()"]),
        ("import datetime\nx = datetime.datetime.utcnow()", ["call utcnow()"]),
        ("from datetime import date\nx = date.today()", ["call today()"]),
        ("import math\nfrom app.timing.params import X\nfrom . import tobler", []),
    ],
)
def test_the_purity_checker_catches_what_it_should(
    source: str, expected: list[str]
) -> None:
    assert violations(source) == expected
