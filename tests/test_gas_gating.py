"""Point-in-time gating tests for the repeatedly-revised gas series.

The trap these guard against is specific and severe: `Demand Forecast, LDZ`
republishes ~8 times per gas day, and the portal's default returns the
publication generated at 00:15 on **D+1** -- after the gas day has ended.
Scoring that as a day-ahead forecast would make the incumbent look far better
than it is, and would be invisible in the output.

Tests marked ``pointintime`` are never skipped (``pyproject.toml``).
"""

from __future__ import annotations

import pandas as pd
import pytest

from heat_nowcast.data.gas import (
    LDZ_CODES,
    PUBLICATION_OBJECTS,
    ForecastGate,
    select_publication_at_gate,
)


def publication_history() -> pd.DataFrame:
    """The real publication pattern for one gas day, in one LDZ.

    Times taken from the actual series for gas day 2025-01-15: two
    publications on D-1, five during D, and one on D+1.
    """
    gas_day = pd.Timestamp("2025-01-15")
    stamps = [
        ("2025-01-14 13:15:00", 16.10),  # D-1 first
        ("2025-01-14 16:15:00", 15.80),  # D-1 last  <- the day-ahead forecast
        ("2025-01-15 00:15:00", 15.95),  # D, before the 05:00 UTC gas-day start
        ("2025-01-15 10:15:00", 14.90),  # D, within-day -- LEAK if used
        ("2025-01-15 13:15:00", 14.90),
        ("2025-01-15 16:15:00", 15.00),
        ("2025-01-15 21:15:00", 15.30),
        ("2025-01-16 00:15:00", 15.35),  # D+1 -- what latestFlag=Y returns
    ]
    return pd.DataFrame(
        {
            "gas_day": [gas_day] * len(stamps),
            "ldz": ["EA"] * len(stamps),
            "generated_at": [pd.Timestamp(t) for t, _ in stamps],
            "value": [v for _, v in stamps],
        }
    )


# --------------------------------------------------------------------------
# the leakage assertions
# --------------------------------------------------------------------------


@pytest.mark.pointintime
def test_default_gate_never_uses_a_publication_from_the_gas_day_or_later():
    """The headline invariant for the gas side."""
    history = publication_history()
    selected = select_publication_at_gate(history, gate=ForecastGate.LAST_ON_D_MINUS_1)

    assert len(selected) == 1
    chosen = selected.iloc[0]
    assert chosen["generated_at"] < chosen["gas_day"], (
        f"leak: selected a publication generated {chosen['generated_at']} "
        f"for gas day {chosen['gas_day']}"
    )
    assert chosen["value"] == pytest.approx(15.80)


@pytest.mark.pointintime
def test_default_gate_rejects_the_portal_default_publication():
    """`latestFlag=Y` returns the D+1 value; the gate must never pick it."""
    history = publication_history()
    portal_default = history.sort_values("generated_at").iloc[-1]
    assert portal_default["value"] == pytest.approx(15.35)

    selected = select_publication_at_gate(history, gate=ForecastGate.LAST_ON_D_MINUS_1)
    assert selected.iloc[0]["value"] != pytest.approx(portal_default["value"])


@pytest.mark.pointintime
def test_every_gate_excludes_within_day_publications():
    """No gate may admit a publication issued after the gas day opened."""
    history = publication_history()
    gas_day_start = pd.Timestamp("2025-01-15 05:00:00")
    for gate in ForecastGate:
        selected = select_publication_at_gate(history, gate=gate)
        assert (selected["generated_at"] < gas_day_start).all(), (
            f"gate {gate.value} admitted a publication at or after the "
            f"05:00 gas-day start"
        )


@pytest.mark.pointintime
def test_gas_day_start_gate_admits_only_the_pre_0500_publication():
    """`LAST_BEFORE_GAS_DAY` may use 00:15 on D but nothing later."""
    history = publication_history()
    selected = select_publication_at_gate(
        history, gate=ForecastGate.LAST_BEFORE_GAS_DAY
    )
    assert selected.iloc[0]["value"] == pytest.approx(15.95)
    assert selected.iloc[0]["generated_at"] == pd.Timestamp("2025-01-15 00:15:00")


@pytest.mark.pointintime
def test_first_on_d_minus_1_is_the_most_conservative():
    history = publication_history()
    first = select_publication_at_gate(history, gate=ForecastGate.FIRST_ON_D_MINUS_1)
    last = select_publication_at_gate(history, gate=ForecastGate.LAST_ON_D_MINUS_1)
    assert first.iloc[0]["generated_at"] < last.iloc[0]["generated_at"]
    assert first.iloc[0]["value"] == pytest.approx(16.10)


@pytest.mark.pointintime
def test_gas_day_with_no_eligible_publication_is_dropped_not_backfilled():
    """A day whose only publications land after the gate must disappear.

    Back-filling from a later publication would silently reintroduce the leak
    on exactly the days where the incumbent revised late.
    """
    history = publication_history()
    late_only = history[history["generated_at"] >= pd.Timestamp("2025-01-15 10:00:00")]
    with pytest.raises(ValueError, match="no publications satisfy gate"):
        select_publication_at_gate(late_only, gate=ForecastGate.LAST_ON_D_MINUS_1)


@pytest.mark.pointintime
def test_gating_is_applied_per_ldz_independently():
    """One zone's late revision must not select another zone's row."""
    base = publication_history()
    other = base.copy()
    other["ldz"] = "SC"
    other["value"] = other["value"] + 100.0
    combined = pd.concat([base, other], ignore_index=True)

    selected = select_publication_at_gate(
        combined, gate=ForecastGate.LAST_ON_D_MINUS_1
    ).set_index("ldz")
    assert len(selected) == 2
    assert selected.loc["EA", "value"] == pytest.approx(15.80)
    assert selected.loc["SC", "value"] == pytest.approx(115.80)


def test_selection_keeps_one_row_per_gas_day_and_ldz():
    days = []
    for offset in range(5):
        block = publication_history()
        block["gas_day"] = block["gas_day"] + pd.Timedelta(days=offset)
        block["generated_at"] = block["generated_at"] + pd.Timedelta(days=offset)
        days.append(block)
    history = pd.concat(days, ignore_index=True)

    selected = select_publication_at_gate(history, gate=ForecastGate.LAST_ON_D_MINUS_1)
    assert len(selected) == 5
    assert selected.duplicated(["gas_day", "ldz"]).sum() == 0


# --------------------------------------------------------------------------
# catalogue integrity
# --------------------------------------------------------------------------


def test_all_thirteen_ldz_present_in_every_series():
    """A missing zone would silently change every fixed effect in the panel."""
    assert len(LDZ_CODES) == 13
    for series, mapping in PUBLICATION_OBJECTS.items():
        assert set(mapping) == set(LDZ_CODES), f"{series} does not cover all 13 LDZs"


def test_publication_object_ids_are_unique_across_series():
    seen: dict[str, str] = {}
    for series, mapping in PUBLICATION_OBJECTS.items():
        for ldz, object_id in mapping.items():
            assert object_id not in seen, (
                f"{object_id} appears in both {seen.get(object_id)} and {series}/{ldz}"
            )
            seen[object_id] = f"{series}/{ldz}"
