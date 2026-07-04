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

**GitHub Actions.** `.github/workflows/update-data.yml` runs
`fetch_forecast.py` on a `cron: "0 */6 * * *"` schedule plus a manual
`workflow_dispatch` trigger, with `permissions: contents: write` so the
job can commit the refreshed `latest.json` back to the repo. Didn't just
trust a green checkmark: triggered it manually via `gh workflow run`,
watched it run to completion (`gh run watch`), then confirmed with
`git fetch` that a real bot commit (`af8b275`) actually landed on
`origin/main` — not just that the job reported success.

**Rate-limit bug, found and fixed.** The first full 50-city normals run
crashed at city 7/50 with an HTTP 429 from Open-Meteo's Archive API —
their free tier throttles bursts of requests even though the daily quota
(10k calls/day) is generous. The original script also only wrote its
output at the very end, so the crash threw away all 6 already-fetched
cities. Fixed both problems: added retry with exponential backoff
(respecting `Retry-After` when present) to `fetch_city_history()`, and
changed `main()` to save `normals.json` after every single city and skip
cities already present on a re-run, so a future crash never loses
progress again. Re-ran end-to-end: all 50 cities completed (some needed
up to 4 retries as rate-limit pressure grew through the run), producing
366 calendar-date entries per city.

**Result, spot-checked against real data:** Kochi's normal dry-bulb
temperature for July 4 (25.6°C) looks unremarkable next to Jaipur's
(30.7°C) — but Kochi's wet-bulb sits only 1.3°C below its dry-bulb
(nearly saturated air), while Jaipur's wet-bulb is 6°C below its dry-bulb
(a much drier heat). This is the misranking the dashboard exists to
surface, showing up in the very first real data pulled for it.

**Committed:** `2dcae5c` (city list, fetch script, workflow),
`bc068cb` (50-city normals baseline) — both pushed to `main`.

---

## Step 4 — Map + rank-shift chart (2026-07-04)

**Boundary data licensing check.** The plan called for a vendored India
state-boundary GeoJSON. The obvious candidate (`udit-001/india-maps-data`)
turned out to have **no license at all** on GitHub — meaning default
all-rights-reserved, unsafe to vendor into a public repo regardless of it
being publicly viewable. `geohacker/india` (MIT) had a license but its
state file was 23MB, too large for a browser to load. Found
`datameet/maps` (MIT, DataMeet India community) with a 15.7MB
`states.geojson` — real state boundaries, clear license — and simplified
it myself with `mapshaper` (`-simplify 1.5% -clean`, coordinate precision
truncated to ~100m) down to 140KB, keeping all 36 states/UTs recognizable.
Wrote `heat/data/india_states.geojson.LICENSE.txt` documenting the exact
source, license, and what was modified, per MIT's attribution requirement.

**Built:**
- `heat/js/data.js` — shared ranking logic used by both the map and the
  chart, so they can't disagree. Defines the dashboard's central claim in
  code: "dry-bulb rank" = cities ranked by today's peak dry-bulb temp;
  "humid-heat rank" = same cities ranked by today's peak estimated WBGT;
  "misranking delta" = dry-bulb rank minus humid-heat rank. A big positive
  delta is a "climber" -- a city that looks unremarkable on ordinary
  temperature but ranks near the top of humid-heat danger.
- `heat/js/map.js` — Leaflet map, OpenStreetMap tiles, three toggleable
  layers (misranking delta / current wet-bulb / anomaly vs. normal).
  Popups show a NIOSH RAL/REL-based risk line using the required language
  ("above NIOSH's limit for continuous moderate work" — never "safe
  hours"), with the same NIOSH formula from `scripts/wbgt.py` duplicated
  as a named JS constant (documented why it's duplicated rather than
  shared, since this is a static site with no shared backend).
- `heat/js/slope-chart.js` — Observable Plot slope chart, dry-bulb rank
  (left) vs. WBGT rank (right), with only the top 10 climbers highlighted
  in color so the story isn't buried in 50 crossing gray lines.
- `heat/index.html` / `heat/style.css` — dashboard shell in a "live policy
  memo" register (serif headline type, monospace data labels, muted paper
  background, no startup-bright colors), with the WBGT/wet-bulb language
  discipline stated explicitly in the footer.

