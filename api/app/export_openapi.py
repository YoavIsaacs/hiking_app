"""Write the OpenAPI schema to disk without starting a server (ADR 0001, decision 2)."""

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from app.config import Settings
from app.main import create_app

SCHEMA_VERSION: Final = "0.0.0-contract"
DEFAULT_OUTPUT: Final[Path] = Path(__file__).resolve().parent.parent / "openapi.json"


def build_schema() -> dict[str, Any]:  # Any: FastAPI.openapi() returns dict[str, Any]
    """Build the deterministic OpenAPI schema from a fresh app."""
    return create_app(Settings(_env_file=None, version=SCHEMA_VERSION)).openapi()


def render_schema(schema: Mapping[str, Any]) -> str:  # Any: arbitrary JSON values
    """Serialise the schema to stable JSON text ending in exactly one newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description="Export the OpenAPI schema.")
    parser.add_argument("output", nargs="?", type=Path, default=None)
    args = parser.parse_args(argv)
    output: Path = args.output if args.output is not None else DEFAULT_OUTPUT
    text = render_schema(build_schema())
    with output.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
