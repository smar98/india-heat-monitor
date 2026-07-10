"""
One-time script: builds the 1980-2024 "overlooked hours per year" history
used by the trend chart -- heat/data/trends.json.

For every city it pulls hourly ERA5 reanalysis (temperature, RH, shortwave
radiation, wind, surface pressure) from Open-Meteo's Historical Weather API,
computes estimated WBGT for every hour with the same Liljegren model the
live pipeline uses, and counts, per calendar year (IST) and per workload:

  - ovl    : hours >= the NIOSH REL, OUTSIDE the 11:00-16:59 IST
             afternoon-avoidance window, with the sun up (solar > 50 W/m2)
             -- the same "overlooked hour" definition as heat/js/data.js;
  - stress : hours >= the REL at any time of day;
  - days   : days with >= 1 overlooked hour;
  plus ovl at REL +/- 1 C (the site's WBGT-error sensitivity band).

Years: 1980-2024 (satellite-era ERA5 only -- pre-1979 reanalysis is weakest
in exactly the variables WBGT leans on, solar and wind). 2025 is excluded
because it is incomplete: a partial year would masquerade as a collapse in
an annual-count chart. The 11-5 window is TODAY'S audited HAP union applied
to past years -- the chart asks "how many hours would today's guidance
overlook," labeled as such on the page.

Cold-hour shortcut (rigorous): WBGT = 0.7*Tnwb + 0.2*Tg + 0.1*Ta with
Tnwb <= Ta and, generously, Tg <= Ta + 35 (the live pipeline's observed
maximum globe excess is 25.3 C; 35 adds margin). So WBGT <= Ta + 7, and any
hour with Ta < 16.5 C cannot reach the lowest threshold used here
(REL(581 W) - 1 = 23.9 C). Those hours skip the iterative solver but still
count as valid hours. Asserted at import time below.

Resumable: each (city x 5-year block) result is cached as aggregated year
counts in data/trends_cache/ (gitignored); rerunning skips completed
blocks. Expect on the order of a couple of hours end-to-end on the free
Open-Meteo tier (~450 requests with polite pauses + ~15M solver calls).

    python3 scripts/compute_trends.py
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from wbgt import estimated_wbgt, niosh_rel_c

HERE = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(HERE, "..", "heat", "data", "cities.json")
CACHE_DIR = os.path.join(HERE, "..", "data", "trends_cache")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "trends.json")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HOURLY_VARS = "temperature_2m,relative_humidity_2m,shortwave_radiation,wind_speed_10m,surface_pressure"

YEAR_START = 1980
YEAR_END = 2024  # inclusive; last COMPLETE year
BLOCK_YEARS = 5
REQUEST_PAUSE_SECONDS = 6.0  # be polite to the free API between calls
MAX_RETRIES = 6

IST_OFFSET = timedelta(hours=5, minutes=30)

# Must mirror heat/js/data.js exactly.
WORKLOADS = [("light", 209.0), ("moderate", 349.0), ("heavy", 465.0), ("very-high", 581.0)]
HAP_WINDOW_START = 11
HAP_WINDOW_END = 17
SUN_UP_WM2 = 50.0

# Cold-hour solver skip (see module docstring).
SKIP_BELOW_TA_C = 16.5
_MIN_THRESHOLD = min(niosh_rel_c(w) for _, w in WORKLOADS) - 1.0
assert SKIP_BELOW_TA_C + 7.0 < _MIN_THRESHOLD, "cold-hour skip bound is not conservative"


def load_cities():
    with open(CITIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def year_blocks():
    blocks = []
    y = YEAR_START
    while y <= YEAR_END:
        blocks.append((y, min(y + BLOCK_YEARS - 1, YEAR_END)))
        y += BLOCK_YEARS
    return blocks


def fetch_block(lat, lon, y0, y1):
    """One archive request for one city and a block of whole years, in IST
    calendar time. Retries with backoff on 429 (free-tier throttling)."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{y0}-01-01",
        "end_date": f"{y1}-12-31",
        "hourly": HOURLY_VARS,
        "timezone": "Asia/Kolkata",  # IST calendar days, like the live pipeline
        "wind_speed_unit": "ms",
    }
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        # Transient network failures (DNS blips, dropped connections) get the
        # same backoff as 429s -- a multi-hour run WILL hit at least one, and
        # an unhandled one previously killed the run 25 blocks from the end.
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=180)
        except (requests.ConnectionError, requests.Timeout) as e:
            print(f"(network error, waiting {delay:.0f}s, attempt {attempt}/{MAX_RETRIES}: {e.__class__.__name__}) ",
                  end="", flush=True)
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429:
            wait = max(float(resp.headers.get("Retry-After", delay)), delay)
            print(f"(429, waiting {wait:.0f}s, attempt {attempt}/{MAX_RETRIES}) ", end="", flush=True)
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"still failing after {MAX_RETRIES} retries (lat={lat}, lon={lon}, {y0}-{y1})")


