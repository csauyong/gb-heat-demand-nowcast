"""The HDD-plus-calendar baseline. Named, pre-specified, implemented first.

This is baseline 1 of the two `CLAUDE.md` §4 requires, and it is a *strong*
baseline, not a straw man: HDD-plus-calendar regression is what the utility
industry actually uses for national demand, and beating it is the minimum bar
for the bottom-up stock model to be worth building.

Specification
-------------
One ordinary least squares model **per settlement period**. Fitting 48
separate models is how "time of day" enters: the response of demand to a
degree day at 07:00 is not the response at 03:00, and a pooled model would
need a full HDD-by-period interaction to say the same thing less clearly. Each
period's model is::

    demand_p ~ 1 + hdd + dow_1..dow_6 + is_holiday + is_christmas_period
                 + trend + [sin/cos annual harmonics]

* ``hdd`` -- daily heating degree days from the population-weighted GB
  temperature, base 15.5 degC by default.
* ``dow_*`` -- six day-of-week dummies, Monday the reference level.
* ``is_holiday`` -- bank holiday in either GB nation.
* ``is_christmas_period`` -- 24 December to 1 January, a regime the statutory
  holiday flags miss.
* ``trend`` -- years since the start of the training sample. GB demand has
  fallen steadily over the period; without a trend the model tracks the level
  of the early sample.
* annual harmonics -- ``sin``/``cos`` of day-of-year at 1 and 2 cycles per
  year, capturing the seasonality `CLAUDE.md` §4 asks for beyond what HDD
  already explains (daylight, occupancy, non-thermal seasonal load).

Settlement periods 49 and 50 exist only on the autumn clock-change day and
carry a handful of observations a year. They are mapped onto the period-48
model rather than given their own; the alternative is fitting a regression to
five points.

Point-in-time behaviour
-----------------------
The fit uses **realised** (ERA5) HDD and prediction uses **forecast** HDD.
Both halves are legal, for different reasons:

* training rows lie at least one embargo behind the refit date, and the
  embargo (7 days by default) exceeds ERA5's ~5-day preliminary publication
  lag, so the realised temperature used in training had genuinely published by
  the time the model was fit;
* prediction consumes only the archived day-ahead forecast.

The mismatch between the two is a real and disclosed property of this
baseline, not an accident. Its direction is known: fitting on a clean
regressor and predicting with a noisy one is classical errors-in-variables,
which leaves the slope unattenuated and *inflates* prediction error. It
therefore makes the baseline look worse, never better, relative to NESO. The
oracle run measures exactly how much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from heat_nowcast.evaluation.splits import ExpandingWindowSplitter

#: Settlement periods above this are folded onto this period's model.
MAX_MODELLED_PERIOD: Final[int] = 48

DAY_OF_WEEK_COLUMNS: Final[tuple[str, ...]] = (
    "dow_1",
    "dow_2",
    "dow_3",
    "dow_4",
    "dow_5",
    "dow_6",
)


@dataclass
class HddCalendarBaseline:
    """Per-settlement-period OLS of demand on HDD and calendar effects.

    Parameters
    ----------
    annual_harmonics :
        Number of annual Fourier harmonic pairs. 2 is the pre-specified
        headline setting (`CLAUDE.md` §4 requires seasonality); 0 gives the
        stricter HDD + day-of-week + holiday + trend specification and is
        reported as a sensitivity.
    ridge_lambda :
        Small ridge penalty on the non-intercept columns, purely for numerical
        stability when a fold contains no holidays of a given kind and a dummy
        column is constant. Not a tuned hyperparameter -- it is fixed and
        never selected on data.

    Attributes
    ----------
    coefficients_ :
        Fitted coefficient vector per settlement period.
    feature_names_ :
        Design matrix column order, shared across periods.
    trend_origin_ :
        Timestamp from which ``trend`` is measured, fixed at fit time so that
        prediction cannot re-centre the trend on the test window.
    """

    annual_harmonics: int = 2
    ridge_lambda: float = 1e-6
    coefficients_: dict[int, np.ndarray] = field(default_factory=dict)
    feature_names_: list[str] = field(default_factory=list)
    trend_origin_: pd.Timestamp | None = None

    def _design_matrix(
        self,
        frame: pd.DataFrame,
        *,
        hdd_column: str,
    ) -> tuple[np.ndarray, list[str]]:
        """Build the design matrix for one specification.

        Parameters
        ----------
        frame :
            Must carry ``settlement_date``, ``hdd_column``, ``is_holiday_any``
            and ``is_christmas_period``.
        hdd_column :
            Which HDD column to use. This is the single switch between the
            point-in-time run (forecast HDD) and the oracle run (realised
            HDD).
        """
        if self.trend_origin_ is None:
            msg = "trend_origin_ must be set before building a design matrix"
            raise RuntimeError(msg)

        dates = pd.DatetimeIndex(frame["settlement_date"])
        columns: list[np.ndarray] = [np.ones(len(frame))]
        names: list[str] = ["intercept"]

        columns.append(frame[hdd_column].to_numpy(dtype="float64"))
        names.append("hdd")

        day_of_week = dates.dayofweek.to_numpy()
        for offset in range(1, 7):
            columns.append((day_of_week == offset).astype("float64"))
            names.append(f"dow_{offset}")

        columns.append(frame["is_holiday_any"].to_numpy(dtype="float64"))
        names.append("is_holiday")
        columns.append(frame["is_christmas_period"].to_numpy(dtype="float64"))
        names.append("is_christmas_period")

        years_since = (dates - self.trend_origin_).days.to_numpy(
            dtype="float64"
        ) / 365.25
        columns.append(years_since)
        names.append("trend")

        if self.annual_harmonics > 0:
            angle = 2.0 * np.pi * dates.dayofyear.to_numpy(dtype="float64") / 365.25
            for harmonic in range(1, self.annual_harmonics + 1):
                columns.append(np.sin(harmonic * angle))
                names.append(f"sin_{harmonic}")
                columns.append(np.cos(harmonic * angle))
                names.append(f"cos_{harmonic}")

        return np.column_stack(columns), names

    @staticmethod
    def _model_period(settlement_period: pd.Series) -> pd.Series:
        """Fold settlement periods 49-50 onto the period-48 model."""
        return settlement_period.clip(upper=MAX_MODELLED_PERIOD)

    def fit(
        self,
        frame: pd.DataFrame,
        *,
        target_column: str,
        hdd_column: str,
    ) -> HddCalendarBaseline:
        """Fit one OLS model per settlement period.

        Parameters
        ----------
        frame :
            Training rows. Must be strictly earlier than any row this model
            will predict -- the splitter guarantees that, this method does not
            re-check it.
        target_column :
            Demand column to regress.
        hdd_column :
            HDD column to use as the temperature regressor.

        Returns
        -------
        HddCalendarBaseline
            ``self``, fitted.
        """
        self.trend_origin_ = pd.Timestamp(
            pd.DatetimeIndex(frame["settlement_date"]).min()
        )
        working = frame.copy()
        working["model_period"] = self._model_period(working["settlement_period"])

        self.coefficients_ = {}
        self.feature_names_ = []
        for period in sorted(working["model_period"].unique()):
            block = working.loc[working["model_period"] == period]
            usable = block.dropna(subset=[target_column, hdd_column])
            if len(usable) < 10:
                continue
            design, names = self._design_matrix(usable, hdd_column=hdd_column)
            self.feature_names_ = names
            target = usable[target_column].to_numpy(dtype="float64")

            penalty = self.ridge_lambda * np.eye(design.shape[1])
            penalty[0, 0] = 0.0  # never penalise the intercept
            gram = design.T @ design + penalty
            coefficients, *_ = np.linalg.lstsq(gram, design.T @ target, rcond=None)
            self.coefficients_[int(period)] = coefficients
        return self

    def predict(
        self,
        frame: pd.DataFrame,
        *,
        hdd_column: str,
    ) -> pd.Series:
        """Predict demand for each row.

        Parameters
        ----------
        frame :
            Rows to predict. Must carry the same calendar columns as training.
        hdd_column :
            HDD column to consume. For a result reported as a forecast this
            must be the **forecast** HDD column; passing the realised column
            produces an oracle prediction and the caller is responsible for
            labelling it as such (`CLAUDE.md` §2.1).

        Returns
        -------
        pandas.Series
            Predictions, indexed like ``frame``. Rows whose settlement period
            was never fitted, or whose HDD is missing, come back as NaN rather
            than silently falling back to some other period's model.
        """
        if not self.coefficients_:
            msg = "model is not fitted"
            raise RuntimeError(msg)

        working = frame.copy()
        working["model_period"] = self._model_period(working["settlement_period"])
        predictions = pd.Series(np.nan, index=frame.index, dtype="float64")

        for period in sorted(working["model_period"].unique()):
            block = working.loc[working["model_period"] == period]
            coefficients = self.coefficients_.get(int(period))
            if coefficients is None:
                continue
            usable = block.dropna(subset=[hdd_column])
            if len(usable) == 0:
                continue
            design, _ = self._design_matrix(usable, hdd_column=hdd_column)
            predictions.loc[usable.index] = design @ coefficients
        return predictions


def walk_forward_predict(
    frame: pd.DataFrame,
    splitter: ExpandingWindowSplitter,
    *,
    target_column: str,
    fit_hdd_column: str,
    predict_hdd_column: str,
    annual_harmonics: int = 2,
    time_column: str = "settlement_datetime",
) -> tuple[pd.Series, pd.DataFrame]:
    """Run expanding-window walk-forward prediction over the whole frame.

    The model is refit once per fold on all history up to that fold's cut,
    then applied to that fold's test window. Rows never appearing in any test
    window come back NaN -- notably the initial training period, which is
    correct: it has no out-of-sample prediction.

    Parameters
    ----------
    frame :
        Full panel, one row per settlement period.
    splitter :
        Configured :class:`ExpandingWindowSplitter`.
    target_column :
        Demand column to predict.
    fit_hdd_column :
        HDD column used to **fit**. Realised HDD is legal here because the
        embargo exceeds ERA5's publication lag.
    predict_hdd_column :
        HDD column used to **predict**. Must be a forecast column for any
        result reported as a forecast.
    annual_harmonics :
        Passed to :class:`HddCalendarBaseline`.
    time_column :
        Column holding the timestamps the splitter orders on.

    Returns
    -------
    predictions : pandas.Series
        Out-of-sample predictions aligned to ``frame``.
    fold_summary : pandas.DataFrame
        One row per fold recording train/test bounds and sizes, so the walk
        can be audited without re-running it.
    """
    # Accumulate into a plain array rather than assigning into a Series by
    # position: the fold indices are positional, and under copy-on-write a
    # positional write into a Series is easy to get subtly wrong. The Series
    # is built once, at the end, from an array whose order matches `frame`.
    values = np.full(len(frame), np.nan, dtype="float64")
    records: list[dict[str, object]] = []

    for fold in splitter.split(frame[time_column]):
        train = frame.iloc[fold.train_index]
        test = frame.iloc[fold.test_index]

        model = HddCalendarBaseline(annual_harmonics=annual_harmonics)
        model.fit(train, target_column=target_column, hdd_column=fit_hdd_column)
        fold_predictions = model.predict(test, hdd_column=predict_hdd_column)
        values[fold.test_index] = fold_predictions.to_numpy()

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
                "periods_fitted": len(model.coefficients_),
            }
        )

    predictions = pd.Series(values, index=frame.index, dtype="float64")
    return predictions, pd.DataFrame(records)


def seasonal_naive_forecast(
    frame: pd.DataFrame,
    *,
    target_column: str,
    time_column: str = "settlement_datetime",
    lag_days: int = 7,
) -> pd.Series:
    """Lag-7-day persistence: last week's demand at the same settlement period.

    The floor beneath the HDD baseline. It uses no weather at all, so it
    answers the question "how much of the HDD baseline's skill comes from
    weather rather than from demand simply repeating weekly?". A seven-day lag
    is used rather than one day because it preserves the day-of-week profile.

    Point-in-time note: a 7-day lag clears both NESO's ~1-day outturn
    publication lag and the day-ahead decision point, so this forecast is
    genuinely knowable at the time.
    """
    working = frame[[time_column, "settlement_period", target_column]].copy()
    working["lookup_time"] = pd.DatetimeIndex(working[time_column]) - pd.Timedelta(
        days=lag_days
    )
    lookup = working.set_index(time_column)[target_column]
    return pd.Series(
        lookup.reindex(working["lookup_time"]).to_numpy(),
        index=frame.index,
        dtype="float64",
    )
