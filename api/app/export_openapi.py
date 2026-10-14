"""Write the OpenAPI schema to disk without starting a server (ADR 0001, decision 1)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = "0.0.0-contract"
DEFAULT_OUTPUT: Final[Path] = Path(__file__).resolve().parent.parent / "openapi.json"


def build_schema() -> dict[str, Any]:  # Any: FastAPI.openapi() returns dict[str, Any]
    """Build the deterministic OpenAPI schema from a fresh app."""
    raise NotImplementedError


def render_schema(schema: Mapping[str, Any]) -> str:  # Any: arbitrary JSON values
    """Serialise the schema to stable JSON text ending in exactly one newline."""
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
