"""
Tests for scripts/fetch_districts_daily.py's summarize() -- the per-district
daily aggregation behind the "workers at risk" map layer. Same synthetic-
extreme-conditions approach as the trends tests.
"""

from fetch_districts_daily import summarize

POINT = {"code": 999, "lat": 26.45, "lon": 80.33}  # Kanpur-ish

HOT = dict(temp=43.0, rh=55.0, solar=850.0, wind=1.0, pressure=1000.0)


def forecast(rows):
    """rows: list of (time_ist, cond_or_None) -> Open-Meteo forecast shape."""
    h = {"time": [], "temperature_2m": [], "relative_humidity_2m": [],
         "shortwave_radiation": [], "wind_speed_10m": [], "surface_pressure": []}
    for t, c in rows:
        h["time"].append(t)
        h["temperature_2m"].append(None if c is None else c["temp"])
        h["relative_humidity_2m"].append(50.0 if c is None else c["rh"])
        h["shortwave_radiation"].append(0.0 if c is None else c["solar"])
        h["wind_speed_10m"].append(1.0 if c is None else c["wind"])
        h["surface_pressure"].append(1000.0 if c is None else c["pressure"])
    return {"hourly": h}


def test_hot_shoulder_hour_counts_for_every_workload():
    s = summarize(POINT, forecast([("2026-05-15T09:00", HOT)]))
    assert s["valid"] == 1
    for key in ("light", "moderate", "heavy", "very-high"):
        assert s["o"][key] == 1, key
    assert s["max_wbgt"] is not None and s["max_wbgt"] > 30.0


def test_window_and_night_hours_are_not_overlooked():
    hot_night = dict(HOT, solar=0.0)
    s = summarize(POINT, forecast([
        ("2026-05-15T13:00", HOT),        # inside 11-5 window
        ("2026-05-15T23:00", hot_night),  # after dark
    ]))
    assert s["valid"] == 2
    assert s["o"]["heavy"] == 0
    assert s["max_wbgt"] is not None  # still tracked for the popup


def test_gap_hours_are_dropped_not_fabricated():
    s = summarize(POINT, forecast([("2026-05-15T09:00", None)]))
    assert s["valid"] == 0
    assert s["max_wbgt"] is None
    assert s["o"]["heavy"] == 0
