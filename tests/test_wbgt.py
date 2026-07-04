"""
Tests for scripts/wbgt.py -- the Stull wet-bulb formula and NIOSH
RAL/REL threshold functions.
"""

from datetime import datetime

import pytest

from wbgt import (
    wet_bulb_stull, estimated_wbgt, niosh_ral_c, niosh_rel_c,
    METABOLIC_RATE_W,
)


def test_wet_bulb_equals_dry_bulb_at_saturation():
    """At RH=100%, wet-bulb should equal dry-bulb (saturated air can't cool
    further by evaporation). Stull's formula is empirical, not exact, so
    allow a small tolerance -- this is a physical sanity check, not a
    numeric regression against the paper."""
    for t in [20.0, 30.0, 40.0]:
        tw = wet_bulb_stull(t, 99.0)  # 99, not 100 -- Stull's stated upper RH bound
        assert tw == pytest.approx(t, abs=0.5), f"T={t}: Tw={tw}"


def test_wet_bulb_below_dry_bulb_at_lower_humidity():
    """Wet-bulb must be <= dry-bulb whenever RH < 100%."""
    for t in [20.0, 30.0, 40.0]:
        for rh in [10.0, 30.0, 50.0, 70.0, 90.0]:
            tw = wet_bulb_stull(t, rh)
            assert tw <= t + 1e-6, f"T={t} RH={rh}: Tw={tw} exceeds T"


def test_wet_bulb_monotonic_in_humidity():
    """Wet-bulb should increase monotonically with RH, all else equal."""
    t = 32.0
    values = [wet_bulb_stull(t, rh) for rh in [10, 30, 50, 70, 90, 99]]
    for earlier, later in zip(values, values[1:]):
        assert later >= earlier - 1e-9


def test_niosh_rel_exceeds_ral_at_same_workload():
    """Acclimatized workers (REL) should tolerate a higher WBGT than
    unacclimatized workers (RAL) at the same workload."""
    for label, m in METABOLIC_RATE_W.items():
        rel = niosh_rel_c(m)
        ral = niosh_ral_c(m)
        assert rel > ral, f"{label}: REL={rel:.1f} should exceed RAL={ral:.1f}"


def test_niosh_moderate_workload_matches_documented_worked_example():
    """
    NIOSH 2016-106 p.35 works this exact example: a 70kg acclimatized
    worker at moderate workload (300 kcal/h = 348.9W, continuous 60 min/h)
    has their REL curve at a WBGT of 27.8C (82F); the unacclimatized RAL
    is at 25C (77F). The document itself derives these two figures by
    reading them off Figures 8-1/8-2 (charts of the same equations we use
    here), not by evaluating the equation directly -- so agreement within
    about 1C confirms we're on the right curve, not a mismatch. Evaluating
    NIOSH's own stated equation directly (as this module does) gives a more
    precise value than their rounded chart-reading example.
    """
    m = METABOLIC_RATE_W["moderate"]
    assert niosh_rel_c(m) == pytest.approx(27.8, abs=0.5)
    assert niosh_ral_c(m) == pytest.approx(25.0, abs=1.0)


def test_niosh_thresholds_decrease_with_higher_workload():
    """Heavier work should tolerate a lower WBGT before hitting the limit."""
    assert niosh_rel_c(METABOLIC_RATE_W["heavy"]) < niosh_rel_c(METABOLIC_RATE_W["moderate"])
    assert niosh_rel_c(METABOLIC_RATE_W["moderate"]) < niosh_rel_c(METABOLIC_RATE_W["light"])


def test_estimated_wbgt_wraps_liljegren_with_hourly_averaging():
    """Smoke test that the wrapper runs end-to-end and returns a plausible
    daytime WBGT for a hot, humid, sunny scenario."""
    result = estimated_wbgt(
        datetime(2026, 7, 4, 13, 0), lat=13.08, lon=80.27,
        solar_wm2=850.0, pressure_hpa=1005.0, tair_c=35.0, rh_pct=70.0,
        wind_speed_ms=3.0, wind_speed_height_m=10.0,
    )
    assert result["status"] == 0
    assert 25.0 < result["Twbg"] < 40.0


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
