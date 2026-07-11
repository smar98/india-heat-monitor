"""
One-time script: builds heat/data/district_workers.json -- per-district
counts of MAIN WORKERS in predominantly-outdoor industrial categories, from
Census of India 2011 table B-04 ("Main workers classified by age, industrial
category and sex").

Categories counted as outdoor work (persons, Total area, all ages):
  - NIC A: cultivators + agricultural labourers + plantation/livestock/
    forestry/fishing (three separate B-04 column groups)
  - NIC B: mining and quarrying
  - NIC F: construction
This is a deliberate under-count of outdoor exposure (e.g. street vending
sits in retail G, brick kilns partly in manufacturing C) -- the honest
direction to err.

Sources: the Census "datagov" per-state CSVs
(https://www.censusindia.gov.in/datagov/B-04/DDW_B04_{SS}00_State_{NAME}-2011.csv)
where the filename resolves; four states/UTs whose names contain "&" have no
CSV at a guessable URL and use the equivalent per-state XLS from the Census
NADA catalog instead. Both carry identical column layouts (verified by
inspection); rows are filtered to district-level (district code != 000),
Total (not rural/urban), all-ages.

Integrity gates (the script fails loudly rather than shipping holes):
  1. per state: the sum of district outdoor-worker counts must equal the
     state-total row's count exactly;
  2. >=95% of the districts in heat/data/district_points.json must join a
     workers row by 2011 census district code (in practice: 100%).

Needs the third-party `xlrd` package for the four XLS states -- one-time,
deliberately NOT in scripts/requirements.txt (CI never runs this).

    python3 scripts/build_district_workers.py
"""

import csv
import io
import json
import os
import ssl
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
POINTS_PATH = os.path.join(HERE, "..", "heat", "data", "district_points.json")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "district_workers.json")

CSV_BASE = "https://www.censusindia.gov.in/datagov/B-04/DDW_B04_{code}00_State_{name}-2011.csv"

# State code -> CSV filename fragment, or ("xls", url) for the four
# ampersand-named states whose CSVs don't resolve at any guessable URL.
STATES = {
    1:  ("xls", "https://censusindia.gov.in/nada/index.php/catalog/43037/download/46705/DDW-B04-0100.xls"),  # Jammu & Kashmir
    2:  "HIMACHAL_PRADESH",
    3:  "PUNJAB",
    4:  "CHANDIGARH",
    5:  "UTTARAKHAND",
    6:  "HARYANA",
    7:  "NCT_OF_DELHI",
    8:  "RAJASTHAN",
    9:  "UTTAR_PRADESH",
    10: "BIHAR",
    11: "SIKKIM",
    12: "ARUNACHAL_PRADESH",
    13: "NAGALAND",
    14: "MANIPUR",
    15: "MIZORAM",
    16: "TRIPURA",
    17: "MEGHALAYA",
    18: "ASSAM",
    19: "WEST_BENGAL",
    20: "JHARKHAND",
    21: "ODISHA",
    22: "CHHATTISGARH",
    23: "MADHYA_PRADESH",
    24: "GUJARAT",
    25: ("xls", "https://censusindia.gov.in/nada/index.php/catalog/43061/download/46729/DDW-B04-2500.xls"),  # Daman & Diu
    26: ("xls", "https://censusindia.gov.in/nada/index.php/catalog/43062/download/46730/DDW-B04-2600.xls"),  # Dadra & Nagar Haveli
    27: "MAHARASHTRA",
    28: "ANDHRA_PRADESH",   # 2011 frame: includes today's Telangana
    29: "KARNATAKA",
    30: "GOA",
    31: "LAKSHADWEEP",
    32: "KERALA",
    33: "TAMIL_NADU",
    34: "PUDUCHERRY",
    35: ("xls", "https://censusindia.gov.in/nada/index.php/catalog/43071/download/46739/DDW-B04-3500.xls"),  # Andaman & Nicobar
}

# Positional value columns, identical in the CSV and XLS layouts:
# 0..5 = table code, state code, district code, area name, T/R/U, age group.
COL_DISTRICT_CODE = 2
COL_AREA_NAME = 3
COL_TRU = 4
COL_AGE = 5
COL_CULTIVATORS = 9       # NIC A - cultivators - persons
COL_AGRI_LABOUR = 12      # NIC A - agricultural labourers - persons
COL_PLANTATION = 15       # NIC A - plantation/livestock/forestry/fishing - persons
COL_MINING = 18           # NIC B - persons
COL_CONSTRUCTION = 30     # NIC F - persons

