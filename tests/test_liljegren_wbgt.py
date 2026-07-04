"""
Sanity-check tests for the Liljegren WBGT Python port (liljegren_wbgt.py).

These are NOT a numerical validation against the original C binary (we
cannot compile/run the C code in this environment). Instead they check
physically-required properties that a gross transcription bug (sign flip,
wrong exponent, degrees/radians mixup, wrong combining weights, etc.) would
very likely violate. Do not loosen these assertions to make them pass --
if one fails, treat it as a signal to go find the transcription bug.
"""

import math
from datetime import datetime, timezone

import pytest

from liljegren_wbgt import calc_wbgt, Tglobe, Twb


# A location near Delhi, India, for realistic heat-risk scenarios.
LAT, LON = 28.6, 77.2
PRES_HPA = 1000.0


def _midday_utc(month=5, day=15):
    # Delhi is UTC+5:30; ~12:30 local noon is ~07:00 UTC.
    return datetime(2024, month, day, 7, 0, tzinfo=timezone.utc)


def _midnight_utc(month=5, day=15):
    # ~01:00 local time is ~19:30 UTC the previous day; use 19:00 UTC.
    return datetime(2024, month, day, 19, 0, tzinfo=timezone.utc)


def test_sunny_midday_globe_temp_exceeds_air_temp():
    """Strong solar radiation should radiantly heat the globe well above Tair."""
    tair_c = 38.0
    result = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=950.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=30.0, wind_speed_ms=1.5,
    )
    assert result["status"] == 0
    assert result["Tg"] > tair_c + 3.0, (
        f"Expected strong radiant heating of the globe at midday sun, "
        f"got Tg={result['Tg']:.2f} vs Tair={tair_c}"
    )


def test_night_globe_temp_close_to_air_temp():
    """With zero solar radiation, Tg should be close to Tair (no radiant heating)."""
    tair_c = 28.0
    result = calc_wbgt(
        _midnight_utc(), LAT, LON,
        solar_wm2=0.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=60.0, wind_speed_ms=1.5,
    )
    assert result["status"] == 0
    assert abs(result["Tg"] - tair_c) < 1.5, (
        f"Expected Tg close to Tair at night, got Tg={result['Tg']:.2f} "
        f"vs Tair={tair_c}"
    )


@pytest.mark.parametrize("rh", [20.0, 50.0, 80.0, 100.0])
def test_psychrometric_wet_bulb_at_or_below_air_temp(rh):
    """
    Tpsy (psychrometric wet bulb, rad=False i.e. no radiative heating term)
    should never exceed Tair -- with radiation disabled, evaporative
    cooling can only cool, never warm, the wick.

    Note: we check Tpsy rather than Tnwb here. Tnwb (natural wet bulb,
    rad=True) includes the Fatm/h radiative-heating term in wbgt.c's Twb()
    even when RH=100%, so under strong sun Tnwb can legitimately exceed
    Tair by a degree or so (verified against the C logic: Twb_new = Tair -
    evap(...)*(...)  + Fatm/h*rad, and at RH=100% the evaporative term
    vanishes but the +Fatm/h term remains). That is expected physical
    behavior, not a transcription bug, so the "never exceeds Tair" check
    belongs on Tpsy (rad=0), which strictly isolates evaporative cooling.
    """
    tair_c = 35.0
    result = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=800.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=rh, wind_speed_ms=2.0,
    )
    assert result["status"] == 0
    assert result["Tpsy"] <= tair_c + 1e-6, (
        f"Tpsy ({result['Tpsy']:.2f}) exceeded Tair ({tair_c}) at RH={rh}%"
    )