**Verification, given a real environment limitation.** The Claude Code
preview tool's sandbox could not access files under this Desktop folder at
all (failed even to `open()` a file there, independent of the code) — a
macOS-level permission wall on that specific tool, not a bug in the site.
Worked around it for everything that doesn't require an actual rendered
DOM:
- Wrote `scripts/serve_static.py` (a minimal server avoiding Python's
  stdlib `http.server` CLI, whose argparse default calls `os.getcwd()`
  unconditionally — which was itself failing in the sandboxed preview
  process) and ran it via the plain shell tool instead, which faced no
  such restriction.
- Confirmed via `curl` that every asset the page references (`index.html`,
  `style.css`, all three JS files, all four data files) returns HTTP 200.
- Syntax-checked all three JS files with `node --check`.
- **Actually ran the ranking logic**: loaded `heat/js/data.js` in Node
  (Node 26 has native `fetch`) against the real, live data files served
  from the local server, and confirmed `buildCityMetrics`/`computeRanks`
  process all 50 cities with unique ranks and no crashes. Real output:
  Chandigarh, Ludhiana, and a few other North/West cities are today's
  biggest climbers, while several Tamil Nadu cities (Madurai,
  Tiruchirappalli, Chennai) currently rank *lower* on WBGT than dry-bulb —
  a live snapshot of an unusual dry spell there, not a scripted "coastal
  cities always win" result. That the ranking flips day to day is the
  point of building this live rather than as a static infographic.
- Extracted and unit-tested the pure color/label helper functions from
  `map.js` in isolation (`vm.runInThisContext`, since `const`/`let` inside
  a plain `eval()` don't escape to the outer scope the way `var` would) —
  confirmed the JS-side NIOSH RAL/REL constants (24.05°C / 27.46°C) match
  the Python-side values in `scripts/wbgt.py` exactly.
- **What's not verified:** actual browser rendering (does the Leaflet map
  actually draw markers in the right place, do hover/click interactions
  work, does the layer toggle visually update, does the chart render
  without layout glitches). This needs a real browser — the dashboard is
  live at https://smar98.github.io/india-heat-monitor/heat/ for that check.

**Committed:** `10fee3c` — pushed to `main`, live on GitHub Pages
(confirmed via `curl` against the actual public URL, not just that Pages
reported a successful build).

---

## Step 5 — Workday clock (2026-07-04)

