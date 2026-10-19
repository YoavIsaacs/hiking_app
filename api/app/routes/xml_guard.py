"""Stdlib-only XML prolog guard: forbids DTDs, checks the root is <gpx>."""


def check_gpx_prolog(data: bytes) -> None:
    """Raise InvalidGpx on DTD/entity, malformed prolog, no root, or root != gpx."""
    raise NotImplementedError