def test_natural_wet_bulb_increases_with_humidity():
    """Tnwb should monotonically increase toward Tair as RH increases (at
    night / zero solar, so the radiative-heating term does not confound
    the comparison -- see note in test_psychrometric_wet_bulb_at_or_below_air_temp
    for why Tnwb alone, under strong sun, is not guaranteed to be <= Tair)."""
    tair_c = 35.0
    tnwb_values = []
    for rh in [20.0, 40.0, 60.0, 80.0, 100.0]:
        result = calc_wbgt(
            _midnight_utc(), LAT, LON,
            solar_wm2=0.0, pressure_hpa=PRES_HPA,
            tair_c=tair_c, rh_pct=rh, wind_speed_ms=2.0,
        )
        assert result["status"] == 0
        tnwb_values.append(result["Tnwb"])

    for earlier, later in zip(tnwb_values, tnwb_values[1:]):
        assert later >= earlier - 1e-6, f"Tnwb not monotonic in RH: {tnwb_values}"

    # At RH=100%, Tnwb should be very close to Tair (no evaporative cooling
    # possible when the air is already saturated, and no solar term at night).
    assert abs(tnwb_values[-1] - tair_c) < 1.0, (
        f"Expected Tnwb close to Tair at RH=100%, got Tnwb={tnwb_values[-1]:.2f} "
        f"vs Tair={tair_c}"
    )


def test_twbg_between_tnwb_and_tg():
    """
    Twbg is a weighted average of Tnwb, Tg, and Tair with weights
    0.7/0.2/0.1 respectively (largest weight on Tnwb), so Twbg should fall
    within [Tnwb, Tg] (Tnwb <= Tair <= Tg is the typical ordering for a
    sunny daytime case, and the weighted sum must lie between the min and
    max of its inputs).
    """
    tair_c = 38.0
    result = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=900.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=40.0, wind_speed_ms=1.5,
    )
    assert result["status"] == 0
    lo = min(result["Tnwb"], result["Tg"], tair_c)
    hi = max(result["Tnwb"], result["Tg"], tair_c)
    assert lo - 1e-6 <= result["Twbg"] <= hi + 1e-6, (
        f"Twbg={result['Twbg']:.2f} not within [{lo:.2f}, {hi:.2f}] "
        f"(Tnwb={result['Tnwb']:.2f}, Tg={result['Tg']:.2f}, Tair={tair_c})"
    )
    # More specifically, Twbg should sit closer to Tnwb than to Tg, since
    # Tnwb carries the largest weight (0.7 vs 0.2).
    assert abs(result["Twbg"] - result["Tnwb"]) < abs(result["Twbg"] - result["Tg"])


def test_twbg_combining_formula_matches_iso7243_weights():
    """
    Directly verify the combining formula implemented in _calc_wbgt matches
    what's in wbgt.c:  Twbg = 0.1*Tair + 0.2*Tg + 0.7*Tnwb.
    We check this by reconstructing Twbg from the independently-returned
    Tg/Tnwb/Tair and comparing to the returned Twbg.
    """
    tair_c = 33.0
    result = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=700.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=45.0, wind_speed_ms=2.5,
    )
    assert result["status"] == 0
    expected_twbg = 0.1 * tair_c + 0.2 * result["Tg"] + 0.7 * result["Tnwb"]
    assert result["Twbg"] == pytest.approx(expected_twbg, abs=1e-9)


def test_high_wind_reduces_globe_solar_heating():
    """Higher wind speed should increase convective cooling of the globe,
    reducing Tg relative to Tair, all else equal."""
    tair_c = 38.0
    low_wind = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=900.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=30.0, wind_speed_ms=0.5,
    )
    high_wind = calc_wbgt(
        _midday_utc(), LAT, LON,
        solar_wm2=900.0, pressure_hpa=PRES_HPA,
        tair_c=tair_c, rh_pct=30.0, wind_speed_ms=8.0,
    )
    assert low_wind["status"] == 0 and high_wind["status"] == 0
    assert high_wind["Tg"] < low_wind["Tg"], (
        f"Expected higher wind to cool the globe more: "
        f"low_wind Tg={low_wind['Tg']:.2f}, high_wind Tg={high_wind['Tg']:.2f}"
    )


