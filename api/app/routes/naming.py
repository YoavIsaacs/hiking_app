"""Route name selection (ADR 0004 §3.9)."""


def route_name(
    metadata_name: str | None, track_name: str | None, filename: str | None
) -> str:
    raise NotImplementedError
