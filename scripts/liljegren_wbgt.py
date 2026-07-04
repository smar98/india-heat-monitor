"""
Liljegren Wet Bulb Globe Temperature (WBGT) model — Python port.

Ported from https://github.com/mdljts/wbgt (wbgt.c, wbgt.h, wrapper.c),
an R-package wrapping of James C. Liljegren's original WBGT algorithm.
R wrapper/refactor by Max Lieblich (University of Washington, 2016-2017).
Original algorithm and C implementation by James C. Liljegren,
Decision & Information Sciences Division, Argonne National Laboratory.

Reference: Liljegren, J. C., R. A. Carhart, P. Lawday, S. Tschopp, and
R. Sharp: "Modeling the Wet Bulb Globe Temperature Using Standard
Meteorological Measurements." The Journal of Occupational and
Environmental Hygiene, vol. 5:10, pp. 645-655, 2008.

This is a line-by-line translation of the physics/iterative-solver logic
in wbgt.c into pure Python + math/numpy (no C extensions). Every constant,
iteration structure, and intermediate equation is preserved as in the
original C source, only the surrounding calling convention has been made
more Pythonic (a single calc_wbgt(dt_utc, ...) entry point that derives
year/month/day/hour/minute/gmt internally from a timezone-aware or naive
UTC datetime).

------------------------------------------------------------------------
The MIT License (MIT)

Copyright (c) 2016 Max Lieblich

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

------------------------------------------------------------------------
Original license follows (from wbgt.c):

               Copyright (c) 2008, UChicago Argonne, LLC
                       All Rights Reserved

                        WBGT, Version 1.1

                     James C. Liljegren
              Decision & Information Sciences Division

                     OPEN SOURCE LICENSE

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.  Software changes,
   modifications, or derivative works, should be noted with comments and
   the author and organization's name.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the names of UChicago Argonne, LLC or the Department of Energy
   nor the names of its contributors may be used to endorse or promote
   products derived from this software without specific prior written
   permission.

4. The software and the end-user documentation included with the
   redistribution, if any, must include the following acknowledgment:

   "This product includes software produced by UChicago Argonne, LLC
   under Contract No. DE-AC02-06CH11357 with the Department of Energy."

******************************************************************************
DISCLAIMER

THE SOFTWARE IS SUPPLIED "AS IS" WITHOUT WARRANTY OF ANY KIND.

NEITHER THE UNITED STATES GOVERNMENT, NOR THE UNITED STATES DEPARTMENT OF
ENERGY, NOR UCHICAGO ARGONNE, LLC, NOR ANY OF THEIR EMPLOYEES, MAKES ANY
WARRANTY, EXPRESS OR IMPLIED, OR ASSUMES ANY LEGAL LIABILITY OR
RESPONSIBILITY FOR THE ACCURACY, COMPLETENESS, OR USEFULNESS OF ANY
INFORMATION, DATA, APPARATUS, PRODUCT, OR PROCESS DISCLOSED, OR REPRESENTS
THAT ITS USE WOULD NOT INFRINGE PRIVATELY OWNED RIGHTS.
******************************************************************************
"""

import math
from datetime import datetime, timezone

# ============================================================================
# Mathematical constants (wbgt.h)
# ============================================================================
PI = 3.1415926535897932
TWOPI = 6.2831853071795864
DEG_RAD = 0.017453292519943295
RAD_DEG = 57.295779513082323

# ============================================================================
# Physical constants (wbgt.h)
# ============================================================================
SOLAR_CONST = 1367.0
GRAVITY = 9.807
STEFANB = 5.6696e-8
Cp = 1003.5
M_AIR = 28.97
M_H2O = 18.015
RATIO = Cp * M_AIR / M_H2O
R_GAS = 8314.34
R_AIR = R_GAS / M_AIR
Pr = Cp / (Cp + 1.25 * R_AIR)

# ============================================================================
# Wick constants (wbgt.h)
# ============================================================================
EMIS_WICK = 0.95
ALB_WICK = 0.4
D_WICK = 0.007
L_WICK = 0.0254

# ============================================================================
# Globe constants (wbgt.h)
# ============================================================================
EMIS_GLOBE = 0.95
ALB_GLOBE = 0.05
D_GLOBE = 0.0508

# ============================================================================
# Surface constants (wbgt.h)
# ============================================================================
EMIS_SFC = 0.999
ALB_SFC = 0.45

# ============================================================================
# Computational and physical limits (wbgt.h)
# ============================================================================
CZA_MIN = 0.00873
NORMSOLAR_MAX = 0.85
REF_HEIGHT = 2.0
MIN_SPEED = 0.13
CONVERGENCE = 0.02
MAX_ITER = 500