def test_direct_tglobe_and_twb_low_level_functions():
    """Spot-check the lower-level Tglobe/Twb functions directly (in Kelvin,
    fraction RH), independent of the calc_wbgt wrapper's unit conversions."""
    tair_k = 313.15  # 40 degC
    rh = 0.3
    pres = 1000.0
    speed = 1.5
    solar = 900.0
    fdir = 0.8
    cza = 0.8  # sun nearly overhead

    tg = Tglobe(tair_k, rh, pres, speed, solar, fdir, cza)
    assert tg != -9999.0, "Tglobe failed to converge"
    assert tg > (tair_k - 273.15), "Tglobe should exceed Tair under strong sun"

    tnwb = Twb(tair_k, rh, pres, speed, solar, fdir, cza, True)
    assert tnwb != -9999.0, "Twb (natural) failed to converge"
    assert tnwb <= (tair_k - 273.15) + 1e-6


def test_matches_compiled_reference_c_implementation_daytime():
    """
    Regression test against ground truth: Liljegren's original wbgt.c.original
    (with its demo main()) was compiled with gcc and run directly on this
    exact input. This is a genuine cross-check against the reference C
    implementation, not just a physical-plausibility check.

    Reference run (Chennai, 2026-07-04, 13:00 local=UTC, avg=60 min):
        input: lat=13.08 lon=80.27 day=185 time=1300 u2m=3.0 solar=850
               Pair=1005 RH=70 Tair=35 dT=0
        output: Twbg=33.64  Tg=43.16  Tnwb=30.72  Tpsy=29.95

    Matching requires avg_minutes=60, since the C code centers the solar
    position calculation at (minute - 0.5*avg), i.e. 30 minutes before the
    timestamp for a 60-minute averaging window -- exactly how Open-Meteo's
    shortwave_radiation field is documented ("average of the preceding hour").
    """
    result = calc_wbgt(
        datetime(2026, 7, 4, 13, 0), lat=13.08, lon=80.27,
        solar_wm2=850.0, pressure_hpa=1005.0, tair_c=35.0, rh_pct=70.0,
        wind_speed_ms=3.0, wind_speed_height_m=2.0, dT_c=0.0, urban=False,
        avg_minutes=60,
    )
    assert result["status"] == 0
    assert result["Twbg"] == pytest.approx(33.64, abs=0.15)
    assert result["Tg"] == pytest.approx(43.16, abs=0.15)
    assert result["Tnwb"] == pytest.approx(30.72, abs=0.15)
    assert result["Tpsy"] == pytest.approx(29.95, abs=0.15)


def test_matches_compiled_reference_c_implementation_nighttime():
    """Same cross-check as above, for a zero-solar nighttime case.

    Reference run (Chennai, 2026-07-04, 03:00 local=UTC):
        input: lat=13.08 lon=80.27 day=185 time=0300 u2m=1.5 solar=0
               Pair=1005 RH=90 Tair=27 dT=0
        output: Twbg=25.94  Tg=26.51  Tnwb=25.62  Tpsy=25.65
    """
    result = calc_wbgt(
        datetime(2026, 7, 4, 3, 0), lat=13.08, lon=80.27,
        solar_wm2=0.0, pressure_hpa=1005.0, tair_c=27.0, rh_pct=90.0,
        wind_speed_ms=1.5, wind_speed_height_m=2.0, dT_c=0.0, urban=False,
        avg_minutes=60,
    )
    assert result["status"] == 0
    assert result["Twbg"] == pytest.approx(25.94, abs=0.1)
    assert result["Tg"] == pytest.approx(26.51, abs=0.1)
    assert result["Tnwb"] == pytest.approx(25.62, abs=0.1)
    assert result["Tpsy"] == pytest.approx(25.65, abs=0.1)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
