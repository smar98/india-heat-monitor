"""
Logs active OFFICIAL heat alerts alongside our own REL-exceedance record,
once per pipeline run. This is a data-collection step only -- nothing on the
site reads these files yet. The point: months from now, the log can answer
"on days our estimated-WBGT record flagged heat stress in city X, was any
official heat alert active there?" using REAL warnings, not an approximation
of IMD's declaration criteria.

Sources (both public, no keys; verified live 2026-07-09):
  - SACHET, NDMA's Common Alerting Protocol portal (includes state-SDMA
    alerts): GET https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails
  - IMD's official CAP 1.2 alerts, via the Google alert-hub mirror of IMD's
    signed feed: https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml
    (each RSS item links a per-alert XML that carries real lat,lon polygons,
    so city matching is exact point-in-polygon).
  IMD's own district-warning API (mausam.imd.gov.in/api/...) is auth-walled
  (401) and is deliberately NOT used.

Outputs (append-only monthly JSONL, at repo root under data/alerts/ -- not
under heat/, because the page does not serve these):
  - data/alerts/raw/YYYY-MM.jsonl     one line per NEWLY SEEN heat-related
                                      alert (deduped by (source, id) within
                                      the month), full normalized record
                                      including its geometry.
  - data/alerts/citylog/YYYY-MM.jsonl one line PER RUN: for every city, the
                                      REL-exceedance signal for today (IST)
                                      plus the ids of any active heat alerts
                                      covering it. A run with zero alerts
                                      anywhere still writes a full line --
                                      "no official alert while we flagged
                                      stress" is exactly the record we want.

Failure policy: this script must NEVER block the heat-data pipeline. Every
network fetch is isolated; any unhandled error is printed and the process
still exits 0. Source failures are recorded in the citylog line
(alert_sources_ok) so gaps are distinguishable from genuinely quiet days.

Run by .github/workflows/update-data.yml AFTER fetch_forecast.py (it reads
the freshly written latest.json). By hand, from the repo root:

    python3 scripts/fetch_alerts.py
"""

import json
import math
import os
import sys
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from wbgt import niosh_rel_c

HERE = os.path.dirname(os.path.abspath(__file__))
CITIES_PATH = os.path.join(HERE, "..", "heat", "data", "cities.json")
LATEST_PATH = os.path.join(HERE, "..", "heat", "data", "latest.json")
ALERTS_DIR = os.path.join(HERE, "..", "data", "alerts")

SACHET_URL = "https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails"
IMD_CAP_RSS_URL = "https://cap-sources.s3.amazonaws.com/in-imd-en/rss.xml"
CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

# An alert is "heat-related" if its event/disaster-type text contains any of
# these (case-insensitive). Matches IMD's own heat vocabulary: "Heat Wave",
# "Severe Heat Wave", "Hot day", "Hot and humid weather", "Warm night".
HEAT_KEYWORDS = ("heat", "hot day", "hot and humid", "warm night")

REQUEST_TIMEOUT_S = 30
MAX_CAP_ALERT_FETCHES = 300  # the RSS index is small; this is a safety cap

IST_OFFSET = timedelta(hours=5, minutes=30)

# --- Our-side signal definition. MUST mirror heat/js/data.js exactly:
#     WORKLOAD_LEVELS heavy = 465 W (the dashboard default), stress when
#     wbgt_c >= REL, HAP window 11:00-16:59 IST, sun up when solar > 50 W/m2,
#     valid hour when wbgt_status == 0 and wbgt_c is not null.
HEAVY_WATTS = 465.0
HAP_WINDOW_START = 11  # inclusive IST hour
HAP_WINDOW_END = 17    # exclusive IST hour
SUN_UP_WM2 = 50.0

# India bounding ranges used ONLY to disambiguate SACHET's undocumented
# "a,b" centroid field (observed lon-first, but never assumed): latitudes
# and longitudes over India do not overlap, so exactly one assignment fits.
INDIA_LAT_RANGE = (6.0, 37.5)
INDIA_LON_RANGE = (68.0, 98.0)


def is_heat_event(text):
    """True if an alert's event/disaster-type text looks heat-related."""
    if not text:
        return False
    lowered = str(text).lower()
    return any(k in lowered for k in HEAT_KEYWORDS)


