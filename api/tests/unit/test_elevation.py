"""Unit tests for app.routes.elevation (ADR 0004 3.4)."""

import math

import pytest

from app.routes.elevation import gain_loss, high_point_index, smooth_elevation

# --- smooth_elevation ----------------------------------------------------------------


def test_constant_profile_stays_constant() -> None:
    out = smooth_elevation([0.0, 50.0, 100.0], [7.0, 7.0, 7.0], window_m=30.0)
    assert out == pytest.approx((7.0,) * len(out))
    assert len(out) == 21  # 100 m at 5 m steps, both ends included


def test_linear_profile_passes_through_unchanged_ends_included() -> None:
    dist = [0.0, 40.0, 100.0, 160.0]
    elev = [10.0 + 0.1 * d for d in dist]
    out = smooth_elevation(dist, elev, window_m=40.0)
    step = 160.0 / (len(out) - 1)
    for k, value in enumerate(out):
        assert value == pytest.approx(10.0 + 0.1 * k * step, abs=1e-9)
    assert out[0] == elev[0] and out[-1] == elev[-1]


def test_window_zero_is_the_plain_resample() -> None:
    dist = [0.0, 10.0, 20.0]
    elev = [0.0, 10.0, 0.0]
    out = smooth_elevation(dist, elev, window_m=0.0, step_m=5.0)
    assert out == (0.0, 5.0, 10.0, 5.0, 0.0)


def test_a_window_narrower_than_one_step_is_the_plain_resample() -> None:
    dist = [0.0, 10.0, 20.0]
    elev = [0.0, 10.0, 0.0]
    out = smooth_elevation(dist, elev, window_m=4.0, step_m=5.0)
    assert out == (0.0, 5.0, 10.0, 5.0, 0.0)


def test_a_spike_is_flattened_but_the_ends_keep_their_raw_values() -> None:
    dist = [float(d) for d in range(0, 101, 5)]
    elev = [0.0] * 21
    elev[10] = 20.0
    out = smooth_elevation(dist, elev, window_m=20.0, step_m=5.0)
    assert out[10] == pytest.approx(20.0 / 5)
    assert out[0] == 0.0 and out[-1] == 0.0


def test_zero_length_and_repeated_distances_do_not_raise() -> None:
    assert smooth_elevation([0.0, 0.0], [3.0, 4.0]) == (3.0, 4.0)
    out = smooth_elevation([0.0, 10.0, 10.0, 20.0], [0.0, 5.0, 9.0, 10.0], window_m=0)
    assert out[2] == 9.0  # the later point wins at a repeated distance
    assert out[0] == 0.0 and out[-1] == 10.0


def test_sample_count_respects_max_samples() -> None:
    out = smooth_elevation([0.0, 1_000_000.0], [0.0, 1.0], max_samples=50)
    assert len(out) == 51
    assert out[-1] == 1.0


def test_a_very_short_profile_uses_a_single_interval() -> None:
    assert smooth_elevation([0.0, 1.0], [0.0, 2.0], step_m=5.0) == (0.0, 2.0)


def test_densified_track_gives_the_same_series() -> None:
    dist = [0.0, 33.0, 80.0, 150.0, 260.0]
    elev = [10.0, 14.0, 9.0, 20.0, 12.0]

    def densify(factor: int) -> tuple[list[float], list[float]]:
        d, e = [dist[0]], [elev[0]]
        for i in range(1, len(dist)):
            for k in range(1, factor + 1):
                f = k / factor
                d.append(dist[i - 1] + (dist[i] - dist[i - 1]) * f)
                e.append(elev[i - 1] + (elev[i] - elev[i - 1]) * f)
        return d, e

    base = smooth_elevation(dist, elev)
    dense_dist, dense_elev = densify(14)
    dense = smooth_elevation(dense_dist, dense_elev)
    assert len(base) == len(dense)
    assert max(abs(a - b) for a, b in zip(base, dense, strict=True)) < 0.05


# --- gain_loss -----------------------------------------------------------------------


def test_monotone_climb_is_all_gain() -> None:
    assert gain_loss([0.0, 3.0, 8.0, 20.0], threshold_m=5.0) == (20.0, 0.0)


def test_monotone_descent_is_all_loss() -> None:
    assert gain_loss([20.0, 8.0, 3.0, 0.0], threshold_m=5.0) == (0.0, 20.0)


def test_wiggles_below_the_threshold_inside_a_climb_add_nothing() -> None:
    assert gain_loss([0.0, 10.0, 7.0, 12.0, 9.0, 20.0], threshold_m=5.0) == (20.0, 0.0)


def test_a_series_that_never_leaves_the_band_counts_first_to_last() -> None:
    assert gain_loss([0.0, 2.0, -1.0, 3.0], threshold_m=10.0) == (3.0, 0.0)
    assert gain_loss([5.0, 3.0, 4.0, 1.0], threshold_m=10.0) == (0.0, 4.0)


def test_zero_threshold_is_total_variation() -> None:
    assert gain_loss([0.0, 3.0, 1.0, 4.0, 4.0, 0.0], threshold_m=0.0) == (6.0, 6.0)


def test_worked_example_from_the_adr() -> None:
    assert gain_loss([0.0, 5.0, -10.0], threshold_m=8.0) == (5.0, 15.0)
    assert gain_loss([-10.0, 5.0, 0.0], threshold_m=8.0) == (15.0, 5.0)


def test_a_fall_out_of_the_initial_band_counts_the_first_leg_as_gain() -> None:
    assert gain_loss([0.0, 3.0, -6.0], threshold_m=8.0) == (3.0, 9.0)


def test_a_dip_inside_the_initial_band_is_the_first_leg() -> None:
    # min -2 inside the band: leg 0 -> -2 is loss, then the climb out to 9.
    assert gain_loss([0.0, 3.0, -2.0, 9.0], threshold_m=8.0) == (11.0, 2.0)


def test_short_series_have_no_gain_or_loss() -> None:
    assert gain_loss([]) == (0.0, 0.0)
    assert gain_loss([42.0]) == (0.0, 0.0)


def test_threshold_exactly_equal_to_the_swing_is_confirmed() -> None:
    assert gain_loss([0.0, 5.0, 0.0], threshold_m=5.0) == (5.0, 5.0)


def test_gain_minus_loss_is_last_minus_first() -> None:
    series = [3.0, 9.0, 1.0, 14.0, 6.0, 7.0, 0.5]
    gain, loss = gain_loss(series, threshold_m=4.0)
    assert gain - loss == pytest.approx(series[-1] - series[0])
    assert math.isfinite(gain) and math.isfinite(loss)


# --- high_point_index ----------------------------------------------------------------


def test_high_point_is_the_first_maximum() -> None:
    assert high_point_index([1.0, 5.0, 2.0, 5.0]) == 1
    assert high_point_index([7.0]) == 0


def test_high_point_of_nothing_raises() -> None:
    with pytest.raises(ValueError):
        high_point_index([])
