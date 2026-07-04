# Build Log — India Humid Heat Monitor

A running record of how this dashboard was built and why, kept alongside
the code so the reasoning isn't lost. See `existing_tools_research.md` for
the prior-art review that shaped the project's scope, and
`/Users/sanch/.claude/plans/shiny-yawning-unicorn.md` for the original
approved build plan.

---

## Step 1 — GitHub connection (2026-07-04)

**What:** Turned the local folder into a git repository, created a public
GitHub repo (`smar98/india-heat-monitor`) via the `gh` CLI (already
authenticated on this machine — confirmed with `gh auth status` mid-session
after the user installed it), pushed the initial commit, and enabled
GitHub Pages (serving from `main` branch root).

**Why this order:** nothing else — data pipeline, frontend — is worth
building until there's a place to push it and a URL for it to eventually
appear at. Also the cheapest step to get right, so it went first.

**Result:** repo live at https://github.com/smar98/india-heat-monitor,
site will appear at https://smar98.github.io/india-heat-monitor/ once a
real `index.html` exists (nothing there yet).

**Editorial decisions made along the way:**
- Repo name `india-heat-monitor` (chosen over a generic `portfolio` name,
  even though this repo may host a landing page + future dashboards later
  — user's call, flagged the tradeoff first via AskUserQuestion).
- Public repo (required for free GitHub Pages on a personal account, and
  the point of a portfolio piece is to be visible).
- Map and rank-shift chart will be built in parallel rather than one being
  named "the" centerpiece up front (user's call) — with the requirement
  that the map be genuinely interactive (pan/zoom/hover/click), not static.

---

## Step 2 — Scientific core: wet-bulb, WBGT, risk thresholds (2026-07-04)

**What:** Built and verified the three heat metrics this dashboard is built
around, keeping them strictly separate per the project's editorial rule
(never compare wet-bulb against WBGT-style thresholds).

1. **Wet-bulb temperature** — Stull (2011) empirical approximation.
   Verified the formula, its validity range (RH 5–99%, T −20°C to 50°C),
   and its error bounds (−1°C to +0.65°C, mean absolute error <0.3°C)
   directly against the AMS citation (Stull, *J. Applied Meteorology and
   Climatology* 50(11), 2267–2269, 2011), not a paraphrase of it.
   → `scripts/wbgt.py::wet_bulb_stull()`

2. **Estimated WBGT** — originally planned to vendor **PyWBGT**
   (github.com/QINQINKONG/PyWBGT), but checking its actual LICENSE file
   turned up **CC BY-NC-SA 4.0** (non-commercial, share-alike) — awkward to
   vendor into a repo meant to be freely reusable. Switched to
   **mdljts/wbgt**, confirmed **MIT-licensed**, which turned out to contain
   **James Liljegren's original 2008 Argonne C algorithm** directly
   (`wbgt.c`, with both the MIT wrapper license and the original Argonne
   open-source license preserved).
   - Downloaded the actual C source (`wbgt.c`, `wbgt.h`, `wrapper.c`,
     `wbgt.c.original`) via the GitHub API.
   - Delegated the mechanical C→Python port to a sub-agent (well-scoped
     translation task), with the full C source and license text handed to
     it directly rather than described secondhand.
   - **Verified the port myself**, not just trusted the sub-agent's report:
     compiled Liljegren's original `wbgt.c.original` (with its own demo
     `main()`) with `gcc` directly on this machine, ran it on two test
     cases (a hot/humid Chennai midday scenario and a nighttime scenario),
     and diffed the Python port's output against the compiled C binary's
     actual output. Both matched to within ~0.02–0.1°C (floating-point
     precision noise between C `float` and Python `double`).
   - One real bug surfaced in this cross-check: my original spec to the
     porting agent omitted the C code's `avg` parameter (the met-data
     averaging window), which centers the solar-position calculation at
     `minute − 0.5·avg` rather than the exact timestamp. Turned out the
     port already supported this via an `avg_minutes` argument I just
     hadn't passed in my test call — not a porting bug, a test-harness
     oversight on my part. Confirmed by re-running with `avg_minutes=60`
     (matching Open-Meteo's documented "average of the preceding hour"
     convention for solar radiation) and getting an exact match.
   - Added both C-reference test cases as permanent regression tests in
     `tests/test_liljegren_wbgt.py`, so this stays caught if the module is
     ever edited later.
   → `scripts/liljegren_wbgt.py` (vendored port, full license chain
     preserved in the file's docstring), wrapped by
     `scripts/wbgt.py::estimated_wbgt()`

3. **Risk thresholds** — originally planned flat ISO 7243-style bands
   (<28°C low / 28–30°C moderate / 30–32°C high / >32°C extreme), but these
   turned out to be an invented simplification once checked: the real
   ACGIH/ISO 7243 tables are two-dimensional (vary by workload *and*
   work/rest duty cycle) and are paywalled — confirmed paywalled directly
   via OSHA's own Technical Manual, which states the ACGIH TLV tables
   "are copyrighted by ACGIH and is not publicly available." Rather than
   publish invented numbers under a borrowed standard's name, found NIOSH's
   own public, precise formula instead, by downloading and text-searching
   the actual PDF (DHHS/NIOSH Publication 2016-106):
   ```
   RAL [°C-WBGT] = 59.9 − 14.1·log10(M)   (unacclimatized workers)
   REL [°C-WBGT] = 56.7 − 11.5·log10(M)   (acclimatized workers)
   ```
   where M is 1-hour time-weighted-average metabolic rate in watts. Cross-
   checked the formula's output against NIOSH's own worked example in the
   same document (a 300 kcal/h moderate-workload case, p.35) — matches
   within the slack expected from their example being a graph-reading, not
   an equation evaluation.
   → `scripts/wbgt.py::niosh_ral_c()` / `niosh_rel_c()`

**Verification:** 20 automated tests across `tests/test_liljegren_wbgt.py`
and `tests/test_wbgt.py`, all passing — includes physical-plausibility
checks (wet-bulb never exceeds dry-bulb, globe temp rises under solar
load, etc.) and the direct numeric regression against Liljegren's compiled
reference C code described above. Run with `pytest tests/` from the repo
root (needs `pytest.ini` present, which points imports at `scripts/`).

**Committed:** `5f85f02` — pushed to `main`.

**Language rule going forward:** UI copy must say "lower-risk outdoor work
windows under estimated WBGT assumptions" — never "safe hours" — and the
NIOSH RAL/REL numbers must always be shown as reference lines for a stated
workload, never as a universal "danger" cutoff.

---

## Step 3 — City list and data pipeline scripts (2026-07-04, in progress)

**City list.** Per the plan's own rule ("lat/lon pulled from a verified
source... not hand-copied from memory"), did not hand-type coordinates.
Found `Vynex/indian-cities-geodata` on GitHub (Apache 2.0 licensed,
sourced from Census 2011 population figures + Google Maps coordinates,
528 Indian cities with population >100,000). Downloaded it via the GitHub
API, sorted by population, took the top 50, then made 3 deliberate swaps
(dropped Kota/Bareilly/Solapur — redundant with other same-climate-zone
cities already on the list — added Bhubaneswar/Kochi/Puducherry) to match
the project's explicit requirement to over-represent humid coastal/eastern
cities rather than just take a strict population cutoff.
→ `heat/data/cities.json` (50 cities: id, name, state, lat, lon,
  2011 census population)

**Live forecast pipeline.** `scripts/fetch_forecast.py` calls Open-Meteo's
Forecast API once per run (batched lat/lon for all 50 cities in a single
HTTP request — confirmed via a live test call that Open-Meteo returns a
JSON array in request order, one object per city, each with its own hourly
block), pulling `temperature_2m, relative_humidity_2m, shortwave_radiation,
wind_speed_10m, surface_pressure` in UTC (kept in UTC rather than IST so
the WBGT solar-position calculation gets true UTC timestamps; IST display
conversion is a frontend concern, not a data-pipeline one). For every
city-hour, computes wet-bulb (Stull) and estimated WBGT (Liljegren), and
skips (rather than fabricates) any hour where Open-Meteo returns a data
gap. Ran it live against the real API: 50 cities x 48 hours = 2,400
city-hours written to `heat/data/latest.json` with no failures. Spot-
checked Jaipur (dry), Chennai (humid coastal), and Kolkata (humid eastern)
by hand — wet-bulb never exceeded dry-bulb, no nulls, WBGT values fell in
a physically sane band.

**Historical normals pipeline.** `scripts/compute_normals.py` is a
one-time (not scheduled) script pulling 30 years of hourly temp+RH per
city from Open-Meteo's Historical/Archive API (1991-2020, ERA5). Tested
the Archive API directly first: a single city's 30-year hourly pull is
~7MB — for 50 cities that's ~350MB, far too much to keep or commit as raw
data. So the script aggregates each city's ~262,800 hourly readings down
to 366 calendar-date entries (mean temp/wet-bulb and climatological-max
temp/wet-bulb, averaged across all 30 years for that MM-DD) immediately
after fetching, and discards the raw hourly response — only the small
aggregated result is written to `heat/data/normals.json`. Verified the
aggregation logic against a real downloaded Chennai history file before
running it for all 50 cities: July 4 normal mean temp came out to 30.5°C
and January 15 to 24.1°C, both consistent with Chennai's known climate;
Feb 29 correctly averaged over only 8 (leap) years out of 30.

*(GitHub Actions workflow and final commit for this step: below, once the
full 50-city normals run finishes.)*
