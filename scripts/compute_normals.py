"""
One-time script: builds the 1991-2020 same-calendar-date climatological
baseline used for the map's "anomaly vs normal" layer.

Pulls 30 years of hourly temperature + relative humidity per city from
Open-Meteo's Historical Weather API (ERA5), computes wet-bulb temperature
for every hour, then collapses each city's ~262,800 hourly readings down
to 366 calendar-date entries (mean and climatological-max temp/wet-bulb for
that date, averaged across all 30 years). The raw hourly pull (~7MB per
city, ~350MB total) is never written to disk or committed -- only the
small aggregated result (heat/data/normals.json) is kept.

This is NOT run on the 6-hourly schedule -- run it by hand, once, or
whenever the baseline needs rebuilding:

    python3 scripts/compute_normals.py

Takes several minutes (50 sequential API calls, ~7MB/2.5s each, with a
short pause between requests to avoid hammering Open-Meteo's free tier).
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime

import requests

from wbgt import wet_bulb_stull

HERE = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(HERE, "..", "heat", "data", "cities.json")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "normals.json")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE = "1991-01-01"
END_DATE = "2020-12-31"
REQUEST_PAUSE_SECONDS = 6.0  # be polite to the free API between per-city calls
MAX_RETRIES = 6


def load_cities():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_city_history(lat, lon):
    """Fetches with retry + exponential backoff on 429 (rate limit) -- the
    free Open-Meteo tier throttles bursts of requests even though the daily
    quota is generous, so a single 429 is expected, not a real failure."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "hourly": "temperature_2m,relative_humidity_2m",
        "timezone": "UTC",
    }
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(ARCHIVE_URL, params=params, timeout=120)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", delay))
            wait = max(retry_after, delay)
            print(f"(rate limited, waiting {wait:.0f}s, attempt {attempt}/{MAX_RETRIES}) ", end="", flush=True)
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Gave up after {MAX_RETRIES} retries (still rate limited) for lat={lat}, lon={lon}")


def aggregate_to_calendar_dates(history):
    """
    Collapses 30 years of hourly (temp, RH) readings into per-calendar-date
    stats: mean temp/wet-bulb across every hour of every year on that date,
    and the climatological max (average of each year's daily max on that
    date). Keyed by "MM-DD" (Feb 29 naturally gets fewer years averaged in --
    not a bug, just less data on leap days).
    """
    hourly = history["hourly"]
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    rhs = hourly["relative_humidity_2m"]

    # date_key -> list of hourly temps, list of hourly wet-bulbs
    by_date_hourly_temp = defaultdict(list)
    by_date_hourly_wetbulb = defaultdict(list)
    # date_key -> {year: [temps for that year's date]} to compute per-year daily max
    by_date_year_temp = defaultdict(lambda: defaultdict(list))
    by_date_year_wetbulb = defaultdict(lambda: defaultdict(list))

    for t, temp_c, rh_pct in zip(times, temps, rhs):
        if temp_c is None or rh_pct is None:
            continue
        dt = datetime.fromisoformat(t)
        date_key = dt.strftime("%m-%d")
        wb = wet_bulb_stull(temp_c, rh_pct)

        by_date_hourly_temp[date_key].append(temp_c)
        by_date_hourly_wetbulb[date_key].append(wb)
        by_date_year_temp[date_key][dt.year].append(temp_c)
        by_date_year_wetbulb[date_key][dt.year].append(wb)

    result = {}
    for date_key in by_date_hourly_temp:
        mean_temp = sum(by_date_hourly_temp[date_key]) / len(by_date_hourly_temp[date_key])
        mean_wb = sum(by_date_hourly_wetbulb[date_key]) / len(by_date_hourly_wetbulb[date_key])

        yearly_max_temps = [max(vals) for vals in by_date_year_temp[date_key].values()]
        yearly_max_wb = [max(vals) for vals in by_date_year_wetbulb[date_key].values()]
        climatological_max_temp = sum(yearly_max_temps) / len(yearly_max_temps)
        climatological_max_wb = sum(yearly_max_wb) / len(yearly_max_wb)

        result[date_key] = {
            "mean_temp_c": round(mean_temp, 2),
            "mean_wet_bulb_c": round(mean_wb, 2),
            "normal_max_temp_c": round(climatological_max_temp, 2),
            "normal_max_wet_bulb_c": round(climatological_max_wb, 2),
            "n_years": len(yearly_max_temps),
        }
    return result


def load_existing_output():
    """Resume support: if a previous run got partway through and crashed
    (e.g. hit a rate limit it couldn't recover from), don't re-fetch cities
    that already succeeded."""
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def main():
    cities = load_cities()
    print(f"Building 1991-2020 normals for {len(cities)} cities. This takes a few minutes.")

    existing = load_existing_output()
    output = existing if existing else {
        "period": f"{START_DATE} to {END_DATE}",
        "generated_at_utc": None,
        "source": "Open-Meteo Historical Weather API / ERA5 (https://open-meteo.com/)",
        "note": "Values are per-calendar-date (MM-DD) climatological normals, "
                "averaged across all years 1991-2020. wet_bulb values are "
                "Stull (2011) approximations computed from ERA5 hourly "
                "temperature and relative humidity.",
        "cities": {},
    }

    for i, city in enumerate(cities, start=1):
        city_key = str(city["id"])
        if city_key in output["cities"]:
            print(f"[{i}/{len(cities)}] {city['name']}... already done, skipping.")
            continue

        print(f"[{i}/{len(cities)}] {city['name']}...", end=" ", flush=True)
        history = fetch_city_history(city["lat"], city["lon"])
        normals = aggregate_to_calendar_dates(history)
        output["cities"][city_key] = {
            "name": city["name"],
            "normals_by_date": normals,
        }
        print(f"done ({len(normals)} calendar dates).")

        # Save after every city, not just at the end -- a crash mid-run
        # should never throw away already-fetched cities.
        output["generated_at_utc"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        time.sleep(REQUEST_PAUSE_SECONDS)

    print(f"Wrote {OUTPUT_PATH}: {len(output['cities'])}/{len(cities)} cities complete.")


if __name__ == "__main__":
    main()
