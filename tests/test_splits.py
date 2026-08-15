"""Walk-forward splitter tests.

The tests marked ``pointintime`` are the ones that matter. `CLAUDE.md` §3
forbids any split that lets information travel backwards in time, and a
splitter is exactly the place that failure hides: it produces plausible
numbers either way, and nothing downstream notices.

Per ``pyproject.toml``, ``pointintime`` tests are never skipped.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from heat_nowcast.evaluation.splits import (
    ExpandingWindowSplitter,
    effective_sample_size,
)


def half_hourly(days: int = 400, start: str = "2023-01-01") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=days * 48, freq="30min", tz="UTC"))


def default_splitter(**overrides: object) -> ExpandingWindowSplitter:
    kwargs: dict[str, object] = {
        "initial_train_end": pd.Timestamp("2023-06-30", tz="UTC"),
        "test_span": pd.DateOffset(months=1),
        "embargo": pd.Timedelta(days=7),
    }
    kwargs.update(overrides)
    return ExpandingWindowSplitter(**kwargs)  # type: ignore[arg-type]  # kwargs is heterogeneous by construction


# --------------------------------------------------------------------------
# the leakage assertions
# --------------------------------------------------------------------------


@pytest.mark.pointintime
def test_no_training_row_is_at_or_after_its_test_window():
    """The headline invariant: no future data reaches any training fold."""
    times = half_hourly()
    folds = list(default_splitter().split(times))
    assert len(folds) > 5

    for fold in folds:
        train_times = times.iloc[fold.train_index]
        test_times = times.iloc[fold.test_index]
        assert len(train_times) > 0
        assert len(test_times) > 0
        assert train_times.max() < test_times.min(), (
            f"fold {fold.fold_index} leaks: training reaches "
            f"{train_times.max()} but testing starts {test_times.min()}"
        )


@pytest.mark.pointintime
def test_embargo_gap_is_actually_enforced():
    """A strict inequality is not enough -- the gap must be at least the embargo."""
    times = half_hourly()
    embargo = pd.Timedelta(days=7)
    for fold in default_splitter(embargo=embargo).split(times):
        train_times = times.iloc[fold.train_index]
        test_times = times.iloc[fold.test_index]
        assert test_times.min() - train_times.max() >= embargo
        assert train_times.max() <= fold.train_end
        assert test_times.min() >= fold.embargo_end


@pytest.mark.pointintime
def test_no_row_appears_in_both_train_and_test_of_a_fold():
    times = half_hourly()
    for fold in default_splitter().split(times):
        assert len(np.intersect1d(fold.train_index, fold.test_index)) == 0


@pytest.mark.pointintime
def test_shuffling_the_input_does_not_change_the_partition():
    """Positional indices must follow the timestamps, not the row order.

    If a caller hands in an unsorted frame, the splitter must still cut on
    time. Otherwise a sort upstream silently changes which rows are 'past'.
    """
    times = half_hourly(days=200)
    rng = np.random.default_rng(seed=20260814)
    permutation = rng.permutation(len(times))
    shuffled = times.iloc[permutation].reset_index(drop=True)

    ordered_folds = list(default_splitter().split(times))
    shuffled_folds = list(default_splitter().split(shuffled))
    assert len(ordered_folds) == len(shuffled_folds)

    for ordered, mixed in zip(ordered_folds, shuffled_folds, strict=True):
        assert set(times.iloc[ordered.train_index]) == set(
            shuffled.iloc[mixed.train_index]
        )
        assert set(times.iloc[ordered.test_index]) == set(
            shuffled.iloc[mixed.test_index]
        )
        # And the invariant still holds on the shuffled input.
        assert (
            shuffled.iloc[mixed.train_index].max()
            < shuffled.iloc[mixed.test_index].min()
        )


@pytest.mark.pointintime
def test_a_deliberately_leaky_split_would_fail_the_invariant():
    """Guard the guard: confirm the assertion above can actually fail.

    A test that passes against a broken implementation is worthless. Here the
    training set is deliberately extended past the cut, and the same check
    used above must reject it.
    """
    times = half_hourly(days=300)
    fold = next(iter(default_splitter().split(times)))

    leaky_train = np.concatenate([fold.train_index, fold.test_index[:1]])
    assert times.iloc[leaky_train].max() >= times.iloc[fold.test_index].min()


# --------------------------------------------------------------------------
# ordinary behaviour
# --------------------------------------------------------------------------


def test_training_window_expands_and_never_shrinks():
    times = half_hourly()
    sizes = [len(fold.train_index) for fold in default_splitter().split(times)]
    assert sizes == sorted(sizes)
    assert sizes[-1] > sizes[0]


def test_test_windows_are_contiguous_and_ordered():
    times = half_hourly()
    folds = list(default_splitter().split(times))
    starts = [fold.test_start for fold in folds]
    assert starts == sorted(starts)
    for earlier, later in itertools.pairwise(folds):
        # Contiguous and non-overlapping: each window starts exactly where the
        # previous one ended, so every row is scored at most once.
        assert later.test_start == earlier.test_end


def test_every_test_row_falls_inside_its_declared_window():
    times = half_hourly()
    for fold in default_splitter().split(times):
        test_times = times.iloc[fold.test_index]
        assert test_times.min() >= fold.test_start
        assert test_times.max() < fold.test_end


def test_max_folds_caps_the_walk():
    times = half_hourly()
    folds = list(default_splitter(max_folds=3).split(times))
    assert len(folds) == 3


def test_no_folds_when_history_ends_before_the_first_test_window():
    times = pd.Series(
        pd.date_range("2023-01-01", periods=48 * 10, freq="30min", tz="UTC")
    )
    assert list(default_splitter().split(times)) == []


def test_n_splits_matches_split():
    times = half_hourly()
    splitter = default_splitter()
    assert splitter.n_splits(times) == len(list(splitter.split(times)))


def test_empty_input_raises():
    with pytest.raises(ValueError, match="empty series"):
        list(default_splitter().split(pd.Series([], dtype="datetime64[ns, UTC]")))


def test_timezone_mismatch_raises():
    naive = pd.Series(pd.date_range("2023-01-01", periods=48 * 300, freq="30min"))
    with pytest.raises(ValueError, match="timezone-awareness"):
        list(default_splitter().split(naive))


def test_negative_embargo_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        default_splitter(embargo=pd.Timedelta(days=-1))


# --------------------------------------------------------------------------
# effective sample size
# --------------------------------------------------------------------------


def test_effective_n_equals_n_for_white_noise():
    rng = np.random.default_rng(seed=20260814)
    noise = pd.Series(rng.normal(size=5000))
    assert effective_sample_size(noise) == pytest.approx(5000, rel=0.15)


def test_effective_n_is_far_below_n_for_persistent_series():
    """Half-hourly demand residuals look like this, not like white noise."""
    rng = np.random.default_rng(seed=20260814)
    innovations = rng.normal(size=5000)
    persistent = np.zeros(5000)
    for position in range(1, 5000):
        persistent[position] = 0.95 * persistent[position - 1] + innovations[position]
    n_eff = effective_sample_size(pd.Series(persistent))
    assert n_eff < 500
    assert n_eff >= 1


def test_effective_n_handles_degenerate_input():
    assert effective_sample_size(pd.Series([1.0])) == 1.0
    assert effective_sample_size(pd.Series([2.0] * 100)) == 100.0
