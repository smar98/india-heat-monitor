"""
Pulls the live 7-day hourly forecast (temp, humidity, solar radiation, wind,
pressure) for all ~50 cities from Open-Meteo in a single batched request,
computes wet-bulb temperature (Stull 2011) and estimated WBGT (Liljegren
2008) for every city/hour, and writes heat/data/latest.json.

Run every 6 hours by .github/workflows/update-data.yml. Can also be run
by hand from the repo root:

    python3 scripts/fetch_forecast.py

Open-Meteo: no API key needed, free tier is 10,000 calls/day -- this script
makes exactly 1 call per run, batching all cities via comma-separated
latitude/longitude lists.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from wbgt import wet_bulb_stull, estimated_wbgt

HERE = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(HERE, "..", "heat", "data", "cities.json")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "latest.json")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "temperature_2m,relative_humidity_2m,shortwave_radiation,wind_speed_10m,surface_pressure"
FORECAST_DAYS = 2  # today + tomorrow, enough for the workday-clock view

# India Standard Time is a fixed UTC+5:30 offset with no daylight saving.
# Requesting timezone=Asia/Kolkata from Open-Meteo gives full, gap-free IST
# calendar days (00:00-23:00 IST for each of the 2 requested days) instead
# of UTC calendar days -- which matters because a prior version of this
# pipeline requested timezone=UTC, so hour 0 of the array was midnight UTC
# of the day the script happened to run, not "now" or even "today in IST."
# That meant the frontend's "current" value and "today" row could be up to
# ~12 hours stale relative to the actual moment a user loaded the page.
IST_OFFSET = timedelta(hours=5, minutes=30)


def load_cities():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_forecast_batch(cities):
    """One Open-Meteo call for all cities. Returns a list of per-city
    response dicts, in the same order as `cities` (Open-Meteo preserves
    request order for batched lat/lon queries)."""
    params = {
        "latitude": ",".join(str(c["lat"]) for c in cities),
        "longitude": ",".join(str(c["lon"]) for c in cities),
        "hourly": HOURLY_VARS,
        "forecast_days": FORECAST_DAYS,
        "timezone": "Asia/Kolkata",  # gap-free IST calendar days; see IST_OFFSET note above
        "wind_speed_unit": "ms",
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        # Open-Meteo returns a single object (not a list) if only one
        # location was requested -- normalize so callers always get a list.
        data = [data]
    if len(data) != len(cities):
        raise RuntimeError(
            f"Open-Meteo returned {len(data)} results for {len(cities)} "
            f"requested cities -- refusing to guess the city/result mapping."
        )
    return data


def build_city_record(city, forecast):
    hourly = forecast["hourly"]
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    rhs = hourly["relative_humidity_2m"]
    solars = hourly["shortwave_radiation"]
    winds = hourly["wind_speed_10m"]
    pressures = hourly["surface_pressure"]

    hourly_out = []
    for i, t in enumerate(times):
        dt_ist = datetime.fromisoformat(t)  # naive, represents IST wall-clock time (see IST_OFFSET note)
        dt_utc = dt_ist - IST_OFFSET  # true UTC instant, needed for the WBGT solar-position calc

        temp_c = temps[i]
        rh_pct = rhs[i]
        solar_wm2 = solars[i]
        wind_ms = winds[i]
        pressure_hpa = pressures[i]

        # Skip an hour entirely rather than writing nulls/fabricated values
        # if Open-Meteo returns a gap for this timestamp.
        if None in (temp_c, rh_pct, solar_wm2, wind_ms, pressure_hpa):
            continue

        tw = wet_bulb_stull(temp_c, rh_pct)
        wbgt = estimated_wbgt(
            dt_utc, city["lat"], city["lon"],
            solar_wm2=solar_wm2, pressure_hpa=pressure_hpa,
            tair_c=temp_c, rh_pct=rh_pct, wind_speed_ms=wind_ms,
            wind_speed_height_m=10.0,
        )

        hourly_out.append({
            "time_ist": t,
            "time_utc": dt_utc.isoformat(timespec="minutes"),
            "temp_c": temp_c,
            "rh_pct": rh_pct,
            "solar_wm2": solar_wm2,
            "wind_ms": wind_ms,
            "pressure_hpa": pressure_hpa,
            "wet_bulb_c": round(tw, 2),
            "wbgt_c": round(wbgt["Twbg"], 2) if wbgt["status"] == 0 else None,
            "wbgt_status": wbgt["status"],
            # Components behind the final WBGT number, so the UI can explain
            # *why* a city's WBGT is high (e.g. high solar + low wind vs. a
            # merely-hot dry-bulb reading) rather than just stating the value.
            "tglobe_c": round(wbgt["Tg"], 2) if wbgt["status"] == 0 else None,
            "tnwb_c": round(wbgt["Tnwb"], 2) if wbgt["status"] == 0 else None,
            "tpsy_c": round(wbgt["Tpsy"], 2) if wbgt["status"] == 0 else None,
            "est_wind_speed_ms": round(wbgt["est_speed"], 2) if wbgt["status"] == 0 else None,
        })

    return {
        "id": city["id"],
        "name": city["name"],
        "state": city["state"],
        "lat": city["lat"],
        "lon": city["lon"],
        "hourly": hourly_out,
    }


def main():
    cities = load_cities()
    print(f"Fetching forecast for {len(cities)} cities from Open-Meteo...")
    forecasts = fetch_forecast_batch(cities)

    records = []
    failed_convergence = 0
    for city, forecast in zip(cities, forecasts):
        record = build_city_record(city, forecast)
        records.append(record)
        failed_convergence += sum(
            1 for h in record["hourly"] if h["wbgt_status"] != 0
        )

    output = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Open-Meteo Forecast API (https://open-meteo.com/)",
        "cities": records,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    total_hours = sum(len(r["hourly"]) for r in records)
    print(f"Wrote {OUTPUT_PATH}: {len(records)} cities, {total_hours} city-hours.")
    if failed_convergence:
        print(f"WARNING: {failed_convergence} city-hours had WBGT solver non-convergence (wbgt_c=null).")


if __name__ == "__main__":
    main()