def _c_int_div(a, b):
    """
    Mimic C's integer division truncation-toward-zero semantics (used for
    `delta_years / 4` in solarposition(), where delta_years can be negative
    for years before 2000). Python's `//` floors toward negative infinity,
    which differs from C for negative operands, so this cannot be replaced
    by a plain `//`.
    """
    q = a / b
    return int(q) if q >= 0 else -int(-q)


def _modf(x):
    """
    Mimic C's modf(x, &integral): returns (fractional_part, integral_part)
    with both parts carrying the same sign as x. Python's math.modf already
    has this exact behavior (it returns (fractional, integral), matching
    C's semantics, just without the pointer-based output argument), so this
    is a thin wrapper kept for readability / line-by-line correspondence
    with the C source, which repeatedly calls `modf(x, &integral)`.
    """
    frac, integral = math.modf(x)
    return frac, integral


# ============================================================================
#  Purpose: to calculate the outdoor wet bulb-globe temperature, which is
#           the weighted sum of the air temperature (dry bulb), the globe
#           temperature, and the natural wet bulb temperature:
#               Twbg = 0.1 * Tair + 0.7 * Tnwb + 0.2 * Tg.
#           The program predicts Tnwb and Tg using meteorological input data
#           then combines the results to produce Twbg.
#
#           Modified 2-Nov-2009: calc_wbgt returns -1 if either subroutines
#           Tg or Tnwb return -9999, which signals a failure to converge,
#           probably due to a bad input value; otherwise, calc_wbgt returns 0.
#
#           If the 2-m wind speed is not available, it is estimated using a
#           wind speed at another level.
#
#  Reference: Liljegren, J. C., R. A. Carhart, P. Lawday, S. Tschopp, and
#             R. Sharp: Modeling the Wet Bulb Globe Temperature Using
#             Standard Meteorological Measurements. The Journal of
#             Occupational and Environmental Hygiene, vol. 5:10,
#             pp. 645-655, 2008.
#
#  Author:  James C. Liljegren
#           Decision and Information Sciences Division
#           Argonne National Laboratory
# ============================================================================
def _calc_wbgt(year, month, day, hour, minute, gmt, avg,
               lat, lon, solar, pres, Tair, relhum,
               speed, zspeed, dT, urban):
    """
    Direct port of calc_wbgt() from wbgt.c.

    Parameters (all units exactly as documented in wbgt.h):
        year    4-digit, e.g. 2007
        month   month (1-12) or month = 0 implies `day` is day of year
        day     day of month or day of year (1-366)
        hour    hour in local standard time (LST)
        minute  minutes past the hour
        gmt     LST-GMT difference, hours (negative in USA)
        avg     averaging time of meteorological inputs, minutes
        lat     north latitude, decimal degrees
        lon     east longitude, decimal degrees (negative in USA)
        solar   solar irradiance, W/m2
        pres    barometric pressure, mb (hPa)
        Tair    air (dry bulb) temperature, degC
        relhum  relative humidity, %
        speed   wind speed, m/s
        zspeed  height of wind speed measurement, m
        dT      vertical temperature difference (upper minus lower), degC
        urban   select "urban" (1) or "rural" (0) wind speed power law exponent

    Returns:
        (status, est_speed, Tg, Tnwb, Tpsy, Twbg)
        status: 0 on success, -1 if Tg or Tnwb failed to converge (-9999)
    """
    # convert time to GMT and center in avg period
    hour_gmt = hour - gmt + (minute - 0.5 * avg) / 60.0
    dday = day + hour_gmt / 24.0

    # calculate the cosine of the solar zenith angle and fraction of solar
    # irradiance due to the direct beam; adjust the solar irradiance if it
    # is out of bounds
    solar, cza, fdir = calc_solar_parameters(year, month, dday, lat, lon, solar)

    # estimate the wind speed, if necessary
    est_speed = 0.0
    if zspeed != REF_HEIGHT:
        daytime = cza > 0.0
        stability_class = stab_srdt(daytime, speed, solar, dT)
        est_speed = est_wind_speed(speed, zspeed, stability_class, urban)
        speed = est_speed

    # unit conversions
    tk = Tair + 273.15  # degC to kelvin
    rh = 0.01 * relhum  # % to fraction

    # calculate the globe, natural wet bulb, psychrometric wet bulb, and
    # outdoor wet bulb globe temperatures
    Tg = Tglobe(tk, rh, pres, speed, solar, fdir, cza)
    Tnwb = Twb(tk, rh, pres, speed, solar, fdir, cza, True)
    Tpsy = Twb(tk, rh, pres, speed, solar, fdir, cza, False)
    Twbg = 0.1 * Tair + 0.2 * Tg + 0.7 * Tnwb

    if Tg == -9999 or Tnwb == -9999:
        Twbg = -9999
        return -1, est_speed, Tg, Tnwb, Tpsy, Twbg
    else:
        return 0, est_speed, Tg, Tnwb, Tpsy, Twbg


