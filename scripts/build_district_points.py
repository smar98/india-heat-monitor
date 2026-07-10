"""
One-time script: builds heat/data/district_points.json -- one representative
point per 2011 Census district, used by scripts/fetch_districts_daily.py as
the location it asks Open-Meteo about for that district.

Uses shapely's representative_point(), which is guaranteed to lie INSIDE the
polygon (a plain centroid can fall outside a concave district or in the sea
for a coastal one). shapely is needed only here, one time -- it is
deliberately NOT in scripts/requirements.txt, which CI installs.

Input: heat/data/india_districts_2011.geojson (simplified DataMeet
Census-2011 boundaries; see its LICENSE.txt).

    python3 scripts/build_district_points.py
"""

import json
import os

from shapely.geometry import shape
from shapely.validation import make_valid

HERE = os.path.dirname(os.path.abspath(__file__))
GEOJSON_PATH = os.path.join(HERE, "..", "heat", "data", "india_districts_2011.geojson")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "district_points.json")


def main():
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        geo = json.load(f)

    points = []
    for feat in geo["features"]:
        props = feat["properties"]
        # censuscode 0 = the "Data Not Available" polygon (Pakistan-
        # administered Kashmir in the Census-2011 frame): it stays in the
        # boundary file so the map shows the full official outline, but has
        # no census data and gets no weather point.
        if int(props["censuscode"]) == 0:
            continue
        geom = shape(feat["geometry"])
        if not geom.is_valid:
            # mapshaper simplification can leave a self-intersection on a
            # complex coastline; repair before taking the interior point.
            geom = make_valid(geom)
        pt = geom.representative_point()
        assert geom.contains(pt) or geom.touches(pt), props["DISTRICT"]
        points.append({
            "code": int(props["censuscode"]),
            "district": props["DISTRICT"],
            "state": props["ST_NM"],
            "lat": round(pt.y, 4),
            "lon": round(pt.x, 4),
        })

    points.sort(key=lambda p: p["code"])
    codes = [p["code"] for p in points]
    assert len(codes) == len(set(codes)), "duplicate census codes"

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(points, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {OUTPUT_PATH}: {len(points)} district points.")


if __name__ == "__main__":
    main()