def parse_sachet_ist_time(s):
    """SACHET timestamps look like 'Thu Jul 09 17:55:00 IST 2026' (IST
    wall-clock). Returns an aware UTC datetime, or None if unparseable."""
    if not s:
        return None
    try:
        naive_ist = datetime.strptime(str(s).replace(" IST", ""), "%a %b %d %H:%M:%S %Y")
        return (naive_ist - IST_OFFSET).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def disambiguate_latlon(a, b):
    """Given two floats in unknown (lat,lon)/(lon,lat) order, return (lat, lon)
    if exactly one assignment fits India's ranges, else None (never guess)."""
    def fits(lat, lon):
        return (INDIA_LAT_RANGE[0] <= lat <= INDIA_LAT_RANGE[1]
                and INDIA_LON_RANGE[0] <= lon <= INDIA_LON_RANGE[1])
    ab, ba = fits(a, b), fits(b, a)
    if ab and not ba:
        return (a, b)
    if ba and not ab:
        return (b, a)
    return None


def parse_sachet_record(rec):
    """Normalizes one SACHET JSON record; returns None if not heat-related.
    Geometry: SACHET gives a centroid plus an area_covered (km^2), so coverage
    is approximated as a circle of equal area -- recorded as such."""
    if not is_heat_event(rec.get("disaster_type")):
        return None

    match_geom = None
    centroid = rec.get("centroid") or ""
    try:
        parts = [float(p) for p in str(centroid).split(",")]
    except ValueError:
        parts = []
    if len(parts) == 2:
        latlon = disambiguate_latlon(parts[0], parts[1])
        if latlon:
            radius_km = None
            try:
                area = float(rec.get("area_covered"))
                if area > 0:
                    radius_km = math.sqrt(area / math.pi)
            except (TypeError, ValueError):
                pass
            if radius_km:
                match_geom = {"type": "circle", "lat": latlon[0], "lon": latlon[1],
                              "radius_km": round(radius_km, 2)}

    start = parse_sachet_ist_time(rec.get("effective_start_time"))
    end = parse_sachet_ist_time(rec.get("effective_end_time"))
    return {
        "source": "sachet",
        "id": str(rec.get("identifier")),
        "event": rec.get("disaster_type"),
        "severity": rec.get("severity_level") or rec.get("severity"),
        "start_utc": start.isoformat(timespec="seconds") if start else None,
        "end_utc": end.isoformat(timespec="seconds") if end else None,
        "area_desc": rec.get("area_description"),
        "issuer": rec.get("alert_source"),
        "match_geom": match_geom,
        "match_method": "circle-approx" if match_geom else "none",
    }


def _cap(tag):
    return f"{{{CAP_NS}}}{tag}"


