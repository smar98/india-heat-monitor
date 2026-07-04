"""
Data sanity gate for heat/data/latest.json. Run after fetch_forecast.py and
BEFORE committing the result -- in GitHub Actions this failing means the
workflow fails and the previous (valid) data stays live, rather than a
corrupt file silently replacing it.

Checks, per the project's "a data gap must never masquerade as no risk"
rule:
  - file parses, was generated recently (not a stale re-commit)
  - every city in cities.json is present exactly once, with >= 24 hours
  - hourly timestamps are contiguous (no silent gaps) in IST
  - every value sits inside a physically plausible range
  - wet-bulb never exceeds dry-bulb beyond Stull's documented error bound
  - wbgt_c is null exactly when the solver reported failure (status != 0)
  - the stored WBGT equals the ISO 7243 combination of its own stored
    components (0.7*Tnwb + 0.2*Tglobe + 0.1*Tair) -- an internal
    consistency check that would catch a pipeline mix-up between columns
  - solver failures are rare (<5% of city-hours)

Exits non-zero with a readable message on the first hard failure.

    python3 scripts/validate_latest.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(HERE, "..", "heat", "data", "cities.json")
LATEST_PATH = os.path.join(HERE, "..", "heat", "data", "latest.json")

MAX_AGE_HOURS = 12          # a 6-hourly pipeline should never produce older data
MIN_HOURS_PER_CITY = 24
MAX_SOLVER_FAILURE_FRACTION = 0.05

# Physically plausible ranges for Indian cities (wide on purpose -- these
# catch unit mix-ups and corruption, not unusual weather).
TEMP_RANGE_C = (-30.0, 55.0)
RH_RANGE_PCT = (0.0, 100.0)
WIND_RANGE_MS = (0.0, 60.0)
SOLAR_RANGE_WM2 = (0.0, 1300.0)
# Srinagar sits at ~1,600m elevation => surface pressure ~840 hPa, so the
# floor must be well below sea-level-ish values.
PRESSURE_RANGE_HPA = (780.0, 1080.0)
WBGT_RANGE_C = (-20.0, 55.0)

# Stull (2011) documents error bounds of -1.0/+0.65 C vs. true wet-bulb;
# true wet-bulb never exceeds dry-bulb, so approximated wet-bulb should
# never exceed dry-bulb by more than that positive error (plus rounding).
STULL_MAX_EXCESS_C = 0.7

# Stored wbgt_c must equal the ISO 7243 combination of its own stored
# components. Components are rounded to 2 decimals independently, so allow
# accumulated rounding of up to ~0.03.
WBGT_RECOMBINE_TOLERANCE_C = 0.03


def fail(msg):
    print(f"VALIDATION FAILED: {msg}")
    sys.exit(1)


def check_range(value, lo_hi, what, where):
    lo, hi = lo_hi
    if not (lo <= value <= hi):
        fail(f"{what}={value} outside plausible range [{lo}, {hi}] at {where}")


def main():
    with open(CITIES_PATH, encoding="utf-8") as f:
        cities = json.load(f)
    try:
        with open(LATEST_PATH, encoding="utf-8") as f:
            latest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        fail(f"could not read/parse latest.json: {e}")

    generated = datetime.fromisoformat(latest["generated_at_utc"])
    age = datetime.now(timezone.utc) - generated
    if age > timedelta(hours=MAX_AGE_HOURS):
        fail(f"data is {age} old (generated {latest['generated_at_utc']}) -- fetch step probably failed silently")
    if age < timedelta(0):
        fail(f"generated_at_utc {latest['generated_at_utc']} is in the future -- clock or timezone bug")

    expected_ids = {c["id"] for c in cities}
    seen_ids = [c["id"] for c in latest["cities"]]
    if len(seen_ids) != len(set(seen_ids)):
        fail("duplicate city ids in latest.json")
    missing = expected_ids - set(seen_ids)
    if missing:
        names = [c["name"] for c in cities if c["id"] in missing]
        fail(f"cities missing from latest.json: {names}")

    total_hours = 0
    failed_hours = 0
    for city in latest["cities"]:
        name = city["name"]
        hours = city["hourly"]
        if len(hours) < MIN_HOURS_PER_CITY:
            fail(f"{name}: only {len(hours)} hourly entries (< {MIN_HOURS_PER_CITY})")

        prev_ist = None
        for h in hours:
            where = f"{name} @ {h['time_ist']} IST"
            total_hours += 1

            # contiguity: each IST timestamp exactly 1h after the previous
            cur_ist = datetime.fromisoformat(h["time_ist"])
            if prev_ist is not None and cur_ist - prev_ist != timedelta(hours=1):
                fail(f"non-contiguous hourly timestamps at {where} (prev {prev_ist.isoformat()})")
            prev_ist = cur_ist

            check_range(h["temp_c"], TEMP_RANGE_C, "temp_c", where)
            check_range(h["rh_pct"], RH_RANGE_PCT, "rh_pct", where)
            check_range(h["wind_ms"], WIND_RANGE_MS, "wind_ms", where)
            check_range(h["solar_wm2"], SOLAR_RANGE_WM2, "solar_wm2", where)
            check_range(h["pressure_hpa"], PRESSURE_RANGE_HPA, "pressure_hpa", where)

            if h["wet_bulb_c"] > h["temp_c"] + STULL_MAX_EXCESS_C:
                fail(
                    f"wet_bulb_c={h['wet_bulb_c']} exceeds temp_c={h['temp_c']} "
                    f"by more than Stull's error bound at {where}"
                )

            if h["wbgt_status"] == 0:
                if h["wbgt_c"] is None:
                    fail(f"wbgt_status=0 but wbgt_c is null at {where}")
                check_range(h["wbgt_c"], WBGT_RANGE_C, "wbgt_c", where)
                for comp in ("tglobe_c", "tnwb_c", "tpsy_c"):
                    if h.get(comp) is None:
                        fail(f"wbgt_status=0 but {comp} is null at {where}")
                recombined = 0.7 * h["tnwb_c"] + 0.2 * h["tglobe_c"] + 0.1 * h["temp_c"]
                if abs(recombined - h["wbgt_c"]) > WBGT_RECOMBINE_TOLERANCE_C:
                    fail(
                        f"stored wbgt_c={h['wbgt_c']} does not equal 0.7*Tnwb+0.2*Tg+0.1*Tair"
                        f"={recombined:.3f} from its own stored components at {where}"
                    )
            else:
                failed_hours += 1
                if h["wbgt_c"] is not None:
                    fail(f"wbgt_status={h['wbgt_status']} but wbgt_c is not null at {where}")

    if total_hours == 0:
        fail("zero city-hours in latest.json")
    failure_fraction = failed_hours / total_hours
    if failure_fraction > MAX_SOLVER_FAILURE_FRACTION:
        fail(
            f"{failed_hours}/{total_hours} city-hours ({failure_fraction:.1%}) had WBGT solver "
            f"failures -- above the {MAX_SOLVER_FAILURE_FRACTION:.0%} threshold"
        )

    print(
        f"OK: {len(seen_ids)} cities, {total_hours} city-hours, "
        f"{failed_hours} solver failures ({failure_fraction:.2%}), "
        f"data age {age.total_seconds()/3600:.1f}h"
    )


if __name__ == "__main__":
    main()
