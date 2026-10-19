"""Throwaway for step 0.6: proves a failing api-test blocks the merge. Never merge."""


def test_throwaway_always_fails_for_step_0_6() -> None:
    # Deliberate failure (throwaway for 0.6).
    expected = int("2")
    assert expected == 1
