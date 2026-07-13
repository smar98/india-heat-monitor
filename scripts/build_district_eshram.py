"""Builds heat/data/district_eshram.json -- per-district counts of e-Shram
registrations in predominantly-outdoor occupation sectors (AGRICULTURE +
CONSTRUCTION), keyed by Census-2011 district code so it joins the map and
the Census-2011 workforce file directly.

Source: data.gov.in resource 1d4d1c5a-feea-423b-be4f-c3636fdd1d82
("District-wise Demographic Data of Unorganised Workers registered on
eShram as on previous day") -- the full registry as individual records,
refreshed daily by the Ministry of Labour and Employment. Nothing is
downloaded in bulk: for each district code the script issues filtered
count queries and reads the API's `total` field.

Requires a data.gov.in API key in the DATAGOV_API_KEY environment
variable (free registration). Two practical notes learned the hard way:
the gateway 502s the default Python-urllib User-Agent under load, so a
browser UA is sent; and the ~2,700 count queries take a couple of hours
at a polite pace. Progress is checkpointed to data/eshram_cache/
(gitignored) and the script resumes for free if interrupted.

    DATAGOV_API_KEY=... python3 scripts/build_district_eshram.py
    # or reuse an existing raw harvest:
    python3 scripts/build_district_eshram.py --from-raw <raw.json>

e-Shram districts are current administrative districts (with post-2011
renames and splits, including Telangana's 2014 split from Andhra Pradesh);
the map is the 2011 Census frame. The join below normalizes names, applies
a table of 205 documented renames/splits, and folds post-2011 districts
back into their 2011 parent (Telangana districts fold into the undivided-
AP district they were carved from). 22 of those entries were carved from
more than one 2011 parent; each is assigned wholly to its majority parent,
a modeling choice that totals ~1% of national registrations. Integrity
gates, now tuned to catch drift from *future* re-harvests (new districts
keep getting created) rather than the known 2011-vs-now gap: >=98% of the
640 Census districts must join, unmatched registrations must stay under 1%
of the national outdoor total, and the joined counts must rank-correlate
with the Census outdoor-workforce file (Spearman >= 0.8) -- if the registry
and the census disagreed wildly, this layer should not ship.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://api.data.gov.in/resource/1d4d1c5a-feea-423b-be4f-c3636fdd1d82"
CACHE = os.path.join(HERE, "..", "data", "eshram_cache", "raw_districts.json")
WORKERS_PATH = os.path.join(HERE, "..", "heat", "data", "district_workers.json")
OUTPUT_PATH = os.path.join(HERE, "..", "heat", "data", "district_eshram.json")
PACE_S = 1.5
MAX_CODE = 900  # LGD district codes are currently well under this

STATE_ALIASES = {
    "PONDICHERRY": "PUDUCHERRY",
    "ORISSA": "ODISHA",
    "DELHI": "NCT OF DELHI",
    # Ladakh became a UT in 2019; the 2011 frame has Kargil/Leh under J&K.
    "LADAKH": "JAMMU AND KASHMIR",
    # Telangana split from Andhra Pradesh in 2014 -- the 2011 census frame
    # has no Telangana entry, so its districts are aliased to (and folded
    # into, via RENAMES below) the undivided-AP district they were carved
    # from. This is disclosed on the methods page and in map popups.
    "TELANGANA": "ANDHRA PRADESH",
    "ARUNANCHAL PRADESH": "ARUNACHAL PRADESH",  # census file's own misspelling
    "ANDAMAN AND NICOBAR ISLAND": "ANDAMAN AND NICOBAR ISLANDS",  # census: singular
    # 2020 UT merger: alias BOTH pre-merger census states into e-Shram's
    # single merged-UT bucket; the three district names (Dadra & Nagar
    # Haveli / Daman / Diu) disambiguate within it via RENAMES/name match.
    "DADARA AND NAGAR HAVELLI": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
    "DAMAN AND DIU": "THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU",
}

# Documented post-2011 renames and splits, e-Shram spelling -> Census-2011
# name. Splits map to the 2011 parent; the join aggregates them. Ordered by
# state, biggest registration volume first. `# multi-parent` marks entries
# where the modern district was carved from more than one 2011 parent; we
# assign the whole count to the majority parent (~1% of national
# registrations in total -- see module docstring).
RENAMES = {
    # Original documented renames (predate the state-by-state expansion below)
    "PRAYAGRAJ": "ALLAHABAD", "AYODHYA": "FAIZABAD", "GURUGRAM": "GURGAON",
    "BHADOHI": "SANT RAVIDAS NAGAR", "AMROHA": "JYOTIBA PHULE NAGAR",
    "HATHRAS": "MAHAMAYA NAGAR", "DHOLPUR": "DHAULPUR", "KAIMUR BHABUA": "KAIMUR",
    "BUDGAM": "BADGAM", "SRI MUKTSAR SAHIB": "MUKTSAR", "PAURI GARHWAL": "GARHWAL",
    "POONCH": "PUNCH", "CHITTORGARH": "CHITTAURGARH",
    # Karnataka: 2014 official renames + Vijayanagara (2021, from Ballari)
    "BELAGAVI": "BELGAUM", "VIJAYAPURA": "BIJAPUR", "KALABURAGI": "GULBARGA",
    "BENGALURU URBAN": "BANGALORE", "BENGALURU RURAL": "BANGALORE RURAL",
    "MYSURU": "MYSORE", "BALLARI": "BELLARY", "TUMAKURU": "TUMKUR",
    "SHIVAMOGGA": "SHIMOGA", "VIJAYANAGAR": "BELLARY",
    # Telangana (state aliased to Andhra Pradesh above; 2016+ splits -> pre-2014 parent)
    "MAHABUBNAGAR": "MAHBUBNAGAR", "RANGA REDDY": "RANGAREDDY",
    "WARANGAL URBAN": "WARANGAL", "WARANGAL RURAL": "WARANGAL",
    "BHADRADRI KOTHAGUDEM": "KHAMMAM", "MEDCHAL MALKAJGIRI": "RANGAREDDY",
    "SANGAREDDY": "MEDAK", "SIDDIPET": "MEDAK", "SURYAPET": "NALGONDA",
    "YADADRI BHUVANAGIRI": "NALGONDA", "KAMAREDDY": "NIZAMABAD",
    "JAGITIAL": "KARIMNAGAR", "PEDDAPALLI": "KARIMNAGAR", "RAJANNA SIRCILLA": "KARIMNAGAR",
    "MANCHERIAL": "ADILABAD", "NIRMAL": "ADILABAD", "KUMURAM BHEEM ASIFABAD": "ADILABAD",
    "MAHABUBABAD": "WARANGAL", "MULUGU": "WARANGAL",
    "JAYASHANKAR BHUPALAPALLY": "WARANGAL",  # multi-parent: small parts from Karimnagar/Khammam
    "JANGOAN": "WARANGAL",  # multi-parent: parts from Nalgonda
    "NAGARKURNOOL": "MAHBUBNAGAR", "WANAPARTHY": "MAHBUBNAGAR",
    "JOGULAMBA GADWAL": "MAHBUBNAGAR", "NARAYANPET": "MAHBUBNAGAR",
    "VIKARABAD": "RANGAREDDY",
    # Uttar Pradesh: post-2010 splits + renames
    "SAMBHAL": "MORADABAD",  # multi-parent: Gunnaur tehsil came from Budaun
    "AMETHI": "SULTANPUR",   # multi-parent: Salon/Tiloi tehsils came from Rae Bareli
    "KASGANJ": "KANSHIRAM NAGAR", "SHAMLI": "MUZAFFARNAGAR", "HAPUR": "GHAZIABAD",
    # Maharashtra
    "PALGHAR": "THANE", "BEED": "BID", "RAIGAD": "RAIGARH",
    # Jharkhand spellings
    "EAST SINGHBUM": "PURBI SINGHBHUM", "WEST SINGHBHUM": "PASHCHIMI SINGHBHUM",
    "KODERMA": "KODARMA",
    # Madhya Pradesh
    "EAST NIMAR": "KHANDWA", "NARSINGHPUR": "NARSIMHAPUR", "NIWARI": "TIKAMGARH",
    "AGAR MALWA": "SHAJAPUR", "MAIHAR": "SATNA", "MAUGANJ": "REWA", "PANDHURNA": "CHHINDWARA",
    # Punjab
    "FAZILKA": "FIROZPUR", "S A S NAGAR": "SAHIBZADA AJIT SINGH NAGAR",
    "PATHANKOT": "GURDASPUR", "MALERKOTLA": "SANGRUR",
    # Chhattisgarh
    "BALODA BAZAR": "RAIPUR", "KABIRDHAM": "KABEERDHAM", "BALOD": "DURG",
    "BEMETARA": "DURG", "MUNGELI": "BILASPUR", "GARIYABAND": "RAIPUR",
    "BALRAMPUR": "SURGUJA",  # collides with UP's Balrampur; symmetric rename keeps both correct
    "SURAJPUR": "SURGUJA", "KANKER": "UTTAR BASTAR KANKER", "KOREA": "KORIYA",
    "DANTEWADA": "DAKSHIN BASTAR DANTEWADA", "KONDAGAON": "BASTAR",
    "GAURELLA PENDRA MARWAHI": "BILASPUR", "SUKMA": "DAKSHIN BASTAR DANTEWADA",
    "SAKTI": "JANJGIR CHAMPA", "MANENDRAGARH CHIRMIRI BHARATPUR M C B": "KORIYA",
    "KHAIRAGARH CHHUIKHADAN GANDAI": "RAJNANDGAON", "MOHLA MANPUR AMBAGARH CHOUKI": "RAJNANDGAON",
    "SARANGARH BILAIGARH": "RAIGARH",  # multi-parent: Bilaigarh side from Baloda Bazar (Raipur)
    # Andhra Pradesh 2022 26-district split -> 2011 parent
    "SPSR NELLORE": "SRI POTTI SRIRAMULU NELLORE", "PALNADU": "GUNTUR",
    "BAPATLA": "GUNTUR",  # multi-parent: Chirala side from Prakasam
    "KONASEEMA": "EAST GODAVARI", "NTR": "KRISHNA", "ANAKAPALLI": "VISAKHAPATNAM",
    "ALLURI SITHARAMA RAJU": "VISAKHAPATNAM",  # multi-parent: Rampachodavaram from East Godavari
    "ANNAMAYYA": "Y S R",  # multi-parent: parts from Chittoor
    "SRI SATHYA SAI": "ANANTAPUR",
    "PARVATHIPURAM MANYAM": "VIZIANAGARAM",  # multi-parent: Palakonda side from Srikakulam
    "TIRUPATI": "CHITTOOR",  # multi-parent: Gudur side from Nellore
    "ELURU": "WEST GODAVARI",  # multi-parent: parts from Krishna
    "KAKINADA": "EAST GODAVARI", "NANDYAL": "KURNOOL",
    # Tamil Nadu 2019-20 splits + spellings
    "KALLAKURICHI": "VILUPPURAM", "TUTICORIN": "THOOTHUKKUDI",
    "CHENGALPATTU": "KANCHEEPURAM", "MAYILADUTHURAI": "NAGAPATTINAM",
    "TENKASI": "TIRUNELVELI", "RANIPET": "VELLORE", "TIRUPATHUR": "VELLORE",
    "KANCHIPURAM": "KANCHEEPURAM",
    # Gujarat 2013 splits
    "GIR SOMNATH": "JUNAGADH", "CHHOTAUDEPUR": "VADODARA", "ARVALLI": "SABAR KANTHA",
    "MAHISAGAR": "PANCH MAHALS",  # multi-parent: Balasinor/Virpur side from Kheda
    "MORBI": "RAJKOT",  # multi-parent: parts from Surendranagar/Jamnagar
    "BOTAD": "BHAVNAGAR",  # multi-parent: parts from Ahmedabad
    "DEVBHUMI DWARKA": "JAMNAGAR", "DANG": "THE DANGS",
    # Assam 2015-22 splits + spelling
    "HOJAI": "NAGAON", "KAMRUP METRO": "KAMRUP METROPOLITAN", "BISWANATH": "SONITPUR",
    "SOUTH SALMARA MANCACHAR": "DHUBRI", "CHARAIDEO": "SIVASAGAR", "MAJULI": "JORHAT",
    "WEST KARBI ANGLONG": "KARBI ANGLONG", "BAJALI": "BARPETA", "TAMULPUR": "BAKSA",
    # Haryana
    "NUH": "MEWAT", "CHARKI DADRI": "BHIWANI",
    # Delhi 2012 (9 -> 11 districts)
    "SOUTH EAST": "SOUTH",
    "SHAHDARA": "EAST",  # multi-parent: carved from East + North East Delhi
    # Odisha spellings
    "SONEPUR": "SUBARNAPUR", "BOUDH": "BAUDH", "DEOGARH": "DEBAGARH",
    # Tripura 2012 (4 -> 8)
    "GOMATI": "SOUTH TRIPURA", "SEPAHIJALA": "WEST TRIPURA",
    "KHOWAI": "WEST TRIPURA", "UNAKOTI": "NORTH TRIPURA",
    # West Bengal
    "PURBA BARDHAMAN": "BARDDHAMAN",
    "PASCHIM BARDHAMAN": "BARDDHAMAN",
    "WEST JAINTIA HILLS": "JAINTIA HILLS",
    "EAST JAINTIA HILLS": "JAINTIA HILLS",
    "KALIMPONG": "DARJILING",
    "ALIPURDUAR": "JALPAIGURI",
    "MEDINIPUR EAST": "PURBA MEDINIPUR",
    "MEDINIPUR WEST": "PASCHIM MEDINIPUR",
    "JHARGRAM": "PASCHIM MEDINIPUR",
    "24 PARAGANAS SOUTH": "SOUTH TWENTY FOUR PARGANAS",
    "24 PARAGANAS NORTH": "NORTH TWENTY FOUR PARGANAS",
    "SOUTH 24 PARGANAS": "SOUTH TWENTY FOUR PARGANAS",
    "NORTH 24 PARGANAS": "NORTH TWENTY FOUR PARGANAS",
    "HOWRAH": "HAORA",
    "HOOGHLY": "HUGLI",
    "PURULIA": "PURULIYA",
    "MALDA": "MALDAH",
    "COOCHBEHAR": "KOCH BIHAR",
    "DARJEELING": "DARJILING",
    # Arunachal Pradesh post-2011 splits (the 16 originals match once the state alias lands)
    "NAMSAI": "LOHIT", "LONGDING": "TIRAP", "KRA DAADI": "KURUNG KUMEY",
    "KAMLE": "LOWER SUBANSIRI",  # multi-parent: parts from Upper Subansiri
    "LOWER SIANG": "WEST SIANG",  # multi-parent: parts from East Siang
    "SIANG": "EAST SIANG",  # multi-parent: parts from West Siang
    "LEPARADA": "WEST SIANG", "SHI YOMI": "WEST SIANG", "PAKKE KESSANG": "EAST KAMENG",
    "KEYI PANYOR": "LOWER SUBANSIRI",
    "BICHOM": "WEST KAMENG",  # multi-parent: parts from East Kameng (28 regs)
    # Manipur 2016 (9 -> 16)
    "KAKCHING": "THOUBAL", "KANGPOKPI": "SENAPATI", "TENGNOUPAL": "CHANDEL",
    "JIRIBAM": "IMPHAL EAST", "NONEY": "TAMENGLONG", "KAMJONG": "UKHRUL",
    "PHERZAWL": "CHURACHANDPUR",
    # Meghalaya splits (North Garo Hills also fixes a live fuzzy false-positive -> South Garo Hills)
    "NORTH GARO HILLS": "EAST GARO HILLS", "SOUTH WEST GARO HILLS": "WEST GARO HILLS",
    "SOUTH WEST KHASI HILLS": "WEST KHASI HILLS", "EASTERN WEST KHASI HILLS": "WEST KHASI HILLS",
    # Mizoram 2019 splits
    "HNAHTHIAL": "LUNGLEI", "SAITUAL": "AIZAWL", "KHAWZAWL": "CHAMPHAI",
    # Nagaland 2021-24 splits
    "CHUMOUKEDIMA": "DIMAPUR", "TSEMINYU": "KOHIMA", "NIULAND": "DIMAPUR",
    "NOKLAK": "TUENSANG", "SHAMATOR": "TUENSANG", "MELURI": "PHEK",
    # Sikkim 2021 new districts
    "SORENG": "WEST DISTRICT", "PAKYONG": "EAST DISTRICT",
    # Rajasthan 2023 new districts
    "DIDWANA KUCHAMAN": "NAGAUR", "BALOTRA": "BARMER",
    "KOTPUTLI BEHROR": "JAIPUR",  # multi-parent: Behror side from Alwar
    "BEAWAR": "AJMER",  # multi-parent: parts from Pali/Rajsamand
    "KHAIRTHAL TIJARA": "ALWAR", "SALUMBAR": "UDAIPUR", "DEEG": "BHARATPUR",
    "PHALODI": "JODHPUR",  # multi-parent: parts from Jaisalmer
    # J&K / Ladakh / small UTs
    "SHOPIAN": "SHUPIYAN", "LEH LADAKH": "LEH", "SOUTH ANDAMANS": "SOUTH ANDAMAN",
    "PONDICHERRY": "PUDUCHERRY", "LAKSHADWEEP DISTRICT": "LAKSHADWEEP",
}


def norm(s):
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = RENAMES.get(s, s)
    return " ".join(sorted(s.split())), s.replace(" ", "")


def norm_state(s):
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return STATE_ALIASES.get(s, s)


def query(params, key, tries=60):
    params = dict(params, **{"api-key": key, "format": "json"})
    url = BASE + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.loads(r.read())
            if "total" not in d:
                raise ValueError("no total in response")
            time.sleep(PACE_S)
            return d
        except Exception as e:
            print(f"  retry {attempt + 1} in 60s ({e})", file=sys.stderr)
            time.sleep(60)
    raise RuntimeError(f"gave up on {params}")


def harvest(key):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    results, empty = {}, set()
    if os.path.exists(CACHE):
        results = json.load(open(CACHE))
        empty = set(results.pop("_empty", []))
        print(f"resuming: {len(results)} districts cached")
    for code in range(1, MAX_CODE + 1):
        if str(code) in results or code in empty:
            continue
        d = query({"filters[currentDistrictCode]": code, "limit": 1}, key)
        if d["total"] == 0 or not d["records"]:
            empty.add(code)
        else:
            rec = d["records"][0]
            agri = query({"filters[currentDistrictCode]": code,
                          "filters[primaryOccupation]": "AGRICULTURE", "limit": 0}, key)["total"]
            constr = query({"filters[currentDistrictCode]": code,
                            "filters[primaryOccupation]": "CONSTRUCTION", "limit": 0}, key)["total"]
            results[str(code)] = {
                "name": rec["currentDistrictName"], "state": rec["currentStateName"],
                "total": d["total"], "agri": agri, "constr": constr,
            }
        out = dict(results)
        out["_empty"] = sorted(empty)
        with open(CACHE, "w") as f:
            json.dump(out, f)
        if code % 50 == 0:
            print(f"  scanned {code}/{MAX_CODE}: {len(results)} districts", flush=True)
    return results


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den


def main():
    if "--from-raw" in sys.argv:
        raw = json.load(open(sys.argv[sys.argv.index("--from-raw") + 1]))
        raw.pop("_empty", None)
    else:
        key = os.environ.get("DATAGOV_API_KEY")
        if not key:
            sys.exit("set DATAGOV_API_KEY (free key from data.gov.in) or use --from-raw")
        raw = harvest(key)

    census = json.load(open(WORKERS_PATH))["districts"]
    cidx, cflat = {}, {}
    for code, d in census.items():
        st = norm_state(d.get("state", ""))
        tok, flat = norm(d["name"])
        cidx[(st, tok)] = code
        cflat[(st, flat)] = code

    matched, unmatched = {}, []
    for e in raw.values():
        etok, eflat = norm(e["name"])
        st = norm_state(e["state"])
        code = cidx.get((st, etok)) or cflat.get((st, eflat))
        if code is None:
            best, score = None, 0.0
            for (cst, nm), c in cidx.items():
                if cst != st:
                    continue
                r = SequenceMatcher(None, etok, nm).ratio()
                if r > score:
                    best, score = c, r
            if score >= 0.87:
                code = best
                print(f"  fuzzy: {e['name']} ({e['state']}) -> {census[best]['name']} ({score:.2f})")
            else:
                unmatched.append((e["state"], e["name"], e["total"]))
                continue
        if code in matched:
            m = matched[code]
            m["agri"] += e["agri"]
            m["constr"] += e["constr"]
            m["total"] += e["total"]
            m["merged"] = m.get("merged", 1) + 1
        else:
            matched[code] = {"agri": e["agri"], "constr": e["constr"], "total": e["total"]}

    # Gates.
    coverage = len(matched) / len(census)
    esh_outdoor = sum(e["agri"] + e["constr"] for e in raw.values())
    unm_outdoor_share = (sum(t for _, _, t in unmatched) / sum(e["total"] for e in raw.values()))
    pairs = [(matched[c]["agri"] + matched[c]["constr"], census[c]["outdoor_workers"])
             for c in matched if census[c]["outdoor_workers"] > 0]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    print(f"coverage: {len(matched)}/{len(census)} = {coverage:.1%}")
    print(f"unmatched registrations share: {unm_outdoor_share:.2%}")
    for st, nm, t in sorted(unmatched, key=lambda r: -r[2])[:20]:
        print(f"  unmatched: {t:>9,}  {nm} ({st})")
    print(f"Spearman vs Census outdoor workers ({len(pairs)} pairs): {rho:.3f}")
    if coverage < 0.98:
        raise RuntimeError("join coverage below 98% -- do not ship")
    if unm_outdoor_share > 0.01:
        raise RuntimeError("unmatched registrations above 1% -- do not ship")
    if rho < 0.8:
        raise RuntimeError("rank agreement with Census below 0.8 -- do not ship")

    output = {
        "meta": {
            "source": ("e-Shram national registry of unorganised workers "
                       "(Ministry of Labour and Employment), via data.gov.in "
                       "resource 1d4d1c5a-feea-423b-be4f-c3636fdd1d82; counts "
                       "are filtered-query totals, not a bulk download"),
            "definition": ("registrations whose primaryOccupation is AGRICULTURE "
                           "or CONSTRUCTION, by current-residence district, "
                           "mapped to Census-2011 district codes (documented "
                           "renames applied; post-2011 splits folded into their "
                           "2011 parent). Registrations are not a workforce "
                           "count: e-Shram covers unorganised workers aged "
                           "16-59 who registered since 2021."),
            "as_of": time.strftime("%Y-%m-%d"),
            "join_coverage": round(coverage, 4),
            "spearman_vs_census_outdoor": round(rho, 3),
            "eshram_rows_folded": len(raw),
            "national_agri": sum(m["agri"] for m in matched.values()),
            "national_constr": sum(m["constr"] for m in matched.values()),
        },
        "districts": {str(k): {"agri": v["agri"], "constr": v["constr"]}
                      for k, v in sorted(matched.items(), key=lambda kv: int(kv[0]))},
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"wrote {OUTPUT_PATH}: {len(matched)} districts, "
          f"{output['meta']['national_agri'] + output['meta']['national_constr']:,} "
          f"outdoor-sector registrations")


if __name__ == "__main__":
    main()
