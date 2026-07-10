"""
Tests for scripts/fetch_alerts.py -- the official-heat-alert logger.

Covers the pure logic only (parsing, geometry matching, the our-side signal
definition, dedupe); network fetching is exercised by running the script
itself. The CAP fixture polygon is the real Uttarakhand/West-UP polygon from
an actual IMD alert (2026-07-09), with the event swapped to "Heat Wave" so it
passes the heat filter -- the geometry and structure are the real format.
"""

import json
from datetime import datetime, timezone

import pytest

from fetch_alerts import (
    alert_is_active,
    compute_city_signal,
    disambiguate_latlon,
    haversine_km,
    is_heat_event,
    load_seen_ids,
    parse_cap_alert,
    parse_sachet_ist_time,
    parse_sachet_record,
    point_in_polygon,
)
from wbgt import niosh_rel_c

# Real polygon from IMD CAP alert urn:oid:2.49.0.1.356.0.2026.7.9.10.40.50
# (Uttarakhand + West Uttar Pradesh), lat,lon pairs.
UTTARAKHAND_POLY_TEXT = (
    "31.2786,78.9697 31.0906,78.1348 30.2970,77.6514 29.5735,77.1240 "
    "28.7677,77.3438 28.1495,77.7832 27.4108,77.3877 26.8633,77.9590 "
    "26.0370,78.7500 25.5623,79.8926 26.3919,80.3320 27.9168,79.1895 "
    "28.6135,79.6289 29.2672,79.9805 30.1831,80.4199 30.1831,81.0791 "
    "31.0153,79.4971 31.2786,78.9697"
)
UTTARAKHAND_POLY = [
    [float(a), float(b)]
    for a, b in (pair.split(",") for pair in UTTARAKHAND_POLY_TEXT.split())
]

CAP_HEAT_FIXTURE = f"""<?xml version="1.0" encoding="UTF-8"?>
<cap:alert xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <cap:identifier>urn:oid:2.49.0.1.356.0.2026.7.9.10.40.50</cap:identifier>
  <cap:sender>rainfallnwfc@gmail.com</cap:sender>
  <cap:sent>2026-07-09T16:10:50+05:30</cap:sent>
  <cap:status>Actual</cap:status>
  <cap:msgType>Alert</cap:msgType>
  <cap:scope>Public</cap:scope>
  <cap:info>
    <cap:language>en</cap:language>
    <cap:category>Met</cap:category>
    <cap:event>Heat Wave</cap:event>
    <cap:severity>Severe</cap:severity>
    <cap:onset>2026-07-09T03:00:00+05:30</cap:onset>
    <cap:expires>2026-07-10T00:00:00+05:30</cap:expires>
    <cap:senderName>NWFC DIVISION, IMD, NEW DELHI</cap:senderName>
    <cap:area>
      <cap:areaDesc>Uttarakhand and West Uttar Pradesh.</cap:areaDesc>
      <cap:polygon>{UTTARAKHAND_POLY_TEXT}</cap:polygon>
    </cap:area>
  </cap:info>
</cap:alert>"""

CAP_RAIN_FIXTURE = CAP_HEAT_FIXTURE.replace(
    "<cap:event>Heat Wave</cap:event>",
    "<cap:event>Heavy to very heavy rainfall</cap:event>",
)


# ---------------------------------------------------------------- filtering

def test_heat_keyword_filter():
    for text in ["Heat Wave", "Severe Heat Wave", "heatwave", "Hot Day",
                 "Hot and humid weather", "Warm Night"]:
        assert is_heat_event(text), text
    for text in ["Heavy to very heavy rainfall", "Lightning", "Thunderstorm",
                 "Cold Wave", None, ""]:
        assert not is_heat_event(text), text


# ----------------------------------------------------------------- geometry

def test_point_in_polygon_square():
    square = [[10.0, 70.0], [10.0, 80.0], [20.0, 80.0], [20.0, 70.0]]
    assert point_in_polygon(15.0, 75.0, square)          # center
    assert not point_in_polygon(25.0, 75.0, square)      # north of it
    assert not point_in_polygon(15.0, 85.0, square)      # east of it


