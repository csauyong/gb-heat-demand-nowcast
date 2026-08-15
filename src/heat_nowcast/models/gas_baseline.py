"""Per-LDZ CWV baseline for daily gas offtake. The gas analogue of Phase 1.

Specification
-------------
One ordinary least squares model **per Local Distribution Zone**, on daily
data::

    demand_ldz ~ 1 + cwv + dow_1..dow_6 + is_holiday + is_christmas_period
                   + trend + sin/cos annual harmonics (2 pairs)

This is deliberately the specification that won Phase 1 -- same calendar terms,
same two annual harmonics, same walk-forward machinery -- with the Composite
Weather Variable substituting for heating degree days. Keeping the form fixed
is what makes the electricity and gas results comparable; changing it would
confound "gas is different" with "the model is different".

Why CWV rather than HDD
-----------------------
The CWV is the gas industry's own weather variable, constructed per LDZ to be
**linear in gas demand** (``docs/data_inventory.md`` §4). It is also the
incumbent forecaster's own input, so using it puts the baseline and the
competitor on the same weather footing -- the reverse of Phase 1, where the
baseline's coarse free NWP was a known handicap. Raw HDD is reported alongside
it rather than substituted for it, per the Phase 1b brief.

Two ways this is cleaner than Phase 1
-------------------------------------
1. **No train/serve mismatch.** Phase 1 had to fit on realised ERA5 HDD and
   serve archived forecast HDD, because point-in-time forecast weather only
   existed from 2024-02-04. Here the *forecast* CWV is published for the whole
   history, so the model is fitted and served on the identical feature. The
   errors-in-variables caveat that qualified every Phase 1 number simply does
   not arise.
2. **A real vintage pair.** LDZ demand actuals publish at D+1 and again,
   reconciled, at D+6. ``CLAUDE.md`` §2.2 asks for vintage discipline; on the
   electricity side it could only be acknowledged, here it can be measured.

Per-LDZ rather than pooled
--------------------------
Fitting 13 separate models lets each zone have its own CWV slope, intercept and
trend, which is the honest way to handle zones that differ by a factor of three
in size and in heating load. It also means the baseline cannot borrow strength
across zones -- important, because the Phase 1b core test asks whether
*cross-sectional* stock differences carry information, and a baseline that
already pooled them would muddy the question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.evaluation.splits import ExpandingWindowSplitter

DEFAULT_ANNUAL_HARMONICS: Final[int] = 2


@dataclass
class CwvCalendarBaseline:
    """Per-LDZ OLS of daily gas offtake on CWV and calendar effects.

    Parameters
    ----------
    annual_harmonics :
        Number of annual Fourier harmonic pairs. 2 is the pre-specified
        headline setting, matching the Phase 1 winner.
    ridge_lambda :
        Small ridge penalty on non-intercept columns for numerical stability
        when a fold contains no holidays of a given kind. Fixed, never tuned.

    Attributes
    ----------
    coefficients_ :
        Fitted coefficient vector per LDZ.
    feature_names_ :
        Design matrix column order.
    trend_origin_ :
        Timestamp the trend is measured from, fixed at fit time so prediction
        cannot re-centre it on the test window.
    """

    annual_harmonics: int = DEFAULT_ANNUAL_HARMONICS
    ridge_lambda: float = 1e-6
    coefficients_: dict[str, np.ndarray] = field(default_factory=dict)
    feature_names_: list[str] = field(default_factory=list)
    trend_origin_: pd.Timestamp | None = None

    def _design_matrix(
        self,
        frame: pd.DataFrame,
        *,
        weather_column: str,
    ) -> tuple[np.ndarray, list[str]]:
        """Build the design matrix.

        Parameters
        ----------
        frame :
            Must carry ``gas_day``, ``weather_column``, ``is_holiday_any`` and
            ``is_christmas_period``.
        weather_column :
            The single switch between the point-in-time run (``cwv_forecast``)
            and the oracle run (``cwv_actual_realised``).
        """
        if self.trend_origin_ is None:
            msg = "trend_origin_ must be set before building a design matrix"
            raise RuntimeError(msg)

        days = pd.DatetimeIndex(frame["gas_day"])
        columns: list[np.ndarray] = [np.ones(len(frame))]
        names: list[str] = ["intercept"]

        columns.append(frame[weather_column].to_numpy(dtype="float64"))
        names.append("cwv")

        day_of_week = days.dayofweek.to_numpy()
        for offset in range(1, 7):
            columns.append((day_of_week == offset).astype("float64"))
            names.append(f"dow_{offset}")

        columns.append(frame["is_holiday_any"].to_numpy(dtype="float64"))
        names.append("is_holiday")
        columns.append(frame["is_christmas_period"].to_numpy(dtype="float64"))
        names.append("is_christmas_period")

        years_since = (days - self.trend_origin_).days.to_numpy(
            dtype="float64"
        ) / 365.25
        columns.append(years_since)
        names.append("trend")

        if self.annual_harmonics > 0:
            angle = 2.0 * np.pi * days.dayofyear.to_numpy(dtype="float64") / 365.25
            for harmonic in range(1, self.annual_harmonics + 1):
                columns.append(np.sin(harmonic * angle))
                names.append(f"sin_{harmonic}")
                columns.append(np.cos(harmonic * angle))
                names.append(f"cos_{harmonic}")

        return np.column_stack(columns), names

    def fit(
        self,
        frame: pd.DataFrame,
        *,
        target_column: str,
        weather_column: str,
    ) -> CwvCalendarBaseline:
        """Fit one OLS model per LDZ.

        Training rows must be strictly earlier than any row this model will
        predict; the splitter guarantees that and this method does not re-check.
        """
        self.trend_origin_ = pd.Timestamp(pd.DatetimeIndex(frame["gas_day"]).min())
        self.coefficients_ = {}
        self.feature_names_ = []

        for ldz in sorted(frame["ldz"].unique()):
            block = frame.loc[frame["ldz"] == ldz]
            usable = block.dropna(subset=[target_column, weather_column])
            if len(usable) < 30:
                continue
            design, names = self._design_matrix(usable, weather_column=weather_column)
            self.feature_names_ = names
            target = usable[target_column].to_numpy(dtype="float64")

            penalty = self.ridge_lambda * np.eye(design.shape[1])
            penalty[0, 0] = 0.0
            gram = design.T @ design + penalty
            coefficients, *_ = np.linalg.lstsq(gram, design.T @ target, rcond=None)
            self.coefficients_[str(ldz)] = coefficients
        return self

    def predict(
        self,
        frame: pd.DataFrame,
        *,
        weather_column: str,
    ) -> pd.Series:
        """Predict daily offtake per LDZ.

        Rows whose LDZ was never fitted, or whose weather value is missing,
        come back NaN rather than borrowing another zone's model.
        """
        if not self.coefficients_:
            msg = "model is not fitted"
            raise RuntimeError(msg)

        predictions = pd.Series(np.nan, index=frame.index, dtype="float64")
        for ldz in sorted(frame["ldz"].unique()):
            coefficients = self.coefficients_.get(str(ldz))
            if coefficients is None:
                continue
            block = frame.loc[frame["ldz"] == ldz].dropna(subset=[weather_column])
            if len(block) == 0:
                continue
            design, _ = self._design_matrix(block, weather_column=weather_column)
            predictions.loc[block.index] = design @ coefficients
        return predictions


def walk_forward_predict_gas(
    frame: pd.DataFrame,
    splitter: ExpandingWindowSplitter,
    *,
    target_column: str,
    fit_weather_column: str,
    predict_weather_column: str,
    annual_harmonics: int = DEFAULT_ANNUAL_HARMONICS,
    time_column: str = "gas_day_utc",
) -> tuple[pd.Series, pd.DataFrame]:
    """Expanding-window walk-forward over the LDZ x day panel.

    The splitter cuts on time only; every LDZ shares the same fold boundaries,
    so a fold's training set is the full cross-section up to the cut. That is
    what makes the panel balanced within each fold.

    Returns
    -------
    predictions : pandas.Series
        Out-of-sample predictions aligned to ``frame``. Rows before the first
        test window are NaN -- they have no out-of-sample prediction.
    fold_summary : pandas.DataFrame
        One row per fold, so the walk can be audited without re-running it.
    """
    values = np.full(len(frame), np.nan, dtype="float64")
    records: list[dict[str, object]] = []

    for fold in splitter.split(frame[time_column]):
        train = frame.iloc[fold.train_index]
        test = frame.iloc[fold.test_index]

        model = CwvCalendarBaseline(annual_harmonics=annual_harmonics)
        model.fit(train, target_column=target_column, weather_column=fit_weather_column)
        # A fold can legitimately fit nothing: the national-HDD comparator has
        # no point-in-time feature before 2024-02-04, so its early folds have
        # no usable training rows. Leaving those predictions NaN is the honest
        # outcome -- the specification has no forecast there, and it must not
        # borrow one from a later fold.
        if model.coefficients_:
            values[fold.test_index] = model.predict(
                test, weather_column=predict_weather_column
            ).to_numpy()

        records.append(
            {
                "fold": fold.fold_index,
                "train_rows": len(train),
                "train_start": pd.Timestamp(train[time_column].min()),
                "train_end": fold.train_end,
                "embargo_end": fold.embargo_end,
                "test_start": fold.test_start,
                "test_end": fold.test_end,
                "test_rows": len(test),
                "ldz_fitted": len(model.coefficients_),
            }
        )

    predictions = pd.Series(values, index=frame.index, dtype="float64")
    return predictions, pd.DataFrame(records)


def seasonal_naive_gas(
    frame: pd.DataFrame,
    *,
    target_column: str,
    lag_days: int = 7,
) -> pd.Series:
    """Lag-7-day persistence per LDZ: last week's offtake, same weekday.

    The no-weather floor. A 7-day lag preserves the day-of-week profile and
    clears the D+1 publication lag of the outturn, so it is genuinely knowable
    at a day-ahead decision.
    """
    working = frame[["gas_day", "ldz", target_column]].copy()
    working["lookup_day"] = pd.DatetimeIndex(working["gas_day"]) - pd.Timedelta(
        days=lag_days
    )
    lookup = working.set_index(["gas_day", "ldz"])[target_column]
    index = pd.MultiIndex.from_arrays(
        [working["lookup_day"], working["ldz"]], names=["gas_day", "ldz"]
    )
    return pd.Series(
        lookup.reindex(index).to_numpy(), index=frame.index, dtype="float64"
    )