**Live bug report from the user, fixed first.** Before starting step 5,
the user opened the step-4 dashboard on their phone and reported "Could
not load chart data: Plot is not defined." Root-caused it directly (not
guessed): `@observablehq/plot@2` doesn't exist as a version — Plot is
still pre-1.0 (latest is 0.6.17) — so the CDN URL 404'd. Also found a
second, not-yet-triggered bug while fixing the first: the correct package
path (`dist/plot.umd.min.js`) depends on a global `d3` that was never
loaded. Fixed both, then actually verified the fix (not just "should
work") by loading both corrected CDN URLs in a sandboxed Node `vm`
context in the exact script order the page uses, and confirming
`typeof Plot.plot === "function"` before pushing. User confirmed it looks
okay after the fix and said to keep going.

**Built:** `heat/js/workday-clock.js` — a per-city hourly grid (today +
tomorrow, in true IST wall-clock time) colored by NIOSH RAL/REL risk tier,
with night hours (19:00–06:00 IST) visually outlined so the "heat doesn't
end at sunset" claim is visible rather than asserted. Defaults to today's
biggest misranking climber (ties this view back to the map/chart without
extra clicking), with a dropdown covering all 50 cities.

**Refactor while building it:** centralized the NIOSH RAL/REL constants
and `wbgtRiskLabel()` from `map.js` into `data.js`, since the clock needed
the same numbers — avoided a third copy of the same formula rather than
letting it drift.

**Two bugs found and fixed via actually running the code, not review:**
1. `map.js`, `slope-chart.js`, and the new `workday-clock.js` each call
   `loadAllData()` independently — without a cache, that's three separate
   fetches of `normals.json` (~3.7MB) per page load, real wasted data on
   the phone the user is checking this on. Added a shared in-flight/
   completed-request cache inside `loadAllData()`.
2. `buildHourlySeriesForCity()`'s IST time conversion computed the correct
   `Date` object but then formatted its label as `HH:00`, silently
   dropping the minutes. Since IST is UTC+5:30 and Open-Meteo's hourly data
   lands exactly on the UTC hour, every converted timestamp is actually
   `HH:30`, never `HH:00` — every single hour label on this view would
   have been wrong by 30 minutes. Caught this by running the actual
   conversion in Node against the live local server and printing real
   values (`05:30`, not the `05:00` the buggy code produced), not by
   reading the code and assuming it was right.

**Result, from real data:** Chandigarh — today's biggest misranking
climber — shows elevated WBGT risk in all 22 of its forecasted night
hours in this run. That's the workday clock's reason for existing, showing
up immediately in real output.

**Committed:** `acad7d1` (Plot/D3 CDN fix), `fb3603e` (workday clock) —
both pushed to `main` and live at
https://smar98.github.io/india-heat-monitor/heat/

---

## Step 6 — Methods page (2026-07-04)

**Built:** `heat/methods.html` — a public-facing writeup of everything
already verified while building the scientific core: the Stull wet-bulb
formula with its validity range and error bounds, the Liljegren WBGT
method and how the port was verified against the compiled original C
code, the NIOSH RAL/REL formula (and, explicitly, why an earlier flat
ISO-7243-style band scale was dropped — the real ACGIH/ISO 7243 tables
are paywalled and workload-dependent, so publishing invented numbers
under a borrowed standard's name would have been dishonest), full data
source citations with licenses, the misranking-delta definition, and an
AI-transparency note describing how this project was built and verified.

Nothing new to verify here beyond what step 2's work already established
— this step was writing up existing, already-checked facts for a public
reader rather than the build log's internal audience, so no new claims
needed sourcing from scratch.

**Committed:** `89210af` — pushed to `main`, confirmed live at
https://smar98.github.io/india-heat-monitor/heat/methods.html (returns
HTTP 200; checked directly against the public URL, not just that Pages
reported success, per this project's habit of never trusting a green
checkmark alone).

---

## Where things stand after steps 1–6

All four MVP views from the original plan are built and live:
1. **The map** — interactive Leaflet map, misranking-delta default layer,
   toggles for current wet-bulb and anomaly-vs-normal.
2. **Rank-shift chart** — dry-bulb rank vs. WBGT rank, climbers
   highlighted.
3. **Workday clock** — hourly WBGT risk bands per city, including night
   hours, defaulting to today's biggest climber.
4. **Methods page** — full methodology, sources, caveats, AI-transparency
   note.

Plus the data pipeline (6-hourly live updates via GitHub Actions,
1991–2020 historical baseline) and a verified scientific core underneath
all of it.

**Not yet built** (from the original plan, deferred/remaining):
- The root landing page (repo currently has no portfolio homepage — the
  dashboard only exists under `/heat/`, not linked from anywhere at the
  repo root yet).
- Phase 2 ideas explicitly deferred by the original brief: outdoor-
  workforce exposure weighting from Census 2011 economic tables, and a
  historical trend view (dangerous-humid-heat-hours per year since 1940).
- General polish: no live testing yet of edge cases (a city with a WBGT
  solver non-convergence, mobile layout at very small widths beyond what
  the user already checked, dark mode, print/share behavior).