# ============================================================================
#  Purpose: to calculate the cosine solar zenith angle and the fraction of
#           the solar irradiance due to the direct beam.
#
#  Author:  James C. Liljegren
#           Decision and Information Sciences Division
#           Argonne National Laboratory
# ============================================================================
def calc_solar_parameters(year, month, day, lat, lon, solar):
    """
    Direct port of calc_solar_parameters() from wbgt.c.

    Returns (solar, cza, fdir):
        solar  adjusted solar irradiance, W/m2
        cza    cosine of solar zenith angle
        fdir   fraction of solar irradiance due to direct beam
    """
    days_1900 = 0.0
    ap_ra, ap_dec, elev, refr, azim, soldist = solarposition(
        year, month, day, days_1900, float(lat), float(lon)
    )
    cza = math.cos((90.0 - elev) * DEG_RAD)
    toasolar = SOLAR_CONST * max(0.0, cza) / (soldist * soldist)

    # if the sun is not fully above the horizon set the maximum
    # (top of atmosphere) solar = 0
    if cza < CZA_MIN:
        toasolar = 0.0

    if toasolar > 0.0:
        # account for any solar sensor calibration errors and make the
        # solar irradiance consistent with normsolar
        normsolar = min(solar / toasolar, NORMSOLAR_MAX)
        solar = normsolar * toasolar

        # calculate the fraction of the solar irradiance due to the direct beam
        if normsolar > 0.0:
            fdir = math.exp(3.0 - 1.34 * normsolar - 1.65 / normsolar)
            fdir = max(min(fdir, 0.9), 0.0)
        else:
            fdir = 0.0
    else:
        fdir = 0.0

    return solar, cza, fdir


# ============================================================================
#  Purpose: to calculate the natural wet bulb temperature.
#
#  Author:  James C. Liljegren
#           Decision and Information Sciences Division
#           Argonne National Laboratory
# ============================================================================
def Twb(Tair, rh, Pair, speed, solar, fdir, cza, rad):
    """
    Direct port of Twb() from wbgt.c.

    Tair    air (dry bulb) temperature, K
    rh      relative humidity, fraction between 0 and 1
    Pair    barometric pressure, mb
    speed   wind speed, m/s
    solar   solar irradiance, W/m2
    fdir    fraction of solar irradiance due to direct beam
    cza     cosine of solar zenith angle
    rad     bool; enable/disable radiative heating.
            rad=False -> psychrometric wet bulb temp (no radiative heating)
            rad=True  -> natural wet bulb temp

    Returns wet bulb temperature in degC, or -9999.0 if the iteration failed
    to converge within MAX_ITER.
    """
    a = 0.56  # from Bedingfield and Drew

    Tsfc = Tair
    sza = math.acos(cza)  # solar zenith angle, radians
    eair = rh * esat(Tair, 0)
    Tdew = dew_point(eair, 0)
    Twb_prev = Tdew  # first guess is the dew point temperature
    converged = False
    iter_ = 0
    Twb_new = Twb_prev

    rad_flag = 1.0 if rad else 0.0

    while not converged and iter_ < MAX_ITER:
        iter_ += 1
        Tref = 0.5 * (Twb_prev + Tair)  # evaluate properties at the average temperature
        h = h_cylinder_in_air(D_WICK, L_WICK, Tref, Pair, speed)
        Fatm = (
            STEFANB * EMIS_WICK
            * (
                0.5 * (emis_atm(Tair, rh) * Tair ** 4 + EMIS_SFC * Tsfc ** 4)
                - Twb_prev ** 4
            )
            + (1.0 - ALB_WICK) * solar
            * (
                (1.0 - fdir) * (1.0 + 0.25 * D_WICK / L_WICK)
                + fdir * ((math.tan(sza) / PI) + 0.25 * D_WICK / L_WICK)
                + ALB_SFC
            )
        )
        ewick = esat(Twb_prev, 0)
        density = Pair * 100.0 / (R_AIR * Tref)
        Sc = viscosity(Tref) / (density * diffusivity(Tref, Pair))
        Twb_new = (
            Tair
            - evap(Tref) / RATIO * (ewick - eair) / (Pair - ewick) * (Pr / Sc) ** a
            + (Fatm / h * rad_flag)
        )
        if abs(Twb_new - Twb_prev) < CONVERGENCE:
            converged = True
        Twb_prev = 0.9 * Twb_prev + 0.1 * Twb_new

    if converged:
        return Twb_new - 273.15
    else:
        return -9999.0