# The census site's TLS chain doesn't verify on stock macOS Python; these are
# public statistical files fetched over HTTPS, integrity-checked by the two
# gates below.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
        return resp.read()


def _num(cell):
    s = str(cell).replace("`", "").strip()
    if s == "":
        return 0
    return int(float(s))


def rows_from_csv(raw):
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))


def rows_from_xls(raw):
    import xlrd  # local-only dependency; see module docstring
    sheet = xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
    return [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)]


def parse_state(rows):
    """Returns (state_total, {district_code: record}) for one state's rows."""
    districts = {}
    state_total = None
    for row in rows:
        if len(row) <= COL_CONSTRUCTION or str(row[0]).strip() != "B0104":
            continue
        if str(row[COL_TRU]).strip() != "Total":
            continue
        if str(row[COL_AGE]).replace("`", "").strip() != "Total":
            continue
        agri = _num(row[COL_CULTIVATORS]) + _num(row[COL_AGRI_LABOUR]) + _num(row[COL_PLANTATION])
        record = {
            "agri": agri,
            "mining": _num(row[COL_MINING]),
            "construction": _num(row[COL_CONSTRUCTION]),
        }
        record["outdoor_workers"] = record["agri"] + record["mining"] + record["construction"]
        code = _num(row[COL_DISTRICT_CODE])
        name = str(row[COL_AREA_NAME]).strip()
        if code == 0:
            state_total = record
        else:
            record["name"] = name.replace("District - ", "").split("(")[0].strip()
            districts[code] = record
    return state_total, districts


def main():
    all_districts = {}
    for code in sorted(STATES):
        spec = STATES[code]
        if isinstance(spec, tuple):
            url = spec[1]
            rows = rows_from_xls(fetch(url))
        else:
            url = CSV_BASE.format(code=f"{code:02d}", name=spec)
            rows = rows_from_csv(fetch(url))
        state_total, districts = parse_state(rows)
        if state_total is None or not districts:
            raise RuntimeError(f"state {code}: no data parsed from {url}")

        # Gate 1: district sums must reproduce the state-total row exactly.
        for field in ("agri", "mining", "construction", "outdoor_workers"):
            district_sum = sum(d[field] for d in districts.values())
            if district_sum != state_total[field]:
                raise RuntimeError(
                    f"state {code}: district {field} sum {district_sum} != "
                    f"state total {state_total[field]}")

        overlap = set(districts) & set(all_districts)
        if overlap:
            raise RuntimeError(f"state {code}: duplicate district codes {sorted(overlap)[:5]}")
        all_districts.update(districts)
        print(f"state {code:2d}: {len(districts):3d} districts ok "
              f"({state_total['outdoor_workers']:,} outdoor workers)")

    # Gate 2: join coverage against the map's district points.
    with open(POINTS_PATH, "r", encoding="utf-8") as f:
        point_codes = {p["code"] for p in json.load(f)}
    matched = point_codes & set(all_districts)
    coverage = len(matched) / len(point_codes)
    missing_map = sorted(point_codes - set(all_districts))
    missing_data = sorted(set(all_districts) - point_codes)
    print(f"join coverage: {len(matched)}/{len(point_codes)} = {coverage:.1%}")
    if missing_map:
        print(f"  map districts with NO workers row: {missing_map}")
    if missing_data:
        print(f"  workers rows with NO map district: {missing_data}")
    if coverage < 0.95:
        raise RuntimeError("join coverage below 95% -- do not ship")

    # Attach proper state names (the CSVs only carry ALLCAPS state rows).
    with open(POINTS_PATH, "r", encoding="utf-8") as f:
        state_by_code = {p["code"]: p["state"] for p in json.load(f)}
    for code, rec in all_districts.items():
        if code in state_by_code:
            rec["state"] = state_by_code[code]

    output = {
        "meta": {
            "source": "Census of India 2011, table B-04 (main workers by industrial category)",
            "definition": ("outdoor_workers = main workers (persons, Total area, all ages) in "
                           "NIC A (cultivators + agricultural labourers + plantation/livestock/"
                           "forestry/fishing) + NIC B (mining) + NIC F (construction). "
                           "A deliberate under-count of outdoor exposure."),
            "vintage": 2011,
        },
        "districts": {str(k): v for k, v in sorted(all_districts.items())},
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    total = sum(d["outdoor_workers"] for d in all_districts.values())
    print(f"Wrote {OUTPUT_PATH}: {len(all_districts)} districts, "
          f"{total:,} outdoor main workers nationally.")


if __name__ == "__main__":
    main()