def parse_cap_alert(xml_text, source_url=None):
    """Parses one CAP 1.2 alert XML (IMD's format); returns a normalized dict,
    or None if the alert is not heat-related. Collects every polygon and
    circle across all <info>/<area> blocks."""
    root = ET.fromstring(xml_text)
    infos = root.findall(_cap("info"))
    if not infos:
        return None

    heat_infos = [i for i in infos if is_heat_event(i.findtext(_cap("event")))]
    if not heat_infos:
        return None

    def parse_iso(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    polygons, circles, area_descs = [], [], []
    onsets, expires_list, events, severities = [], [], [], []
    for info in heat_infos:
        events.append(info.findtext(_cap("event")))
        severities.append(info.findtext(_cap("severity")))
        onsets.append(parse_iso(info.findtext(_cap("onset"))
                                or info.findtext(_cap("effective"))))
        expires_list.append(parse_iso(info.findtext(_cap("expires"))))
        for area in info.findall(_cap("area")):
            desc = area.findtext(_cap("areaDesc"))
            if desc:
                area_descs.append(desc)
            for poly_el in area.findall(_cap("polygon")):
                coords = []
                for pair in (poly_el.text or "").split():
                    try:
                        lat_s, lon_s = pair.split(",")
                        coords.append([float(lat_s), float(lon_s)])  # CAP is lat,lon
                    except ValueError:
                        coords = []
                        break
                if len(coords) >= 3:
                    polygons.append(coords)
            for circ_el in area.findall(_cap("circle")):
                # CAP circle: "lat,lon radius" with radius in kilometres
                try:
                    center_s, radius_s = (circ_el.text or "").split()
                    lat_s, lon_s = center_s.split(",")
                    circles.append({"lat": float(lat_s), "lon": float(lon_s),
                                    "radius_km": float(radius_s)})
                except ValueError:
                    pass

    onset = min((d for d in onsets if d), default=None)
    expires = max((d for d in expires_list if d), default=None)
    sent = parse_iso(root.findtext(_cap("sent")))
    start = onset or sent

    def to_utc_iso(d):
        if d is None:
            return None
        if d.tzinfo is None:  # CAP times carry +05:30; a naive one is unexpected
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat(timespec="seconds")

    has_geom = bool(polygons or circles)
    return {
        "source": "imd-cap",
        "id": root.findtext(_cap("identifier")),
        "event": "; ".join(sorted({e for e in events if e})),
        "severity": "; ".join(sorted({s for s in severities if s})),
        "start_utc": to_utc_iso(start),
        "end_utc": to_utc_iso(expires),
        "area_desc": "; ".join(area_descs) or None,
        "issuer": (heat_infos[0].findtext(_cap("senderName"))
                   or root.findtext(_cap("sender"))),
        "match_geom": ({"type": "shapes", "polygons": polygons, "circles": circles}
                       if has_geom else None),
        "match_method": "polygon" if polygons else ("circle" if circles else "none"),
        "url": source_url,
    }


def point_in_polygon(lat, lon, polygon):
    """Ray-casting point-in-polygon. polygon = [[lat, lon], ...] (>= 3 points;
    closing repeat of the first point optional). Boundary behavior is
    tolerable either way for ~25km-scale alert polygons."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i][0], polygon[i][1]
        yj, xj = polygon[j][0], polygon[j][1]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def alert_is_active(alert, now_utc):
    """Active = start <= now <= end; a missing bound is treated as open
    (permissive on purpose -- better to log a doubtful match than drop one)."""
    now_iso = now_utc.isoformat(timespec="seconds")
    start, end = alert.get("start_utc"), alert.get("end_utc")
    if start and now_iso < start:
        return False
    if end and now_iso > end:
        return False
    return True


def alert_covers_city(alert, lat, lon):
    geom = alert.get("match_geom")
    if not geom:
        return False
    if geom["type"] == "circle":
        return haversine_km(lat, lon, geom["lat"], geom["lon"]) <= geom["radius_km"]
    if geom["type"] == "shapes":
        for poly in geom.get("polygons", []):
            if point_in_polygon(lat, lon, poly):
                return True
        for circ in geom.get("circles", []):
            if haversine_km(lat, lon, circ["lat"], circ["lon"]) <= circ["radius_km"]:
                return True
    return False


def compute_city_signal(city_hourly, today_date_key, rel_c):
    """Today's (IST) REL-exceedance record for one city, mirroring
    computeCityWorkStress in heat/js/data.js: valid hours only
    (wbgt_status==0, wbgt_c non-null), stress when wbgt_c >= REL, overlooked
    when additionally outside the 11:00-16:59 IST window with solar > 50."""
    hours_above_rel = 0
    overlooked_hours = 0
    max_wbgt = None
    for h in city_hourly:
        if not h["time_ist"].startswith(today_date_key):
            continue
        if h.get("wbgt_status") != 0 or h.get("wbgt_c") is None:
            continue
        wbgt = h["wbgt_c"]
        if max_wbgt is None or wbgt > max_wbgt:
            max_wbgt = wbgt
        if wbgt < rel_c:
            continue
        hours_above_rel += 1
        ist_hour = int(h["time_ist"][11:13])
        inside_window = HAP_WINDOW_START <= ist_hour < HAP_WINDOW_END
        if not inside_window and h.get("solar_wm2", 0) > SUN_UP_WM2:
            overlooked_hours += 1
    return {
        "hours_above_rel": hours_above_rel,
        "overlooked_hours": overlooked_hours,
        "max_wbgt_c": max_wbgt,
    }


def load_seen_ids(raw_path):
    """(source, id) pairs already logged this month, for dedupe."""
    seen = set()
    if not os.path.exists(raw_path):
        return seen
    with open(raw_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                seen.add((rec.get("source"), rec.get("id")))
            except json.JSONDecodeError:
                continue  # a corrupt line must not kill the logger
    return seen


def fetch_sachet_alerts():
    """Returns (list of normalized heat alerts, source_ok)."""
    try:
        resp = requests.get(SACHET_URL, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        records = resp.json()
        if not isinstance(records, list):
            raise ValueError(f"expected a JSON array, got {type(records).__name__}")
        alerts = []
        for rec in records:
            try:
                parsed = parse_sachet_record(rec)
                if parsed:
                    alerts.append(parsed)
            except Exception:  # one malformed record must not drop the rest
                traceback.print_exc()
        return alerts, True
    except Exception:
        print("WARNING: SACHET fetch failed (logged, not fatal):")
        traceback.print_exc()
        return [], False


def fetch_imd_cap_alerts():
    """Returns (list of normalized heat alerts, source_ok). Fetches the RSS
    index, then each linked per-alert XML."""
    try:
        resp = requests.get(IMD_CAP_RSS_URL, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        rss = ET.fromstring(resp.content)
        urls = []
        for link in rss.iter("link"):
            url = (link.text or "").strip()
            if url.endswith(".xml") and url != IMD_CAP_RSS_URL and url not in urls:
                urls.append(url)
        alerts = []
        for url in urls[:MAX_CAP_ALERT_FETCHES]:
            try:
                alert_resp = requests.get(url, timeout=REQUEST_TIMEOUT_S)
                alert_resp.raise_for_status()
                parsed = parse_cap_alert(alert_resp.content, source_url=url)
                if parsed:
                    alerts.append(parsed)
            except Exception:  # one bad alert XML must not drop the rest
                traceback.print_exc()
        return alerts, True
    except Exception:
        print("WARNING: IMD CAP fetch failed (logged, not fatal):")
        traceback.print_exc()
        return [], False


def run():
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc + IST_OFFSET
    today_date_key = now_ist.strftime("%Y-%m-%d")
    month_key = now_utc.strftime("%Y-%m")
    rel_c = niosh_rel_c(HEAVY_WATTS)

    raw_dir = os.path.join(ALERTS_DIR, "raw")
    citylog_dir = os.path.join(ALERTS_DIR, "citylog")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(citylog_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{month_key}.jsonl")
    citylog_path = os.path.join(citylog_dir, f"{month_key}.jsonl")

    sachet_alerts, sachet_ok = fetch_sachet_alerts()
    imd_alerts, imd_ok = fetch_imd_cap_alerts()
    all_alerts = sachet_alerts + imd_alerts

    # Raw log: append only alerts not already seen this month.
    seen = load_seen_ids(raw_path)
    new_alerts = [a for a in all_alerts if (a["source"], a["id"]) not in seen]
    if new_alerts:
        with open(raw_path, "a", encoding="utf-8") as f:
            for a in new_alerts:
                record = dict(a)
                record["first_seen_utc"] = now_utc.isoformat(timespec="seconds")
                f.write(json.dumps(record, ensure_ascii=False,
                                   separators=(",", ":")) + "\n")

    # City log: one line per run, always (even with zero alerts / no data).
    active_alerts = [a for a in all_alerts if alert_is_active(a, now_utc)]
    cities_out = {}
    latest_ok = True
    try:
        with open(CITIES_PATH, "r", encoding="utf-8") as f:
            cities = json.load(f)
        with open(LATEST_PATH, "r", encoding="utf-8") as f:
            latest = json.load(f)
        hourly_by_id = {c["id"]: c["hourly"] for c in latest["cities"]}
        for city in cities:
            signal = compute_city_signal(
                hourly_by_id.get(city["id"], []), today_date_key, rel_c)
            covering = [f'{a["source"]}:{a["id"]}' for a in active_alerts
                        if alert_covers_city(a, city["lat"], city["lon"])]
            entry = dict(signal)
            if covering:  # key omitted when empty to keep lines compact
                entry["active_heat_alerts"] = covering
            cities_out[str(city["id"])] = entry
    except Exception:
        print("WARNING: could not compute city signals from latest.json:")
        traceback.print_exc()
        latest_ok = False

    citylog_line = {
        "run_utc": now_utc.isoformat(timespec="seconds"),
        "ist_date": today_date_key,
        "workload": "heavy",
        "rel_c": round(rel_c, 2),
        "alert_sources_ok": {"sachet": sachet_ok, "imd_cap": imd_ok},
        "latest_ok": latest_ok,
        "heat_alerts_seen": len(all_alerts),
        "heat_alerts_active": len(active_alerts),
        "cities": cities_out,
    }
    with open(citylog_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(citylog_line, ensure_ascii=False,
                           separators=(",", ":")) + "\n")

    print(f"Alert log: {len(all_alerts)} heat alert(s) seen "
          f"({len(new_alerts)} new, {len(active_alerts)} active), "
          f"sources ok: sachet={sachet_ok} imd_cap={imd_ok}, "
          f"city signals: {len(cities_out)}.")


def main():
    # Hard rule: never block the heat-data pipeline, no matter what breaks.
    try:
        run()
    except Exception:
        print("WARNING: fetch_alerts.py failed entirely (non-fatal to the pipeline):")
        traceback.print_exc()
    sys.exit(0)


if __name__ == "__main__":
    main()