# ============================================================================
# Purpose: to calculate the convective heat transfer coefficient in W/(m2 K)
#          for a long cylinder in cross flow.
#
# Reference: Bedingfield and Drew, eqn 32
# ============================================================================
def h_cylinder_in_air(diameter, length, Tair, Pair, speed):
    """
    diameter  cylinder diameter, m
    length    cylinder length, m (unused in the original formula, kept for
              signature fidelity with the C source)
    Tair      air temperature, K
    Pair      barometric pressure, mb
    speed     fluid (wind) speed, m/s
    """
    a = 0.56  # parameters from Bedingfield and Drew
    b = 0.281
    c = 0.4

    density = Pair * 100.0 / (R_AIR * Tair)
    Re = max(speed, MIN_SPEED) * density * diameter / viscosity(Tair)
    Nu = b * Re ** (1.0 - c) * Pr ** (1.0 - a)
    return Nu * thermal_cond(Tair) / diameter


# ============================================================================
#  Purpose: to calculate the globe temperature.
#
#  Author:  James C. Liljegren
#           Decision and Information Sciences Division
#           Argonne National Laboratory
# ============================================================================
def Tglobe(Tair, rh, Pair, speed, solar, fdir, cza):
    """
    Direct port of Tglobe() from wbgt.c.

    Tair    air (dry bulb) temperature, K
    rh      relative humidity, fraction between 0 and 1
    Pair    barometric pressure, mb
    speed   wind speed, m/s
    solar   solar irradiance, W/m2
    fdir    fraction of solar irradiance due to direct beam
    cza     cosine of solar zenith angle

    Returns globe temperature in degC, or -9999.0 if the iteration failed
    to converge within MAX_ITER.
    """
    Tsfc = Tair
    Tglobe_prev = Tair  # first guess is the air temperature
    converged = False
    iter_ = 0
    Tglobe_new = Tglobe_prev

    while not converged and iter_ < MAX_ITER:
        iter_ += 1
        Tref = 0.5 * (Tglobe_prev + Tair)  # evaluate properties at the average temperature
        h = h_sphere_in_air(D_GLOBE, Tref, Pair, speed)
        base = (
            0.5 * (emis_atm(Tair, rh) * Tair ** 4 + EMIS_SFC * Tsfc ** 4)
            - h / (STEFANB * EMIS_GLOBE) * (Tglobe_prev - Tair)
            + solar / (2.0 * STEFANB * EMIS_GLOBE) * (1.0 - ALB_GLOBE)
            * (fdir * (1.0 / (2.0 * cza) - 1.0) + 1.0 + ALB_SFC)
        )
        # C's pow(base, 0.25) requires base >= 0 for a real result; preserve
        # that behavior (a negative base here would indicate a non-physical
        # input rather than something to silently coerce).
        Tglobe_new = base ** 0.25
        if abs(Tglobe_new - Tglobe_prev) < CONVERGENCE:
            converged = True
        Tglobe_prev = 0.9 * Tglobe_prev + 0.1 * Tglobe_new

    if converged:
        return Tglobe_new - 273.15
    else:
        return -9999.0


# ============================================================================
# Purpose: to calculate the convective heat transfer coefficient, W/(m2 K)
#          for flow around a sphere.
#
# Reference: Bird, Stewart, and Lightfoot (BSL), page 409.
# ============================================================================
def h_sphere_in_air(diameter, Tair, Pair, speed):
    """
    diameter  sphere diameter, m
    Tair      air temperature, K
    Pair      barometric pressure, mb
    speed     fluid (air) speed, m/s
    """
    density = Pair * 100.0 / (R_AIR * Tair)
    Re = max(speed, MIN_SPEED) * density * diameter / viscosity(Tair)
    Nu = 2.0 + 0.6 * math.sqrt(Re) * Pr ** 0.3333
    return Nu * thermal_cond(Tair) / diameter


# ============================================================================
#  Purpose: calculate the saturation vapor pressure (mb) over liquid water
#           (phase = 0) or ice (phase = 1).
#
#  Reference: Buck's (1981) approximation (eqn 3) of Wexler's (1976) formulae.
# ============================================================================
def esat(tk, phase):
    """
    tk     air temperature, K
    phase  0 = over liquid water, 1 = over ice
    """
    if phase == 0:  # over liquid water
        y = (tk - 273.15) / (tk - 32.18)
        es = 6.1121 * math.exp(17.502 * y)
        # es = (1.0007 + (3.46E-6 * pres)) * es  # correction for moist air, if pressure is available
    else:  # over ice
        y = (tk - 273.15) / (tk - 0.6)
        es = 6.1115 * math.exp(22.452 * y)
        # es = (1.0003 + (4.18E-6 * pres)) * es  # correction for moist air, if pressure is available

    es = 1.004 * es  # correction for moist air, if pressure is not available; for pressure > 800 mb
    # es = 1.0034 * es  # correction for moist air, if pressure is not available; for pressure down to 200 mb

    return es


