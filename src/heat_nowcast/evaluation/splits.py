"""Time-ordered splitters. The only sanctioned way to partition this data.

`CLAUDE.md` §3 is categorical: no shuffling, no k-fold, expanding-window
walk-forward with an embargo at every boundary. This module implements that
and nothing else. There is deliberately no random-split code path to reach for
in a hurry.

The embargo is not decoration. Two separate lags make it necessary here:

* **Outturn publication.** NESO's demand outturn appears roughly a day after
  the settlement day. A model refitted at 08:45 UTC on D-1 cannot have trained
  on D-2's outturn if that outturn had not yet published.
* **ERA5 publication.** The baseline trains on realised (ERA5) temperature,
  which lags ~5 days in its preliminary release
  (``docs/data_inventory.md`` §5.2). Training rows must be old enough that
  ERA5 had actually published them by the refit date.

The default embargo of 7 days covers both with room to spare. It is a
parameter, not a constant, and shortening it is a research decision that
belongs in the decision log.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

#: Default embargo: covers NESO's ~1-day outturn lag and ERA5's ~5-day
#: preliminary release lag, with room to spare.
DEFAULT_EMBARGO: Final[pd.Timedelta] = pd.Timedelta(days=7)


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold.

    Attributes
    ----------
    fold_index :
        0-based position in the walk.
    train_index :
        Positional indices into the ordered frame forming the training set.
    test_index :
        Positional indices forming the out-of-sample test set.
    train_end :
        Last timestamp actually present in the training set.
    embargo_end :
        End of the embargoed gap. No training row may lie at or after this,
        and no test row may lie before it.
    test_start, test_end :
        Bounds of the test window, inclusive.
    """

    fold_index: int
    train_index: np.ndarray
    test_index: np.ndarray
    train_end: pd.Timestamp
    embargo_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


