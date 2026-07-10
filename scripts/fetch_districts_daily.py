"""
Daily district heat summary: for each of the 640 Census-2011 districts,
fetches today's hourly forecast at the district's representative point,
computes estimated WBGT for every hour, and writes ONLY the per-district
aggregates the map layer needs -- overlooked-hours count per workload and
the day's peak WBGT -- to heat/data/districts_daily.json (~40KB; no hourly
arrays, so the page payload stays small).

Definitions mirror heat/js/data.js exactly: an hour is "overlooked" when
estimated WBGT >= the NIOSH REL for that workload, the IST hour is outside
11:00-16:59, and solar > 50 W/m2 (sun up).

Run once daily by .github/workflows/update-districts.yml (early-morning
IST, so the day's forecast is fresh for Indian daylight hours). ~8 batched
Open-Meteo calls per run. By hand:

    python3 scripts/fetch_districts_daily.py
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from wbgt import estimated_wbgt, niosh_rel_c

HERE = os.path.dirname(os.path.abspath(__file__))
POINTS_PATH = os.path.join(HERE, "..", "heat", "data", "district_points.json")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "districts_daily.json")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "temperature_2m,relative_humidity_2m,shortwave_radiation,wind_speed_10m,surface_pressure"
CHUNK_SIZE = 80          # 640 points -> 8 requests
REQUEST_PAUSE_S = 2.0
MAX_RETRIES = 5

IST_OFFSET = timedelta(hours=5, minutes=30)

# Must mirror heat/js/data.js.
WORKLOADS = {"light": 209.0, "moderate": 349.0, "heavy": 465.0, "very-high": 581.0}
HAP_WINDOW_START = 11
HAP_WINDOW_END = 17
SUN_UP_WM2 = 50.0


def fetch_chunk(points):
    params = {
        "latitude": ",".join(str(p["lat"]) for p in points),
        "longitude": ",".join(str(p["lon"]) for p in points),
        "hourly": HOURLY_VARS,
        "forecast_days": 1,               # today's IST calendar day
        "timezone": "Asia/Kolkata",
        "wind_speed_unit": "ms",
    }
    delay = 5.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(FORECAST_URL, params=params, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as e:
            print(f"(network error, retry {attempt}/{MAX_RETRIES}: {e.__class__.__name__}) ",
                  end="", flush=True)
            time.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429:
            wait = max(float(resp.headers.get("Retry-After", delay)), delay)
            print(f"(429, waiting {wait:.0f}s) ", end="", flush=True)
            time.sleep(wait)
            delay *= 2
            continue
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(points):
            raise RuntimeError(f"got {len(data)} results for {len(points)} points")
        return data
    raise RuntimeError(f"chunk still failing after {MAX_RETRIES} retries")


def summarize(point, forecast):
    hourly = forecast["hourly"]
    rels = {key: niosh_rel_c(watts) for key, watts in WORKLOADS.items()}
    ovl = {key: 0 for key in WORKLOADS}
    max_wbgt = None
    valid = 0
    for i, t in enumerate(hourly["time"]):
        vals = [hourly[v][i] for v in ("temperature_2m", "relative_humidity_2m",
                                       "shortwave_radiation", "wind_speed_10m",
                                       "surface_pressure")]
        if any(v is None for v in vals):
            continue
        temp_c, rh_pct, solar_wm2, wind_ms, pressure_hpa = vals
        dt_utc = (datetime.fromisoformat(t) - IST_OFFSET).replace(tzinfo=timezone.utc)
        result = estimated_wbgt(dt_utc, point["lat"], point["lon"],
                                solar_wm2=solar_wm2, pressure_hpa=pressure_hpa,
                                tair_c=temp_c, rh_pct=rh_pct, wind_speed_ms=wind_ms,
                                wind_speed_height_m=10.0)
        if result["status"] != 0:
            continue
        valid += 1
        wbgt = round(result["Twbg"], 2)
        if max_wbgt is None or wbgt > max_wbgt:
            max_wbgt = wbgt
        ist_hour = int(t[11:13])
        inside = HAP_WINDOW_START <= ist_hour < HAP_WINDOW_END
        if not inside and solar_wm2 > SUN_UP_WM2:
            for key, rel in rels.items():
                if wbgt >= rel:
                    ovl[key] += 1
    return {"o": ovl, "max_wbgt": max_wbgt, "valid": valid}


def main():
    with open(POINTS_PATH, "r", encoding="utf-8") as f:
        points = json.load(f)

    districts = {}
    for start in range(0, len(points), CHUNK_SIZE):
        chunk = points[start:start + CHUNK_SIZE]
        print(f"chunk {start // CHUNK_SIZE + 1}/{(len(points) - 1) // CHUNK_SIZE + 1}: "
              f"{len(chunk)} districts... ", end="", flush=True)
        forecasts = fetch_chunk(chunk)
        for point, forecast in zip(chunk, forecasts):
            districts[str(point["code"])] = summarize(point, forecast)
        print("ok")
        time.sleep(REQUEST_PAUSE_S)

    # Validation gate: refuse to write a file the map can't trust.
    if len(districts) != len(points):
        print(f"FATAL: {len(districts)} summaries for {len(points)} districts")
        sys.exit(1)
    no_data = [c for c, d in districts.items() if d["valid"] < 20 or d["max_wbgt"] is None]
    if len(no_data) > len(points) * 0.02:
        print(f"FATAL: {len(no_data)} districts with insufficient valid hours: {no_data[:10]}")
        sys.exit(1)
    bad = [c for c, d in districts.items()
           if d["max_wbgt"] is not None and not (-10.0 < d["max_wbgt"] < 45.0)]
    if bad:
        print(f"FATAL: implausible max WBGT in districts {bad[:10]}")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc)
    output = {
        "generated_at_utc": now_utc.isoformat(timespec="seconds"),
        "ist_date": (now_utc + IST_OFFSET).strftime("%Y-%m-%d"),
        "source": "Open-Meteo Forecast API (https://open-meteo.com/)",
        "districts": districts,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, separators=(",", ":"))
    worst = max(districts.values(), key=lambda d: d["o"]["heavy"])
    print(f"Wrote {OUTPUT_PATH}: {len(districts)} districts "
          f"({os.path.getsize(OUTPUT_PATH) // 1024} KB); "
          f"max heavy-work overlooked hours today: {worst['o']['heavy']}.")


if __name__ == "__main__":
    main()