# ============================================================================
#  Purpose: calculate the dew point (phase=0) or frost point (phase=1)
#           temperature, K.
# ============================================================================
def dew_point(e, phase):
    """
    e      vapor pressure, mb
    phase  0 = dew point, 1 = frost point
    """
    if phase == 0:  # dew point
        z = math.log(e / (6.1121 * 1.004))
        tdk = 273.15 + 240.97 * z / (17.502 - z)
    else:  # frost point
        z = math.log(e / (6.1115 * 1.004))
        tdk = 273.15 + 272.55 * z / (22.452 - z)

    return tdk


# ============================================================================
#  Purpose: calculate the viscosity of air, kg/(m s)
#
#  Reference: BSL, page 23.
# ============================================================================
def viscosity(Tair):
    """Tair: air temperature, K"""
    sigma = 3.617
    eps_kappa = 97.0

    Tr = Tair / eps_kappa
    omega = (Tr - 2.9) / 0.4 * (-0.034) + 1.048
    return 2.6693e-6 * math.sqrt(M_AIR * Tair) / (sigma * sigma * omega)


# ============================================================================
#  Purpose: calculate the thermal conductivity of air, W/(m K)
#
#  Reference: BSL, page 257.
# ============================================================================
def thermal_cond(Tair):
    """Tair: air temperature, K"""
    return (Cp + 1.25 * R_AIR) * viscosity(Tair)


# ============================================================================
#  Purpose: calculate the diffusivity of water vapor in air, m2/s
#
#  Reference: BSL, page 505.
# ============================================================================
def diffusivity(Tair, Pair):
    """
    Tair  air temperature, K
    Pair  barometric pressure, mb
    """
    Pcrit_air = 36.4
    Pcrit_h2o = 218.0
    Tcrit_air = 132.0
    Tcrit_h2o = 647.3
    a = 3.640e-4
    b = 2.334

    Pcrit13 = (Pcrit_air * Pcrit_h2o) ** (1.0 / 3.0)
    Tcrit512 = (Tcrit_air * Tcrit_h2o) ** (5.0 / 12.0)
    Tcrit12 = math.sqrt(Tcrit_air * Tcrit_h2o)
    Mmix = math.sqrt(1.0 / M_AIR + 1.0 / M_H2O)
    Patm = Pair / 1013.25  # convert pressure from mb to atmospheres

    return a * (Tair / Tcrit12) ** b * Pcrit13 * Tcrit512 * Mmix / Patm * 1e-4


# ============================================================================
#  Purpose: calculate the heat of evaporation, J/(kg K), for temperature
#           in the range 283-313 K.
#
#  Reference: Van Wylen and Sonntag, Table A.1.1
# ============================================================================
def evap(Tair):
    """Tair: air temperature, K"""
    return (313.15 - Tair) / 30.0 * (-71100.0) + 2.4073e6


# ============================================================================
#  Purpose: calculate the atmospheric emissivity.
#
#  Reference: Oke (2nd edition), page 373.
# ============================================================================
def emis_atm(Tair, rh):
    """
    Tair  air temperature, K
    rh    relative humidity, fraction between 0 and 1
    """
    e = rh * esat(Tair, 0)
    return 0.575 * e ** 0.143