def aggregate_hours(hourly, lat, lon):
    """Aggregates one block's hourly arrays into per-year counts.

    hourly: the Open-Meteo "hourly" dict (time + the 5 variable arrays,
    time labeled in IST). Returns {year: {"valid": n, "skipped_cold": n,
    "<workload>": {"ovl": n, "stress": n, "days": n, "ovl_hi": n,
    "ovl_lo": n}}} where hi/lo are the REL+1/REL-1 variants.
    """
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    rhs = hourly["relative_humidity_2m"]
    solars = hourly["shortwave_radiation"]
    winds = hourly["wind_speed_10m"]
    pressures = hourly["surface_pressure"]

    thresholds = {key: niosh_rel_c(watts) for key, watts in WORKLOADS}
    years = {}
    ovl_days = {}  # (year, workload_key) -> set of date keys

    for i, t in enumerate(times):
        temp_c, rh_pct = temps[i], rhs[i]
        solar_wm2, wind_ms, pressure_hpa = solars[i], winds[i], pressures[i]
        if None in (temp_c, rh_pct, solar_wm2, wind_ms, pressure_hpa):
            continue  # skip gaps rather than fabricate (same as the live pipeline)

        year = int(t[0:4])
        date_key = t[0:10]
        ist_hour = int(t[11:13])
        y = years.setdefault(year, {"valid": 0, "skipped_cold": 0})
        y["valid"] += 1

        if temp_c < SKIP_BELOW_TA_C:
            # Provably below every threshold used here -- skip the solver.
            y["skipped_cold"] += 1
            continue

        dt_ist = datetime.fromisoformat(t)  # naive IST wall-clock
        dt_utc = (dt_ist - IST_OFFSET).replace(tzinfo=timezone.utc)
        result = estimated_wbgt(
            dt_utc, lat, lon,
            solar_wm2=solar_wm2, pressure_hpa=pressure_hpa,
            tair_c=temp_c, rh_pct=rh_pct, wind_speed_ms=wind_ms,
            wind_speed_height_m=10.0,
        )
        if result["status"] != 0:
            continue  # solver non-convergence: no estimate, not a zero
        wbgt = round(result["Twbg"], 2)  # live pipeline stores 2 dp; compare like-for-like

        inside_window = HAP_WINDOW_START <= ist_hour < HAP_WINDOW_END
        sun_up = solar_wm2 > SUN_UP_WM2
        is_shoulder = (not inside_window) and sun_up

        for key, rel in thresholds.items():
            w = y.setdefault(key, {"ovl": 0, "stress": 0, "days": 0, "ovl_hi": 0, "ovl_lo": 0})
            if wbgt >= rel:
                w["stress"] += 1
                if is_shoulder:
                    w["ovl"] += 1
                    ovl_days.setdefault((year, key), set()).add(date_key)
            if is_shoulder:
                # Sensitivity band: hi = stricter limit (rel+1, fewer hours),
                # lo = looser (rel-1, more hours) -- matches the headline band.
                if wbgt >= rel + 1.0:
                    w["ovl_hi"] += 1
                if wbgt >= rel - 1.0:
                    w["ovl_lo"] += 1

    for (year, key), days in ovl_days.items():
        years[year][key]["days"] = len(days)
    return years


def cache_path(city_id, y0, y1):
    return os.path.join(CACHE_DIR, f"{city_id}_{y0}_{y1}.json")


def main():
    cities = load_cities()
    blocks = year_blocks()
    os.makedirs(CACHE_DIR, exist_ok=True)
    total_jobs = len(cities) * len(blocks)
    done = 0

    for city in cities:
        for (y0, y1) in blocks:
            done += 1
            path = cache_path(city["id"], y0, y1)
            if os.path.exists(path):
                continue
            t0 = time.time()
            print(f"[{done}/{total_jobs}] {city['name']} {y0}-{y1}: fetching... ", end="", flush=True)
            data = fetch_block(city["lat"], city["lon"], y0, y1)
            t_fetch = time.time() - t0
            print(f"({t_fetch:.0f}s) computing... ", end="", flush=True)
            years = aggregate_hours(data["hourly"], city["lat"], city["lon"])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(years, f)
            print(f"done ({time.time() - t0:.0f}s total)")
            time.sleep(REQUEST_PAUSE_SECONDS)

    # ---- assemble trends.json from the cache ----
    year_list = list(range(YEAR_START, YEAR_END + 1))
    out_cities = {}
    for city in cities:
        merged = {}
        for (y0, y1) in blocks:
            with open(cache_path(city["id"], y0, y1), "r", encoding="utf-8") as f:
                merged.update({int(k): v for k, v in json.load(f).items()})
        city_out = {"valid": [merged.get(y, {}).get("valid", 0) for y in year_list]}
        for key, _watts in WORKLOADS:
            def series(stat, k=key):
                return [merged.get(y, {}).get(k, {}).get(stat, 0) for y in year_list]
            city_out[key] = {
                "ovl": series("ovl"),
                "ovl_hi": series("ovl_hi"),
                "ovl_lo": series("ovl_lo"),
                "stress": series("stress"),
                "days": series("days"),
            }
        out_cities[str(city["id"])] = city_out

    output = {
        "meta": {
            "source": "Open-Meteo Historical Weather API (ERA5), https://open-meteo.com/",
            "years": [YEAR_START, YEAR_END],
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "definition": (
                "ovl = hours/year with estimated WBGT >= the NIOSH REL for the workload, "
                "outside the current 11:00-16:59 IST avoidance window, with solar > 50 W/m2 "
                "(IST calendar). ovl_hi/ovl_lo = same at REL +1/-1 C. stress = all hours >= REL. "
                "days = days/year with >= 1 overlooked hour. valid = hours with complete data. "
                "2025 excluded (incomplete year). Same Liljegren/Stull/NIOSH code path as the "
                "live pipeline; the avoidance window is today's audited HAP union applied "
                "to all years."
            ),
        },
        "years": year_list,
        "cities": out_cities,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))
    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"Wrote {OUTPUT_PATH} ({size_kb:.0f} KB, {len(out_cities)} cities, {len(year_list)} years)")


if __name__ == "__main__":
    main()