class ExpandingWindowSplitter:
    """Expanding-window walk-forward splitter with an embargoed gap.

    Every fold trains on **all** history up to a cut, skips an embargo, and
    tests on the following step. The training set only ever grows, and it
    never contains a timestamp at or after the corresponding test window --
    that invariant is what :mod:`tests.test_splits` asserts directly.

    Parameters
    ----------
    initial_train_end :
        End of the first training window (inclusive). The first test window
        opens after the embargo that follows it.
    test_span :
        Length of each test window, e.g. ``pd.DateOffset(months=1)``. Also the
        refit cadence: the model is refit once per fold.
    embargo :
        Gap between the end of training and the start of testing. Defaults to
        7 days -- see the module docstring.
    max_folds :
        Optional cap on the number of folds, for smoke tests.

    Examples
    --------
    >>> import pandas as pd
    >>> times = pd.Series(pd.date_range("2024-01-01", periods=400, freq="D", tz="UTC"))
    >>> splitter = ExpandingWindowSplitter(
    ...     initial_train_end=pd.Timestamp("2024-06-30", tz="UTC"),
    ...     test_span=pd.DateOffset(months=1),
    ... )
    >>> folds = list(splitter.split(times))
    >>> all(times[f.train_index].max() < times[f.test_index].min() for f in folds)
    True
    """

    def __init__(
        self,
        *,
        initial_train_end: pd.Timestamp,
        test_span: pd.DateOffset,
        embargo: pd.Timedelta = DEFAULT_EMBARGO,
        max_folds: int | None = None,
    ) -> None:
        if embargo < pd.Timedelta(0):
            msg = "embargo must be non-negative"
            raise ValueError(msg)
        if max_folds is not None and max_folds < 1:
            msg = "max_folds must be at least 1"
            raise ValueError(msg)
        self.initial_train_end = pd.Timestamp(initial_train_end)
        self.test_span = test_span
        self.embargo = embargo
        self.max_folds = max_folds

    def split(self, timestamps: pd.Series) -> Iterator[Fold]:
        """Yield folds in chronological order.

        Parameters
        ----------
        timestamps :
            Timestamps of the rows to be split, one per row, in the same order
            as the frame the returned positional indices will index into. They
            need not be sorted; sorting is applied internally and the returned
            indices refer to the *original* positions.

        Yields
        ------
        Fold
            Successive expanding-window folds. Folds whose test window
            contains no rows are skipped, not emitted empty.

        Raises
        ------
        ValueError
            If ``timestamps`` is empty, or mixes timezone-aware and naive
            values, or if the splitter's timezone-awareness does not match.
        """
        times = pd.Series(pd.to_datetime(pd.Series(timestamps).to_numpy()))
        if len(times) == 0:
            msg = "cannot split an empty series"
            raise ValueError(msg)

        series_tz = pd.DatetimeIndex(times).tz
        cut = pd.Timestamp(self.initial_train_end).as_unit("ns")
        if (series_tz is None) != (cut.tz is None):
            msg = "timestamps and initial_train_end must agree on timezone-awareness"
            raise ValueError(msg)

        # Compare in integer nanoseconds. Timezone-aware pandas series fall
        # back to an object-dtype numpy array, which compares elementwise and
        # slowly; the integer view is both exact and dtype-stable. `as_unit`
        # is not optional: pandas may hold datetimes at microsecond
        # resolution, and the integer view then counts microseconds while
        # `Timestamp.value` always counts nanoseconds. Mixing the two silently
        # places every cut ~1000x too early and yields zero folds.
        index = pd.DatetimeIndex(times).as_unit("ns")
        nanoseconds = index.astype("int64").to_numpy()
        positions = np.arange(len(times))
        order = np.argsort(nanoseconds, kind="stable")
        sorted_nanoseconds = nanoseconds[order]
        sorted_positions = positions[order]

        last_nanosecond = int(sorted_nanoseconds[-1])
        fold_index = 0
        while True:
            if self.max_folds is not None and fold_index >= self.max_folds:
                return

            embargo_end = pd.Timestamp(cut + self.embargo).as_unit("ns")
            test_start = embargo_end
            # The test window ends where the *next* fold's window begins, not
            # at `test_start + test_span`. With a calendar offset those two
            # differ whenever adjacent months have different lengths, and the
            # difference makes consecutive test windows overlap -- which would
            # score some rows twice and quietly break the "identical rows,
            # once each" guarantee the comparison table depends on.
            test_end = pd.Timestamp(cut + self.test_span + self.embargo).as_unit("ns")
            if test_start.value > last_nanosecond:
                return

            train_mask = sorted_nanoseconds <= cut.value
            test_mask = (sorted_nanoseconds >= test_start.value) & (
                sorted_nanoseconds < test_end.value
            )

            if train_mask.any() and test_mask.any():
                train_end = index[sorted_positions[train_mask]].max()
                yield Fold(
                    fold_index=fold_index,
                    train_index=np.sort(sorted_positions[train_mask]),
                    test_index=np.sort(sorted_positions[test_mask]),
                    train_end=pd.Timestamp(train_end),
                    embargo_end=embargo_end,
                    test_start=test_start,
                    test_end=test_end,
                )
                fold_index += 1

            cut = pd.Timestamp(cut + self.test_span).as_unit("ns")

    def n_splits(self, timestamps: pd.Series) -> int:
        """Return the number of folds this splitter would produce."""
        return sum(1 for _ in self.split(timestamps))


def effective_sample_size(
    residuals: pd.Series,
    *,
    max_lag: int = 48,
) -> float:
    """Estimate independent observations in an autocorrelated residual series.

    Half-hourly GB demand is enormously autocorrelated; 50,000 rows is not
    50,000 observations, and any standard error computed as though it were is
    wrong (`CLAUDE.md` §3). This applies the standard variance-inflation
    correction::

        n_eff = n / (1 + 2 * sum_{k=1..K} rho_k)

    truncated at the first non-positive autocorrelation, which keeps the
    estimate from being dragged around by noisy long-lag terms.

    Parameters
    ----------
    residuals :
        Forecast errors, in time order.
    max_lag :
        Highest lag considered. 48 is one day of half-hourly data.

    Returns
    -------
    float
        Estimated effective sample size, clipped to at least 1.
    """
    values = pd.Series(residuals).dropna().to_numpy(dtype="float64")
    n_obs = len(values)
    if n_obs < 3:
        return float(max(n_obs, 1))

    centred = values - values.mean()
    denominator = float(np.dot(centred, centred))
    if denominator == 0.0:
        return float(n_obs)

    inflation = 1.0
    for lag in range(1, min(max_lag, n_obs - 1) + 1):
        rho = float(np.dot(centred[:-lag], centred[lag:]) / denominator)
        if rho <= 0.0:
            break
        inflation += 2.0 * rho
    return float(max(n_obs / inflation, 1.0))