# ============================================================================
#  Version 3.0 - February 20, 1992.
#
#  solarposition() employs the low precision formulas for the Sun's
#  coordinates given in the "Astronomical Almanac" of 1990 to compute the
#  Sun's apparent right ascension, apparent declination, altitude,
#  atmospheric refraction correction applicable to the altitude, azimuth,
#  and distance from Earth. The "Astronomical Almanac" (A. A.) states a
#  precision of 0.01 degree for the apparent coordinates between the years
#  1950 and 2050, and an accuracy of 0.1 arc minute for refraction at
#  altitudes of at least 15 degrees.
#
#  Author: Nels Larson, Pacific Northwest National Laboratory
# ============================================================================
def solarposition(year, month, day, days_1900, latitude, longitude):
    """
    Direct port of solarposition() from wbgt.c.

    year        4-digit year (Gregorian calendar) [1950-2049; 0 ok if using days_1900]
    month       month number [1-12; 0 ok if using daynumber for day]
    day         calendar day.fraction, or daynumber.fraction (GMT)
    days_1900   days since 1900 January 0 @ 00:00:00 UT (used only if year == 0)
    latitude    north latitude, degrees.fraction
    longitude   east longitude, degrees.fraction

    Returns (ap_ra, ap_dec, altitude, refraction, azimuth, distance):
        ap_ra       apparent solar right ascension, hours [0, 24)
        ap_dec      apparent solar declination, degrees [-90, 90]
        altitude    solar altitude (refraction-corrected), degrees
        refraction  refraction correction, degrees
        azimuth     solar azimuth, degrees [0, 360)
        distance    distance of Sun from Earth, astronomical units

    Raises ValueError for out-of-bounds inputs, mirroring the C function's
    return of -1 (here surfaced as an exception since there's no output
    pointer convention in Python).
    """
    pressure = 1013.25  # Earth mean atmospheric pressure at sea level, mb
    temp = 15.0  # Earth mean atmospheric temperature at sea level, degC

    if latitude < -90.0 or latitude > 90.0 or longitude < -180.0 or longitude > 180.0:
        raise ValueError("latitude/longitude out of bounds")

    if year != 0:
        # Date given by {year, month, day} or {year, 0, daynumber}.
        if year < 1950 or year > 2049:
            raise ValueError("year out of bounds [1950, 2049]")
        if month != 0:
            if month < 1 or month > 12 or day < 0.0 or day > 33.0:
                raise ValueError("month/day out of bounds")
            daynumber = daynum(year, month, int(day))
        else:
            if day < 0.0 or day > 368.0:
                raise ValueError("day out of bounds")
            daynumber = int(day)

        # Construct Julian centuries since J2000 at 0 hours UT of date,
        # days.fraction since J2000, and UT hours.
        delta_years = year - 2000
        # delta_days is days from 2000/01/00 (1900's are negative).
        delta_days = delta_years * 365 + _c_int_div(delta_years, 4) + daynumber
        if year > 2000:
            delta_days += 1
        # J2000 is 2000/01/01.5
        days_J2000 = delta_days - 1.5

        cent_J2000 = days_J2000 / 36525.0

        ut, integral = _modf(day)
        days_J2000 += ut
        ut *= 24.0
    else:
        # Date given by days_1900.
        if days_1900 < 18262.0 or days_1900 > 54788.0:
            raise ValueError("days_1900 out of bounds")

        # days_1900 is 36524 for 2000/01/00. J2000 is 2000/01/01.5
        days_J2000 = days_1900 - 36525.5

        ut_frac, integral = _modf(days_1900)
        ut = ut_frac * 24.0

        cent_J2000 = (integral - 36525.5) / 36525.0

    # Compute solar position parameters. A. A. 1990, C24.
    mean_anomaly = 357.528 + 0.9856003 * days_J2000
    mean_longitude = 280.460 + 0.9856474 * days_J2000

    # Put mean_anomaly and mean_longitude in the range 0 -> 2 pi.
    frac, integral = _modf(mean_anomaly / 360.0)
    mean_anomaly = frac * TWOPI
    frac, integral = _modf(mean_longitude / 360.0)
    mean_longitude = frac * TWOPI

    mean_obliquity = (23.439 - 4.0e-7 * days_J2000) * DEG_RAD
    ecliptic_long = (
        (1.915 * math.sin(mean_anomaly)) + (0.020 * math.sin(2.0 * mean_anomaly))
    ) * DEG_RAD + mean_longitude

    distance = 1.00014 - 0.01671 * math.cos(mean_anomaly) - 0.00014 * math.cos(2.0 * mean_anomaly)

    # Tangent of ecliptic_long separated into sine and cosine parts for ap_ra.
    ap_ra = math.atan2(math.cos(mean_obliquity) * math.sin(ecliptic_long), math.cos(ecliptic_long))

    # Change range of ap_ra from -pi -> pi to 0 -> 2 pi.
    if ap_ra < 0.0:
        ap_ra += TWOPI
    # Put ap_ra in the range 0 -> 24 hours.
    frac, integral = _modf(ap_ra / TWOPI)
    ap_ra = frac * 24.0

    ap_dec = math.asin(math.sin(mean_obliquity) * math.sin(ecliptic_long))

    # Calculate local mean sidereal time. A. A. 1990, B6-B7.
    # Horner's method of polynomial exponent expansion used for gmst0h.
    gmst0h = 24110.54841 + cent_J2000 * (
        8640184.812866 + cent_J2000 * (0.093104 - cent_J2000 * 6.2e-6)
    )
    # Convert gmst0h from seconds to hours and put in the range 0 -> 24.
    frac, integral = _modf(gmst0h / 3600.0 / 24.0)
    gmst0h = frac * 24.0
    if gmst0h < 0.0:
        gmst0h += 24.0

    # Ratio of lengths of mean solar day to mean sidereal day is
    # 1.00273790934 in 1990.
    lmst = gmst0h + (ut * 1.00273790934) + longitude / 15.0
    # Put lmst in the range 0 -> 24 hours.
    frac, integral = _modf(lmst / 24.0)
    lmst = frac * 24.0
    if lmst < 0.0:
        lmst += 24.0

    # Calculate local hour angle, altitude, azimuth, and refraction correction.
    # A. A. 1990, B61-B62.
    local_ha = lmst - ap_ra
    # Put hour angle in the range -12 to 12 hours.
    if local_ha < -12.0:
        local_ha += 24.0
    elif local_ha > 12.0:
        local_ha -= 24.0

    # Convert latitude and local_ha to radians.
    latitude_rad = latitude * DEG_RAD
    local_ha = local_ha / 24.0 * TWOPI

    cos_apdec = math.cos(ap_dec)
    sin_apdec = math.sin(ap_dec)
    cos_lat = math.cos(latitude_rad)
    sin_lat = math.sin(latitude_rad)
    cos_lha = math.cos(local_ha)

    altitude = math.asin(sin_apdec * sin_lat + cos_apdec * cos_lha * cos_lat)

    cos_alt = math.cos(altitude)
    # Avoid tangent overflow at altitudes of +-90 degrees.
    # 1.57079615 radians is equal to 89.99999 degrees.
    if abs(altitude) < 1.57079615:
        tan_alt = math.tan(altitude)
    else:
        tan_alt = 6.0e6

    cos_az = (sin_apdec * cos_lat - cos_apdec * cos_lha * sin_lat) / cos_alt
    sin_az = -(cos_apdec * math.sin(local_ha) / cos_alt)
    azimuth = math.acos(cos_az)

    # Change range of azimuth from 0 -> pi to 0 -> 2 pi.
    if math.atan2(sin_az, cos_az) < 0.0:
        azimuth = TWOPI - azimuth

    # Convert ap_dec, altitude, and azimuth to degrees.
    ap_dec *= RAD_DEG
    altitude *= RAD_DEG
    azimuth *= RAD_DEG

    # Compute refraction correction to be added to altitude to obtain actual
    # position.
    if altitude < -1.0 or tan_alt == 6.0e6:
        refraction = 0.0
    else:
        if altitude < 19.225:
            refraction = (0.1594 + altitude * (0.0196 + 0.00002 * altitude)) * pressure
            refraction /= (1.0 + altitude * (0.505 + 0.0845 * altitude)) * (273.0 + temp)
        else:
            refraction = 0.00452 * (pressure / (273.0 + temp)) / tan_alt

    # to match Michalsky's sunae program, the following line was inserted
    # by JC Liljegren to add the refraction correction to the solar altitude
    altitude = altitude + refraction

    return ap_ra, ap_dec, altitude, refraction, azimuth, distance


