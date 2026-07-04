"""
Heat-metric functions for the India Humid Heat Monitor.

Keeps three metrics strictly separate, per this project's editorial rule:
  1. Dry-bulb temperature -- the raw value from Open-Meteo, used as-is.
  2. Wet-bulb temperature -- Stull (2011) empirical approximation.
  3. Estimated WBGT -- Liljegren et al. (2008) model (see liljegren_wbgt.py),
     with NIOSH RAL/REL exposure limits (not fixed "safe/unsafe" bands) as
     the risk reference.

Never compare wet-bulb values against WBGT thresholds, and vice versa --
they are different physical quantities with different risk meanings.
"""

import math
from datetime import datetime

from liljegren_wbgt import calc_wbgt as _liljegren_calc_wbgt


# ---------------------------------------------------------------------------
# 1. Wet-bulb temperature -- Stull (2011)
# ---------------------------------------------------------------------------
#
# Stull, R., 2011: "Wet-Bulb Temperature from Relative Humidity and Air
# Temperature." Journal of Applied Meteorology and Climatology, 50(11),
# 2267-2269. https://doi.org/10.1175/JAMC-D-11-0143.1
#
# Validity range: RH 5%-99%, T from -20C to 50C (accuracy degrades in the
# combined very-low-RH / very-cold-T corner).
# Error bounds: -1C to +0.65C, mean absolute error < 0.3C.
# Assumes sea-level (101.325 kPa) pressure -- all ~50 cities in this project
# are lowland/coastal, so this assumption holds; stated here for transparency.

STULL_VALID_T_RANGE_C = (-20.0, 50.0)
STULL_VALID_RH_RANGE_PCT = (5.0, 99.0)
STULL_ERROR_BOUNDS_C = (-1.0, 0.65)  # (min, max) error vs. true wet-bulb


def wet_bulb_stull(t_air_c: float, rh_pct: float) -> float:
    """
    Wet-bulb temperature (degC) from dry-bulb air temperature (degC) and
    relative humidity (%), via the Stull (2011) empirical approximation.

    Does not raise outside the validity range (5-99% RH, -20 to 50C) --
    callers that need to flag out-of-range inputs should check
    STULL_VALID_T_RANGE_C / STULL_VALID_RH_RANGE_PCT themselves, since a
    live weather feed will occasionally have edge-case values and this
    function should not crash the pipeline over one bad reading.
    """
    t = t_air_c
    rh = rh_pct
    return (
        t * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(t + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )


# ---------------------------------------------------------------------------
# 2. Estimated WBGT -- Liljegren et al. (2008)
# ---------------------------------------------------------------------------
#
# See liljegren_wbgt.py for the full ported model, license, and verification
# notes. This wrapper adds the unit/parameter defaults appropriate for our
# Open-Meteo data feed.
#
# Open-Meteo's `shortwave_radiation` field is documented as "average of the
# preceding hour" -- so avg_minutes=60 is passed to match, which matters:
# the Liljegren model centers its solar-position calculation at
# (minute - 0.5*avg), i.e. 30 minutes before an hourly timestamp for a
# 60-minute average. This was verified against Liljegren's own compiled
# reference C implementation (see tests/test_liljegren_wbgt.py) -- omitting
# it produces WBGT values off by several tenths of a degree C at midday.

def estimated_wbgt(
    dt_utc: datetime,
    lat: float,
    lon: float,
    solar_wm2: float,
    pressure_hpa: float,
    tair_c: float,
    rh_pct: float,
    wind_speed_ms: float,
    wind_speed_height_m: float = 10.0,
) -> dict:
    """
    Estimated outdoor WBGT (degC) and its components, from ordinary weather
    station inputs (temp, RH, solar radiation, wind) -- NOT a physical
    globe-thermometer measurement. See liljegren_wbgt.py's module docstring
    for the full method and its typical agreement (~1C) with measured WBGT
    under normal conditions.

    Returns a dict with keys Tg (globe temp), Tnwb (natural wet-bulb),
    Tpsy (psychrometric wet-bulb), Twbg (final WBGT), status (0 = ok,
    -1 = the underlying iterative solver failed to converge -- treat as
    missing data, do not silently substitute a fallback value).
    """
    return _liljegren_calc_wbgt(
        dt_utc, lat, lon, solar_wm2, pressure_hpa, tair_c, rh_pct,
        wind_speed_ms, wind_speed_height_m=wind_speed_height_m,
        avg_minutes=60,
    )


# ---------------------------------------------------------------------------
# 3. Outdoor-work risk reference -- NIOSH Recommended Alert/Exposure Limits
# ---------------------------------------------------------------------------
#
# Source: NIOSH, "Criteria for a Recommended Standard: Occupational Exposure
# to Heat and Hot Environments," DHHS (NIOSH) Publication 2016-106, Chapter
# 8.1, p.93-94 (equations) and Table 5-1, p.101 (cross-standard comparison).
# https://www.cdc.gov/niosh/docs/2016-106/ (PDF verified directly, not via a
# secondary paraphrase -- see this project's build notes).
#
#   RAL [C-WBGT] = 59.9 - 14.1 * log10(M)   -- unacclimatized workers
#   REL [C-WBGT] = 56.7 - 11.5 * log10(M)   -- acclimatized workers
#
# where M is 1-hour time-weighted-average metabolic rate, in watts, for a
# "standard" 70kg/1.8m^2 worker. These are NOT flat "safe/danger" bands --
# they vary continuously with workload and depend on acclimatization, work
# clothing, and work/rest scheduling, none of which this dashboard measures
# directly. Report them as reference lines for representative workloads,
# never as a universal cutoff, and always as "estimated WBGT relative to
# NIOSH's own limit for continuous moderate work" -- never as "safe hours."
#
# Representative metabolic rates (NIOSH 2016-106 Sec. 8.5.1, p.132, and the
# worked example on p.35 using 300 kcal/h moderate work):
#   light work    ~180 kcal/h ~= 209 W
#   moderate work ~300 kcal/h ~= 349 W  (NIOSH's own worked example uses this)
#   heavy work    ~400 kcal/h ~= 465 W
KCAL_H_TO_WATT = 1.163
METABOLIC_RATE_W = {
    "light": 180 * KCAL_H_TO_WATT,
    "moderate": 300 * KCAL_H_TO_WATT,
    "heavy": 400 * KCAL_H_TO_WATT,
}


def niosh_ral_c(metabolic_rate_w: float) -> float:
    """NIOSH Recommended Alert Limit (deg C WBGT) for UNACCLIMATIZED workers
    at the given 1-hour TWA metabolic rate (watts), continuous (60 min/h)
    work. Above this, NIOSH's own criteria call for added precautions for
    workers not yet heat-acclimatized."""
    return 59.9 - 14.1 * math.log10(metabolic_rate_w)


def niosh_rel_c(metabolic_rate_w: float) -> float:
    """NIOSH Recommended Exposure Limit (deg C WBGT) for ACCLIMATIZED
    workers at the given 1-hour TWA metabolic rate (watts), continuous
    (60 min/h) work."""
    return 56.7 - 11.5 * math.log10(metabolic_rate_w)
