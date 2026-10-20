"""prethin(): O(n) pre-thinning before ranked RDP (ADR 0004 section 3.5).

The tables are worked by hand from the ADR: F = {0, n-1} + keep, M = min_points,
P = max_points; M index picks i_j = 1 + floor(j*(n-2)/M), j = 0..M-1; then
r = P - |F| - M distance picks, target t_j = j*L/(r+1), first index with dist >= t_j.
"""

import itertools

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.routes.params import DEFAULT_PARAMS, ParseParams
from app.routes.simplify import prethin


def cumulative(steps: list[float]) -> list[float]:
    return [0.0, *itertools.accumulate(steps)]


# --- identity under the budget --------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 2, 10, 2000])
def test_up_to_max_points_is_the_identity(n: int) -> None:
    assert prethin([float(i) for i in range(n)]) == tuple(range(n))


def test_the_defaults_are_the_documented_ones() -> None:
    assert DEFAULT_PARAMS.max_points == 500
    assert DEFAULT_PARAMS.prethin_max_points == 2000


def test_one_point_over_the_budget_is_thinned() -> None:
    out = prethin([float(i) for i in range(2001)])
    assert 502 <= len(out) <= 2000
    assert out[0] == 0 and out[-1] == 2000


# --- hand-worked tables ---------------------------------------------------------------


def test_table_uniform_20_points_min_3_max_10() -> None:
    # index picks 1, 7, 13; distance targets 3.17 6.33 9.5 12.67 15.83 -> 4 7 10 13 16
    assert prethin([float(i) for i in range(20)], min_points=3, max_points=10) == (
        0,
        1,
        4,
        7,
        10,
        13,
        16,
        19,
    )


def test_table_keep_index_is_forced_and_shrinks_the_distance_budget() -> None:
    # F = {0, 10, 19}; index picks 1, 7, 13; r = 4; targets 3.8 7.6 11.4 15.2
    # give 4 8 12 16
    out = prethin([float(i) for i in range(20)], keep=[10], min_points=3, max_points=10)
    assert out == (0, 1, 4, 7, 8, 10, 12, 13, 16, 19)


def test_table_distance_picks_that_land_on_the_end_give_one_candidate() -> None:
    # index picks 1, 4, 7; r = 1: target 50 -> index 11, already forced
    dist = [float(i) for i in range(11)] + [100.0]
    assert prethin(dist, min_points=3, max_points=6) == (0, 1, 4, 7, 11)


def test_table_zero_length_track_has_only_index_picks() -> None:
    assert prethin([0.0] * 12, min_points=3, max_points=6) == (0, 1, 4, 7, 11)


def test_table_all_distance_targets_on_the_same_index_collapse() -> None:
    dist = [0.0] * 14 + [10.0]
    assert prethin(dist, min_points=3, max_points=8) == (0, 1, 5, 9, 14)


# --- properties -----------------------------------------------------------------------


@st.composite
def thinning_cases(draw: st.DrawFn) -> tuple[list[float], list[int], int, int]:
    min_points = draw(st.integers(3, 12))
    max_points = draw(st.integers(2 * min_points, 5 * min_points))
    n = draw(st.integers(max_points + 1, max_points + 300))
    shape = draw(st.sampled_from(["uniform", "random", "zero", "clustered", "sparse"]))
    if shape == "uniform":
        steps = [draw(st.floats(0.5, 20.0))] * (n - 1)
    elif shape == "zero":
        steps = [0.0] * (n - 1)
    elif shape == "clustered":  # all but one step is tiny
        steps = [1e-4] * (n - 1)
        steps[draw(st.integers(0, n - 2))] = 5000.0
    elif shape == "sparse":  # dense recording, then a few long hops
        steps = [0.01] * (n - 1)
        for _ in range(3):
            steps[draw(st.integers(0, n - 2))] = 1000.0
    else:
        steps = draw(st.lists(st.floats(0.0, 100.0), min_size=n - 1, max_size=n - 1))
    forced_room = min_points - 2
    keep = draw(
        st.lists(st.integers(0, n - 1), max_size=max(0, forced_room), unique=True)
    )
    return cumulative(steps), keep, min_points, max_points