# ============================================================================
# 'daynum()' returns the sequential daynumber of a calendar date during a
#  Gregorian calendar year (for years 1 onward).
#  (Jan. 1 = 01/01 = 001; Dec. 31 = 12/31 = 365 or 366.)
#
#  Author: Nels Larson, Pacific Northwest Lab.
# ============================================================================
def daynum(year, month, day):
    """year, month, day: integers"""
    begmonth = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    leapyr = 0

    if year < 1:
        return -1

    if ((year % 4) == 0 and (year % 100) != 0) or (year % 400) == 0:
        leapyr = 1

    dnum = begmonth[month] + day
    if leapyr and (month > 2):
        dnum += 1

    return dnum


# ============================================================================
#  Purpose: estimate 2-m wind speed for all stability conditions
#
#  Reference: EPA-454/5-99-005, 2000, section 6.2.5
# ============================================================================
def est_wind_speed(speed, zspeed, stability_class, urban):
    """
    speed             wind speed measured at zspeed, m/s
    zspeed            height of wind speed measurement, m
    stability_class   Pasquill stability class, 1-6 (1-indexed, as in the C source)
    urban             bool (or 1/0): urban vs rural power-law exponent
    """
    urban_exp = [0.15, 0.15, 0.20, 0.25, 0.30, 0.30]
    rural_exp = [0.07, 0.07, 0.10, 0.15, 0.35, 0.55]

    if urban:
        exponent = urban_exp[stability_class - 1]
    else:
        exponent = rural_exp[stability_class - 1]

    est_speed = speed * (REF_HEIGHT / zspeed) ** exponent
    est_speed = max(est_speed, MIN_SPEED)
    return est_speed


# ============================================================================
#  Purpose: estimate the stability class
#
#  Reference: EPA-454/5-99-005, 2000, section 6.2.5
# ============================================================================
def stab_srdt(daytime, speed, solar, dT):
    """
    daytime  bool
    speed    wind speed, m/s
    solar    solar irradiance, W/m2
    dT       vertical temperature difference (upper minus lower), degC

    Returns the Pasquill stability class, an integer 1-6.
    """
    lsrdt = [
        [1, 1, 2, 4, 0, 5, 6, 0],
        [1, 2, 3, 4, 0, 5, 6, 0],
        [2, 2, 3, 4, 0, 4, 4, 0],
        [3, 3, 4, 4, 0, 0, 0, 0],
        [3, 4, 4, 4, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0],
    ]

    if daytime:
        if solar >= 925.0:
            j = 0
        elif solar >= 675.0:
            j = 1
        elif solar >= 175.0:
            j = 2
        else:
            j = 3

        if speed >= 6.0:
            i = 4
        elif speed >= 5.0:
            i = 3
        elif speed >= 3.0:
            i = 2
        elif speed >= 2.0:
            i = 1
        else:
            i = 0
    else:
        if dT >= 0.0:
            j = 6
        else:
            j = 5

        if speed >= 2.5:
            i = 2
        elif speed >= 2.0:
            i = 1
        else:
            i = 0

    return lsrdt[i][j]


