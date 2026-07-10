"""
Tests for scripts/compute_trends.py's aggregation -- the per-year counting
that feeds the trend chart. Uses synthetic hourly blocks with conditions
extreme enough that the solver's classification is unambiguous, plus
invariant checks, so the tests don't hardcode solver internals.
"""

from compute_trends import (
    SKIP_BELOW_TA_C,
    aggregate_hours,
    year_blocks,
)
from wbgt import niosh_rel_c

LAT, LON = 25.3176, 82.9739  # Varanasi

HOT = dict(temp=43.0, rh=55.0, solar=850.0, wind=1.0, pressure=1000.0)   # unambiguously over every REL
COLD = dict(temp=10.0, rh=50.0, solar=0.0, wind=2.0, pressure=1000.0)    # under the solver-skip bound


def block(rows):
    """rows: list of (time_ist, cond_dict_or_None). Builds the API 'hourly' shape."""
    h = {"time": [], "temperature_2m": [], "relative_humidity_2m": [],
         "shortwave_radiation": [], "wind_speed_10m": [], "surface_pressure": []}
    for t, c in rows:
        h["time"].append(t)
        if c is None:
            h["temperature_2m"].append(None); h["relative_humidity_2m"].append(50.0)
            h["shortwave_radiation"].append(0.0); h["wind_speed_10m"].append(1.0)
            h["surface_pressure"].append(1000.0)
        else:
            h["temperature_2m"].append(c["temp"]); h["relative_humidity_2m"].append(c["rh"])
            h["shortwave_radiation"].append(c["solar"]); h["wind_speed_10m"].append(c["wind"])
            h["surface_pressure"].append(c["pressure"])
    return h


def test_hot_shoulder_hour_counts_as_overlooked():
    years = aggregate_hours(block([("2000-05-15T09:00", HOT)]), LAT, LON)
    y = years[2000]
    assert y["valid"] == 1 and y["skipped_cold"] == 0
    for key in ("light", "moderate", "heavy", "very-high"):
        assert y[key]["ovl"] == 1, key
        assert y[key]["stress"] == 1, key
        assert y[key]["days"] == 1, key


def test_window_boundary_semantics_match_frontend():
    # 11:00 is INSIDE the avoidance window (inclusive start): stress, not ovl.
    # 17:00 is OUTSIDE (exclusive end): ovl -- must match isInsideHapWindow.
    years = aggregate_hours(block([
        ("2000-05-15T11:00", HOT),
        ("2000-05-15T17:00", HOT),
    ]), LAT, LON)
    y = years[2000]["heavy"]
    assert y["stress"] == 2
    assert y["ovl"] == 1


def test_night_heat_is_stress_but_never_overlooked():
    hot_night = dict(HOT, solar=0.0)
    years = aggregate_hours(block([("2000-05-15T23:00", hot_night)]), LAT, LON)
    y = years[2000]["heavy"]
    assert y["stress"] == 1
    assert y["ovl"] == 0 and y["days"] == 0


def test_cold_hours_skip_solver_but_stay_valid():
    years = aggregate_hours(block([("2000-01-15T05:00", COLD)]), LAT, LON)
    y = years[2000]
    assert y["valid"] == 1 and y["skipped_cold"] == 1
    assert y.get("heavy", {"ovl": 0})["ovl"] == 0


def test_gap_hours_are_dropped_not_fabricated():
    years = aggregate_hours(block([("2000-05-15T09:00", None)]), LAT, LON)
    assert 2000 not in years or years[2000]["valid"] == 0


def test_sensitivity_band_invariant_and_days_dedupe():
    rows = [
        ("2001-05-15T08:00", HOT), ("2001-05-15T09:00", HOT),   # same day, 2 ovl hours
        ("2001-05-16T18:00", HOT),                              # second day
    ]
    years = aggregate_hours(block(rows), LAT, LON)
    y = years[2001]["heavy"]
    assert y["ovl"] == 3 and y["days"] == 2
    # looser limit can only add hours; stricter can only remove them
    assert y["ovl_lo"] >= y["ovl"] >= y["ovl_hi"]


def test_year_blocks_cover_range_exactly_once():
    blocks = year_blocks()
    covered = [y for (a, b) in blocks for y in range(a, b + 1)]
    assert covered == list(range(1980, 2025))


def test_skip_bound_is_below_every_threshold():
    lowest = min(niosh_rel_c(w) for w in (209.0, 349.0, 465.0, 581.0)) - 1.0
    assert SKIP_BELOW_TA_C + 7.0 < lowest