@settings(
    max_examples=200,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(thinning_cases())
def test_output_is_sorted_distinct_forced_and_within_the_budget(
    case: tuple[list[float], list[int], int, int],
) -> None:
    dist, keep, min_points, max_points = case
    n = len(dist)
    out = prethin(dist, keep=keep, min_points=min_points, max_points=max_points)
    assert list(out) == sorted(set(out))
    assert all(0 <= i < n for i in out)
    assert {0, n - 1, *keep} <= set(out)
    assert min_points + 2 <= len(out) <= max_points
    assert out == prethin(dist, keep=keep, min_points=min_points, max_points=max_points)


@settings(max_examples=60, deadline=None, derandomize=True)
@given(st.integers(2001, 5000), st.integers(0, 4999))
def test_default_budget_leaves_room_for_rdp_with_a_forced_high_point(
    n: int, high: int
) -> None:
    out = prethin([float(i) for i in range(n)], keep=[high % n])
    assert 502 <= len(out) <= 2000
    assert {0, n - 1, high % n} <= set(out)


# --- the reasons for two strides ------------------------------------------------------


def test_a_sparse_stretch_survives_inside_a_dense_recording() -> None:
    """100k points over 1 km, then 50 points over 10 km: the index stride alone would
    keep about one of the 50."""
    dense = [i * 1000.0 / 100_000 for i in range(100_000)]
    sparse = [1000.0 + (j + 1) * 9000.0 / 50 for j in range(50)]
    out = prethin([*dense, *sparse])
    assert sum(1 for i in out if i >= 100_000) >= 40
    assert 502 <= len(out) <= 2000


def test_a_collapsed_distance_stride_still_gives_the_guaranteed_count() -> None:
    """All but one point within 1 m: distance targets collapse onto few indices, the
    index stride must still leave at least min_points + 2 candidates."""
    dist = [i * 1e-4 for i in range(9_999)] + [5000.0]
    out = prethin(dist)
    assert len(out) >= DEFAULT_PARAMS.max_points + 2
    assert len(out) <= DEFAULT_PARAMS.prethin_max_points


def test_a_zero_length_track_does_not_raise_and_keeps_the_count() -> None:
    out = prethin([0.0] * 5000)
    assert 502 <= len(out) <= 2000
    assert out[0] == 0 and out[-1] == 4999


def test_a_100k_point_input_is_thinned_to_the_budget() -> None:
    out = prethin([i * 0.5 for i in range(100_000)])
    assert 502 <= len(out) <= 2000
    assert out[0] == 0 and out[-1] == 99_999


# --- preconditions --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("min_points", "max_points"), [(5, 9), (500, 999), (3, 5), (10, 0)]
)
def test_max_points_below_twice_min_points_raises(
    min_points: int, max_points: int
) -> None:
    with pytest.raises(ValueError):
        prethin(
            [float(i) for i in range(2000)],
            min_points=min_points,
            max_points=max_points,
        )


def test_exactly_twice_min_points_is_allowed() -> None:
    out = prethin([float(i) for i in range(100)], min_points=5, max_points=10)
    assert 7 <= len(out) <= 10


def test_more_forced_indices_than_min_points_raises() -> None:
    with pytest.raises(ValueError):
        prethin(
            [float(i) for i in range(100)],
            keep=[10, 20, 30, 40],  # F = {0, 99, 10, 20, 30, 40} = 6 > 5
            min_points=5,
            max_points=20,
        )


def test_exactly_min_points_forced_indices_is_allowed() -> None:
    out = prethin(
        [float(i) for i in range(100)],
        keep=[10, 20, 30],  # F has 5 members == min_points
        min_points=5,
        max_points=20,
    )
    assert {0, 99, 10, 20, 30} <= set(out)


# --- ParseParams ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("max_points", "prethin_max_points"),
    [(500, 999), (500, 499), (500, 0), (500, -1), (3, 5), (100, 199), (250, 100)],
)
def test_prethin_budget_below_twice_max_points_is_rejected(
    max_points: int, prethin_max_points: int
) -> None:
    with pytest.raises(ValueError):
        ParseParams(max_points=max_points, prethin_max_points=prethin_max_points)


@pytest.mark.parametrize(
    ("max_points", "prethin_max_points"),
    [(500, 1000), (500, 2000), (3, 6), (3, 10), (100, 200)],
)
def test_prethin_budget_of_at_least_twice_max_points_is_accepted(
    max_points: int, prethin_max_points: int
) -> None:
    params = ParseParams(max_points=max_points, prethin_max_points=prethin_max_points)
    assert params.prethin_max_points == prethin_max_points
