#!/usr/bin/env bash
# Helpers for the `benchmark` job in ci.yml (ADR 0004 section 5). Kept as a script so the same
# code runs in CI and in a local dry-run. Needs bash, jq and uv.
#
#   bench.sh run   <checkout-dir> <out.json>        run the benchmark test, write customSmallerIsBetter JSON
#   bench.sh seed  <bench.json> <out.json> <sha>    write a github-action-benchmark data file whose only
#                                                   entry is <bench.json> recorded under commit <sha>
#   bench.sh check <bench.json> <limit-seconds>     fail if any min >= limit (the absolute ceiling)
#   bench.sh names <base.json> <head.json>          fail if head is empty or base and head share no name; else
#                                                   warn about one-sided names and filter both files to the shared ones.
#                                                   A rename is two PRs: add the new name (keep the old), then remove the old.
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
names)
  # Rewrites both files in place to the benchmarks they share (sorted by name), so the comparison
  # only sees comparable entries. Names on one side only are reported as a warning, not an error.
  hn="$(jq -c 'map(.name) | sort' "$2")"
  bn="$(jq -c 'map(.name) | sort' "$1")"
  if [ "$hn" = "[]" ]; then
    echo "::error::the head produced no benchmarks"
    exit 1
  fi
  common="$(jq -nc --argjson b "$bn" --argjson h "$hn" '$b - ($b - $h)')"
  if [ "$common" = "[]" ]; then
    echo "::error::base and head share no benchmark name (base $bn, head $hn), so nothing is comparable and the gate would be a no-op. Rename in two PRs: add the new name keeping the old, then remove the old."
    exit 1
  fi
  only_base="$(jq -nc --argjson b "$bn" --argjson c "$common" '$b - $c')"
  only_head="$(jq -nc --argjson h "$hn" --argjson c "$common" '$h - $c')"
  if [ "$only_base" != "[]" ] || [ "$only_head" != "[]" ]; then
    echo "::warning::benchmark names differ; comparing only $common. Only in base (removed or renamed): $only_base. Only in head (new, not compared this time): $only_head."
  fi
  for f in "$1" "$2"; do
    jq --argjson c "$common" 'map(select(.name as $n | $c | index($n))) | sort_by(.name)' "$f" >"$f.tmp"
    mv "$f.tmp" "$f"
  done
  echo "benchmarks compared: $common"
  ;;
ratio)
  jq -rn --slurpfile b "$1" --slurpfile h "$2" \
    '($b[0][0].value) as $bv | ($h[0][0].value) as $hv |
     "base min \($bv) s, head min \($hv) s, head/base = \($hv / $bv) (fails above 1.2)"'
  ;;
*)
  echo "usage: bench.sh run|seed|check|names|ratio ..." >&2
  exit 2
  ;;
esac