def test_point_in_polygon_real_imd_shape():
    # Dehradun sits inside the Uttarakhand alert polygon; Mumbai far outside.
    assert point_in_polygon(30.3165, 78.0322, UTTARAKHAND_POLY)
    assert not point_in_polygon(19.0760, 72.8777, UTTARAKHAND_POLY)


def test_haversine_known_distance():
    # Delhi to Mumbai is ~1150 km great-circle.
    d = haversine_km(28.6139, 77.2090, 19.0760, 72.8777)
    assert 1100 < d < 1200


def test_disambiguate_latlon_both_orders():
    # SACHET's observed lon-first order gets flipped...
    assert disambiguate_latlon(79.82, 13.41) == (13.41, 79.82)
    # ...lat-first passes through...
    assert disambiguate_latlon(13.41, 79.82) == (13.41, 79.82)
    # ...and garbage is refused rather than guessed.
    assert disambiguate_latlon(200.0, 300.0) is None


# ------------------------------------------------------------------ parsing

def test_parse_sachet_ist_time_to_utc():
    dt = parse_sachet_ist_time("Thu Jul 09 17:55:00 IST 2026")
    assert dt == datetime(2026, 7, 9, 12, 25, 0, tzinfo=timezone.utc)
    assert parse_sachet_ist_time("not a time") is None
    assert parse_sachet_ist_time(None) is None


def test_parse_sachet_record_heat_with_circle_geometry():
    rec = {
        "identifier": 12345,
        "disaster_type": "Heat Wave",
        "severity_level": "Likely",
        "effective_start_time": "Thu Jul 09 10:00:00 IST 2026",
        "effective_end_time": "Thu Jul 09 18:00:00 IST 2026",
        "area_description": "some mandals",
        "alert_source": "Andhra Pradesh SDMA",
        "centroid": "79.82072174920728,13.415551395851251",  # lon-first, as observed
        "area_covered": "292.47",
    }
    parsed = parse_sachet_record(rec)
    assert parsed["source"] == "sachet"
    assert parsed["id"] == "12345"
    assert parsed["match_method"] == "circle-approx"
    geom = parsed["match_geom"]
    assert geom["type"] == "circle"
    assert geom["lat"] == pytest.approx(13.4156, abs=1e-3)
    assert geom["lon"] == pytest.approx(79.8207, abs=1e-3)
    # r = sqrt(292.47 / pi) ~ 9.65 km
    assert geom["radius_km"] == pytest.approx(9.65, abs=0.05)
    assert parsed["start_utc"] == "2026-07-09T04:30:00+00:00"
    assert parsed["end_utc"] == "2026-07-09T12:30:00+00:00"


def test_parse_sachet_record_non_heat_is_dropped():
    assert parse_sachet_record({"disaster_type": "Lightning"}) is None


def test_parse_sachet_record_garbage_geometry_never_guesses():
    rec = {"identifier": 1, "disaster_type": "Heat Wave",
           "centroid": "garbage", "area_covered": "not-a-number"}
    parsed = parse_sachet_record(rec)
    assert parsed["match_geom"] is None
    assert parsed["match_method"] == "none"


def test_parse_cap_alert_heat_fixture():
    parsed = parse_cap_alert(CAP_HEAT_FIXTURE, source_url="https://example/x.xml")
    assert parsed["source"] == "imd-cap"
    assert parsed["id"] == "urn:oid:2.49.0.1.356.0.2026.7.9.10.40.50"
    assert parsed["event"] == "Heat Wave"
    assert parsed["severity"] == "Severe"
    assert parsed["match_method"] == "polygon"
    polys = parsed["match_geom"]["polygons"]
    assert len(polys) == 1 and len(polys[0]) == 18
    # onset 03:00 IST = 21:30 UTC previous day; expires 00:00 IST = 18:30 UTC
    assert parsed["start_utc"] == "2026-07-08T21:30:00+00:00"
    assert parsed["end_utc"] == "2026-07-09T18:30:00+00:00"
    assert "IMD" in parsed["issuer"]


def test_parse_cap_alert_rainfall_is_dropped():
    assert parse_cap_alert(CAP_RAIN_FIXTURE) is None


