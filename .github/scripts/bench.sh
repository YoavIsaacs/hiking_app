#!/usr/bin/env bash
# Helpers for the `benchmark` job in ci.yml (ADR 0004 section 5). Kept as a script so the same
# code runs in CI and in a local dry-run. Needs bash, jq and uv.
#
#   bench.sh run   <checkout-dir> <out.json>        run the benchmark test, write customSmallerIsBetter JSON
#   bench.sh seed  <bench.json> <out.json> <sha>    write a github-action-benchmark data file whose only
#                                                   entry is <bench.json> recorded under commit <sha>
#   bench.sh check <bench.json> <limit-seconds>     fail if any min >= limit (the absolute ceiling)
#   bench.sh ratio <base.json> <head.json>          print base/head min and head/base (log only)
set -euo pipefail

# Name the action stores results under; ci.yml passes the same value as `name:`.
BENCH_NAME="${BENCH_NAME:-gpx-parse}"

# pytest-benchmark JSON -> customSmallerIsBetter. value = min seconds (the most stable estimator for
# deterministic CPU-bound code), range = IQR, extra = median and rounds.
CONVERT='[.benchmarks[] | {
  name: .name,
  unit: "s",
  value: .stats.min,
  range: ("IQR " + (.stats.iqr | tostring) + " s"),
  extra: ("median " + (.stats.median | tostring) + " s, rounds " + (.stats.rounds | tostring))
}]'

cmd="${1:-}"
shift || true

case "$cmd" in
run)
  dir="$1"
  out="$2"
  mkdir -p "$(dirname "$out")"
  out="$(cd "$(dirname "$out")" && pwd)/$(basename "$out")"
  raw="$(mktemp)"
  # --no-cov: coverage tracing distorts timing and a subset run would trip --cov-fail-under.
  # Nothing is stored in .benchmarks/ because no --benchmark-save/autosave is given.
  (cd "$dir/api" && uv run --frozen pytest tests/routes/test_benchmark.py \
    --benchmark-enable --benchmark-only --no-cov --benchmark-json="$raw")
  jq "$CONVERT" "$raw" >"$out"
  rm -f "$raw"
  jq -e 'length > 0' "$out" >/dev/null || {
    echo "::error::no benchmark result was produced"
    exit 1
  }
  cat "$out"
  ;;
seed)
  jq --arg sha "$3" --arg name "$BENCH_NAME" \
    '{lastUpdate: 0, repoUrl: "", entries: {($name): [{
        commit: {id: $sha}, date: 0, tool: "customSmallerIsBetter", benches: .}]}}' \
    "$1" >"$2"
  ;;
check)
  if ! jq -e --argjson limit "$2" 'all(.[]; .value < $limit)' "$1" >/dev/null; then
    echo "::error::benchmark min is $(jq -c '[.[].value]' "$1") s; the ceiling is $2 s (ADR 0004 section 5)"
    exit 1
  fi
  echo "absolute check passed: $(jq -c '[.[].value]' "$1") s < $2 s"
  ;;
ratio)
  jq -rn --slurpfile b "$1" --slurpfile h "$2" \
    '($b[0][0].value) as $bv | ($h[0][0].value) as $hv |
     "base min \($bv) s, head min \($hv) s, head/base = \($hv / $bv) (fails above 1.2)"'
  ;;
*)
  echo "usage: bench.sh run|seed|check|ratio ..." >&2
  exit 2
  ;;
esac
