"""One-off recorder for the Open-Meteo elevation fixtures (ADR 0005 7).

Run by hand, never by pytest (the name does not match ``test_*.py``), from ``api/``:

    uv run python tests/fixtures/http/elevation/record.py

It reads every de-duplicated point of the three AllTrails parent fixtures, sends them
in batches of at most 100 to the LIVE ``/v1/elevation`` endpoint (19 calls in all), and
writes ``<parent-stem>.json`` plus the raw response bodies byte for byte under ``raw/``.

The app's ``split_batches``/``batch_query``/``format_coord`` were stubs when this was
recorded (step 1.3 red phase), so the same formatting is implemented here: comma-joined,
no spaces, ``f"{v:.5f}"``. Any failed call aborts the run; nothing is invented.
"""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

API_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(API_DIR))

from app.routes.parse import drop_consecutive_duplicates, parse_gpx  # noqa: E402

HERE = Path(__file__).resolve().parent
GPX_DIR = API_DIR / "tests" / "fixtures" / "gpx"
ENDPOINT = "https://api.open-meteo.com/v1/elevation"
DOCS = "https://open-meteo.com/en/docs/elevation-api"
BATCH = 100
WINDOW_S = 60.0
BUDGET_PER_WINDOW = 500
DECIMALS = 5
PARENTS = (
    "alltrails-tel-hadid-loop",
    "alltrails-modiin-hills-south-double-loop",
    "alltrails-ben-shemen-hertzl-singletrack",
)
COMMAND = "uv run python tests/fixtures/http/elevation/record.py  (run from api/)"
NOTES = (
    "Recorded with the formatting re-implemented in record.py because the app's "
    "format_coord/batch_query/split_batches were NotImplementedError stubs at the "
    "time: "
    "values f'{v:.5f}', comma-joined, no spaces, latitude and longitude as separate "
    "parameters, batches of at most 100 in point order. One-off manual call outside "
    "pytest."
)


def fmt(value: float) -> str:
    return f"{value:.{DECIMALS}f}"


def git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=API_DIR,
    )
    return out.stdout.strip()


class Pacer:
    """Open-Meteo's minutely limit (600) is charged per coordinate, not per request.

    Found while recording: the 7th request of 100 coordinates inside a minute got 429.
    Stay at or under 500 coordinates in any 60 s window.
    """

    def __init__(self) -> None:
        self.window_start = time.monotonic()
        self.used = 0

    def wait_for(self, n: int) -> None:
        if time.monotonic() - self.window_start >= WINDOW_S:
            self.window_start, self.used = time.monotonic(), 0
        if self.used + n > BUDGET_PER_WINDOW:
            time.sleep(max(0.0, WINDOW_S + 2 - (time.monotonic() - self.window_start)))
            self.window_start, self.used = time.monotonic(), 0
        self.used += n


PACER = Pacer()


def record(stem: str, client: httpx.Client, sha: str) -> None:
    data = (GPX_DIR / f"{stem}.gpx").read_bytes()
    points = drop_consecutive_duplicates(parse_gpx(data).points)
    recorded_at = (
        datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    requests: list[dict[str, object]] = []
    table: list[dict[str, object]] = []
    for k, start in enumerate(range(0, len(points), BATCH)):
        batch = points[start : start + BATCH]
        lats = ",".join(fmt(p.lat) for p in batch)
        lons = ",".join(fmt(p.lon) for p in batch)
        url = f"{ENDPOINT}?latitude={lats}&longitude={lons}"
        PACER.wait_for(len(batch))
        response = client.get(url)
        if response.status_code != 200:
            raise SystemExit(
                f"{stem} batch {k}: HTTP {response.status_code}: {response.text}"
            )
        values = json.loads(response.content)["elevation"]
        if len(values) != len(batch):
            raise SystemExit(
                f"{stem} batch {k}: got {len(values)} values for {len(batch)}"
            )
        raw_name = f"raw/{stem}-{k}.json"
        (HERE / raw_name).write_bytes(response.content)
        requests.append(
            {
                "url": url,
                "status": response.status_code,
                "date_header": response.headers.get("date"),
                "raw": raw_name,
            }
        )
        for p, v in zip(batch, values, strict=True):
            table.append(
                {
                    "lat": p.lat,
                    "lon": p.lon,
                    "sent": f"{fmt(p.lat)},{fmt(p.lon)}",
                    "elevation_m": v,
                }
            )
    meta = {
        "source_fixture": f"{stem}.gpx",
        "recorded_at": recorded_at,
        "endpoint": ENDPOINT,
        "command": COMMAND,
        "notes": NOTES,
        "git_sha": sha,
        "coord_decimals": DECIMALS,
        "docs_checked": DOCS,
        "requests": requests,
        "points": table,
    }
    (HERE / f"{stem}.json").write_text(
        json.dumps(meta, indent=1) + "\n", encoding="utf-8"
    )
    print(f"{stem}: {len(points)} points, {len(requests)} calls")


def main() -> None:
    sha = git_sha()
    with httpx.Client(
        timeout=30.0, headers={"User-Agent": "hike-prep-qa-recorder"}
    ) as client:
        for stem in PARENTS:
            record(stem, client, sha)


if __name__ == "__main__":
    main()