# ============================================================================
# Public, Pythonic entry point
# ============================================================================
def calc_wbgt(dt_utc, lat, lon, solar_wm2, pressure_hpa, tair_c, rh_pct,
              wind_speed_ms, wind_speed_height_m=10.0, dT_c=0.0, urban=False,
              avg_minutes=5):
    """
    Compute the Liljegren et al. (2008) outdoor Wet Bulb Globe Temperature.

    This is a thin, unit-preserving wrapper around the ported calc_wbgt()
    from wbgt.c. It derives year/month/day/hour/minute and the LST-GMT
    offset ("gmt") from a UTC datetime so callers don't need to juggle
    local-standard-time conventions themselves: since dt_utc is UTC,
    local standard time == GMT, so gmt=0 and hour/minute are taken directly
    from dt_utc. This is equivalent to the C algorithm's LST/GMT handling
    with gmt=0.

    Parameters
    ----------
    dt_utc : datetime.datetime
        Date/time of the observation, in UTC. May be naive (assumed UTC)
        or timezone-aware (converted to UTC).
    lat : float
        North latitude, decimal degrees (negative for southern hemisphere).
    lon : float
        East longitude, decimal degrees (negative in the Americas).
    solar_wm2 : float
        Solar irradiance, W/m^2 (0 at night).
    pressure_hpa : float
        Barometric (station) pressure, hPa == mb.
    tair_c : float
        Air (dry bulb) temperature, degrees Celsius.
    rh_pct : float
        Relative humidity, percent (0-100).
    wind_speed_ms : float
        Wind speed, m/s, measured at `wind_speed_height_m`.
    wind_speed_height_m : float, default 10.0
        Height at which wind speed was measured, meters. If this is not
        exactly REF_HEIGHT (2.0 m), the wind speed is extrapolated to 2 m
        using the EPA power-law method (stability class dependent).
    dT_c : float, default 0.0
        Vertical temperature difference (upper minus lower), degrees C.
        Only used to help classify atmospheric stability when
        wind_speed_height_m != 2.0; if you don't have this measurement,
        leave at the default (0.0 implies neutral-to-stable at night in
        the stability lookup).
    urban : bool, default False
        True selects the "urban" wind-speed power-law exponent, False the
        "rural" exponent, used only when extrapolating wind speed to 2 m.
    avg_minutes : float, default 5
        Averaging time of the meteorological inputs, minutes. Used only to
        center the time stamp within the averaging window (matches the
        `avg` parameter of the original C function).

    Returns
    -------
    dict with keys, all in degrees Celsius:
        "Tg"   : globe temperature
        "Tnwb" : natural wet bulb temperature
        "Tpsy" : psychrometric wet bulb temperature
        "Twbg" : wet bulb globe temperature (outdoor),
                 Twbg = 0.1*Tair + 0.2*Tg + 0.7*Tnwb
        "est_speed" : estimated wind speed at 2 m reference height, m/s
                      (equal to wind_speed_ms if wind_speed_height_m == 2.0)
        "status" : 0 on success, -1 if the globe or natural-wet-bulb
                   iterative solver failed to converge (in which case Tg
                   and/or Tnwb will be -9999.0 and Twbg will be -9999.0)

    Notes
    -----
    All physical constants, iteration structure, and equations reproduce
    wbgt.c exactly (see module docstring for provenance).
    """
    if dt_utc.tzinfo is not None:
        dt_utc = dt_utc.astimezone(timezone.utc)

    year = dt_utc.year
    month = dt_utc.month
    day = dt_utc.day
    hour = dt_utc.hour
    minute = dt_utc.minute + dt_utc.second / 60.0
    gmt = 0  # dt_utc is already UTC, so local-standard-time == GMT

    status, est_speed, Tg, Tnwb, Tpsy, Twbg = _calc_wbgt(
        year, month, day, hour, minute, gmt, avg_minutes,
        lat, lon, solar_wm2, pressure_hpa, tair_c, rh_pct,
        wind_speed_ms, wind_speed_height_m, dT_c, urban,
    )

    return {
        "Tg": Tg,
        "Tnwb": Tnwb,
        "Tpsy": Tpsy,
        "Twbg": Twbg,
        "est_speed": est_speed,
        "status": status,
    }