# ----------------------------------------------------------- active windows

def test_alert_is_active_bounds():
    alert = {"start_utc": "2026-07-09T04:00:00+00:00",
             "end_utc": "2026-07-09T12:00:00+00:00"}
    inside = datetime(2026, 7, 9, 8, 0, tzinfo=timezone.utc)
    before = datetime(2026, 7, 9, 3, 0, tzinfo=timezone.utc)
    after = datetime(2026, 7, 9, 13, 0, tzinfo=timezone.utc)
    assert alert_is_active(alert, inside)
    assert not alert_is_active(alert, before)
    assert not alert_is_active(alert, after)
    # missing bounds are treated as open
    assert alert_is_active({"start_utc": None, "end_utc": None}, inside)
    assert alert_is_active({"start_utc": "2026-07-09T04:00:00+00:00",
                            "end_utc": None}, after)


# ---------------------------------------------------- our-side signal maths

def _hour(time_ist, wbgt_c, solar_wm2, status=0):
    return {"time_ist": time_ist, "wbgt_c": wbgt_c, "wbgt_status": status,
            "solar_wm2": solar_wm2}


def test_compute_city_signal_mirrors_frontend_definition():
    rel = niosh_rel_c(465.0)  # ~26.02 C, the dashboard's Heavy default
    hourly = [
        _hour("2026-07-09T09:00", rel + 1.0, 400.0),   # above, outside window, sun up -> overlooked
        _hour("2026-07-09T13:00", rel + 2.0, 800.0),   # above, INSIDE window -> not overlooked
        _hour("2026-07-09T22:00", rel + 0.5, 0.0),     # above, dark -> not overlooked
        _hour("2026-07-09T10:00", rel - 5.0, 300.0),   # below the limit
        _hour("2026-07-09T11:00", rel + 3.0, 900.0, status=1),  # non-converged: ignored
        _hour("2026-07-10T09:00", rel + 9.0, 400.0),   # tomorrow: ignored
    ]
    signal = compute_city_signal(hourly, "2026-07-09", rel)
    assert signal["hours_above_rel"] == 3
    assert signal["overlooked_hours"] == 1
    assert signal["max_wbgt_c"] == pytest.approx(rel + 2.0)


def test_compute_city_signal_boundary_hours_use_window_semantics():
    # 11:00 is inside the window (inclusive start); 17:00 is outside
    # (exclusive end) -- must match isInsideHapWindow in data.js.
    rel = 26.0
    hourly = [
        _hour("2026-07-09T11:00", 30.0, 900.0),
        _hour("2026-07-09T17:00", 30.0, 400.0),
    ]
    signal = compute_city_signal(hourly, "2026-07-09", rel)
    assert signal["hours_above_rel"] == 2
    assert signal["overlooked_hours"] == 1  # only the 17:00 hour


def test_compute_city_signal_at_rel_exactly_counts_as_stress():
    # data.js: `if (h.wbgt_c < relThreshold) continue;` -- equality IS stress.
    hourly = [_hour("2026-07-09T09:00", 26.0, 400.0)]
    signal = compute_city_signal(hourly, "2026-07-09", 26.0)
    assert signal["hours_above_rel"] == 1


def test_compute_city_signal_empty_day():
    signal = compute_city_signal([], "2026-07-09", 26.0)
    assert signal == {"hours_above_rel": 0, "overlooked_hours": 0,
                      "max_wbgt_c": None}


# ------------------------------------------------------------------- dedupe

def test_load_seen_ids_dedupe_and_corrupt_line_tolerance(tmp_path):
    raw = tmp_path / "2026-07.jsonl"
    raw.write_text(
        json.dumps({"source": "sachet", "id": "1"}) + "\n"
        + "{corrupt json line\n"
        + json.dumps({"source": "imd-cap", "id": "urn:x"}) + "\n",
        encoding="utf-8",
    )
    seen = load_seen_ids(str(raw))
    assert seen == {("sachet", "1"), ("imd-cap", "urn:x")}
    assert load_seen_ids(str(tmp_path / "missing.jsonl")) == set()
