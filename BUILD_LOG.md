# Build Log — The Overlooked Hours (formerly India Humid Heat Monitor)

A running record of how this dashboard was built and why the key decisions
went the way they did, kept alongside the code so the reasoning isn't lost.

---

## Step 1 — Repository and hosting (2026-07-04)

Turned the local folder into a git repository, created the public GitHub
repo (`smar98/india-heat-monitor`), pushed the initial commit, and enabled
GitHub Pages (serving from the `main` branch root).

**Why first:** nothing else — data pipeline, frontend — is worth building
until there's a place to push it and a URL for it to appear at, and it's the
cheapest step to get right.

**Decisions:**
- Repo named `india-heat-monitor` rather than a generic `portfolio` name,
  even though it may host a landing page and future dashboards later.
- Public repo — required for free GitHub Pages on a personal account, and a
  portfolio piece is meant to be visible.
- The map and the rank-shift chart would be built in parallel rather than
  naming one "the" centerpiece up front, with a hard requirement that the
  map be genuinely interactive (pan/zoom/hover/click), not static.

---

## Step 2 — Scientific core: wet-bulb, WBGT, risk thresholds (2026-07-04)

Built and verified the three heat metrics the dashboard rests on, keeping
them strictly separate (never compare wet-bulb against WBGT-style
thresholds).

1. **Wet-bulb temperature** — Stull (2011) empirical approximation. The
   formula, its validity range (RH 5–99%, T −20°C to 50°C), and its error
   bounds (−1°C to +0.65°C, mean absolute error <0.3°C) were checked against
   the primary source (Stull, *J. Applied Meteorology and Climatology*
   50(11), 2267–2269, 2011), not a paraphrase of it.
   → `scripts/wbgt.py::wet_bulb_stull()`

2. **Estimated WBGT** — the plan was to vendor **PyWBGT**, but its actual
   LICENSE file turned out to be **CC BY-NC-SA 4.0** (non-commercial,
   share-alike) — awkward to vendor into a repo meant to be freely reusable.
   Switched to **mdljts/wbgt**, confirmed **MIT-licensed**, which contains
   **James Liljegren's original 2008 Argonne C algorithm** directly (with
   both the MIT wrapper license and the original Argonne open-source license
   preserved). The C source was ported to Python from the full original,
   with the complete license chain kept in the file's docstring.
   - **The port was verified against ground truth, not by inspection:**
     Liljegren's original C (with its own demo driver) was compiled with
     `gcc` and run on two test cases (a hot/humid daytime scenario and a
     nighttime one); the Python port's output matched the compiled binary to
     within ~0.02–0.1°C — floating-point precision noise between C `float`
     and Python `double`, not a translation error.
   - The cross-check surfaced one real subtlety: the C code centers the
     solar-position calculation at `minute − 0.5·avg` (the met-data
     averaging window), not at the exact timestamp. Passing `avg_minutes=60`
     — matching Open-Meteo's documented "average of the preceding hour"
     convention for solar radiation — produced an exact match.
   - Both C-reference cases are kept as permanent regression tests
     (`tests/test_liljegren_wbgt.py`).
   → `scripts/liljegren_wbgt.py`, wrapped by `scripts/wbgt.py::estimated_wbgt()`

3. **Risk thresholds** — the plan was flat ISO 7243-style bands (<28°C /
   28–30°C / 30–32°C / >32°C), but that turned out to be an invented
   simplification: the real ACGIH/ISO 7243 tables are two-dimensional (vary
   by workload *and* work/rest duty cycle) and are paywalled — confirmed
   directly via OSHA's own Technical Manual, which states the ACGIH TLV
   tables "are copyrighted by ACGIH and is not publicly available." Rather
   than publish invented numbers under a borrowed standard's name, the
   dashboard uses NIOSH's own public, precise formula (DHHS/NIOSH Publication
   2016-106):
   ```
   RAL [°C-WBGT] = 59.9 − 14.1·log10(M)   (unacclimatized workers)
   REL [°C-WBGT] = 56.7 − 11.5·log10(M)   (acclimatized workers)
   ```
   where M is the 1-hour time-weighted-average metabolic rate in watts. The
   formula's output was cross-checked against NIOSH's own worked example in
   the same document (a 300 kcal/h moderate case), matching within the slack
   expected from their example being a graph-reading.
   → `scripts/wbgt.py::niosh_ral_c()` / `niosh_rel_c()`

**Verification:** 20 automated tests (`tests/`), all passing — physical
plausibility checks (wet-bulb never exceeds dry-bulb, globe temp rises under
solar load) plus the numeric regression against Liljegren's compiled C.

**Committed:** `5f85f02`.

**Language rule going forward:** UI copy says "lower-risk outdoor work
windows under estimated WBGT assumptions," never "safe hours," and the NIOSH
numbers are always shown as reference lines for a stated workload, never as a
universal "danger" cutoff.

---

## Step 3 — City list and data pipeline (2026-07-04)

**City list.** Coordinates were pulled from a verified source, not
hand-typed: `Vynex/indian-cities-geodata` (Apache 2.0, sourced from Census
2011 population figures + Google Maps, 528 cities >100k). Sorted by
population, took the top 50, then made three deliberate swaps (dropped
Kota/Bareilly/Solapur as redundant with same-climate-zone cities already on
the list; added Bhubaneswar/Kochi/Puducherry) to ensure humid coastal and
eastern cities are represented rather than a strict population cutoff drying
out the sample.
→ `heat/data/cities.json`

**Live forecast pipeline.** `scripts/fetch_forecast.py` calls Open-Meteo's
Forecast API once per run, batching all 50 cities in a single request
(verified via a live call that Open-Meteo returns results in request order,
one hourly block per city). For every city-hour it computes wet-bulb (Stull)
and estimated WBGT (Liljegren), and skips — rather than fabricates — any hour
with a data gap. First live run wrote 2,400 city-hours with no failures;
Jaipur (dry), Chennai (humid coastal), and Kolkata (humid eastern) were
spot-checked by hand.

**Historical normals.** `scripts/compute_normals.py` (one-time, not
scheduled) pulls 30 years of hourly temp+RH per city from Open-Meteo's
Archive API (1991–2020, ERA5). A single city's 30-year hourly pull is ~7MB —
~350MB across 50 cities, far too much to keep — so the script aggregates each
city's ~262,800 readings to 366 calendar-date entries immediately and
discards the raw response; only the small result is written. The aggregation
was verified against a downloaded Chennai history before running all 50.

**Automation.** `.github/workflows/update-data.yml` runs the fetch on a cron
schedule plus a manual trigger, committing the refreshed `latest.json` back
to the repo. Confirmed end-to-end by triggering it manually and verifying a
real bot commit actually landed on `origin/main` — not just that the job
reported success.

**Rate-limit issue, found and fixed.** The first full normals run hit an HTTP
429 (Open-Meteo throttles request bursts even under the generous daily quota)
partway through, and the original script only saved at the very end, so the
crash discarded everything fetched so far. Both were fixed: retry with
exponential backoff (respecting `Retry-After`), and incremental saving after
each city with skip-on-rerun, so a crash never loses progress. Re-ran to
completion for all 50 cities.

**Committed:** `2dcae5c`, `bc068cb`.

---

## Step 4 — Map and rank-shift chart (2026-07-04)

**Boundary-data licensing.** The obvious candidate (`udit-001/india-maps-data`)
had **no license** on GitHub — default all-rights-reserved, unsafe to vendor.
`geohacker/india` (MIT) was licensed but its state file was 23MB, too large
for a browser. `datameet/maps` (MIT) had a 15.7MB `states.geojson` with clear
provenance; it was simplified with `mapshaper` down to ~140KB, keeping all
36 states/UTs recognizable, with a LICENSE.txt documenting the source and
what was modified.

**Built:**
- `heat/js/data.js` — shared logic so the map and chart can't disagree.
- `heat/js/map.js` — interactive Leaflet map with toggleable layers.
- `heat/js/slope-chart.js` — an Observable Plot rank-shift chart.
- `heat/index.html` / `heat/style.css` — the dashboard shell.

**Verification under a real environment limitation.** The preview tooling's
sandbox couldn't access files under this working folder (a macOS permission
wall on that tool specifically, not a site bug). Everything not requiring a
rendered DOM was verified anyway: a minimal static server
(`scripts/serve_static.py`), `curl` confirming every asset returns 200,
`node --check` on all JS, and — critically — running the real computation
logic in Node against the live local data and confirming it processes all
50 cities without crashes. The JS-side NIOSH constants were confirmed to
match the Python side exactly. Left explicitly unverified until a real
browser: actual marker placement, hover/click, layer toggles, chart layout.

**Committed:** `10fee3c`, confirmed live via `curl` against the public URL.

---

## Step 5 — Workday clock (2026-07-04)

**A CDN bug surfaced in live use, fixed first:** on mobile the dashboard
showed "Could not load chart data: Plot is not defined." Root cause (not
guessed): the pinned `@observablehq/plot@2` version doesn't exist (Plot is
still pre-1.0), so the CDN URL 404'd; the correct path also depends on a
global `d3` that wasn't loaded. Both were fixed and the fix verified by
loading the corrected CDN URLs in the exact script order the page uses and
confirming `typeof Plot.plot === "function"` before pushing.

**Built:** `heat/js/workday-clock.js` — a per-city hourly grid (today +
tomorrow, true IST) colored by risk tier, with night hours outlined so the
"heat doesn't end at sunset" point is visible rather than asserted.

**Refactor:** the NIOSH constants and risk-label helper were centralized into
`data.js` so the clock, map, and chart share one copy rather than letting a
third drift.

**Two bugs caught by running the code, not reviewing it:**
1. Each view called `loadAllData()` independently — three separate fetches of
   the 3.7MB `normals.json` per page load. Added a shared request cache.
2. The IST time conversion computed the right instant but formatted the label
   as `HH:00`, dropping the minutes — and since IST is UTC+5:30 and the data
   lands on the UTC hour, every label was actually `HH:30`. Every hour label
   on the view would have been 30 minutes wrong. Caught by printing real
   converted values (`05:30`, not `05:00`), not by reading the code.

**Committed:** `acad7d1`, `fb3603e`.

---

## Step 6 — Methods page (2026-07-04)

Built `heat/methods.html` — a reader-facing writeup of what was already
verified in the scientific core: the Stull formula with its validity range
and error bounds, the Liljegren method and how the port was checked against
compiled C, the NIOSH formula and why a flat ISO-7243-style scale was
dropped, full data-source citations with licenses, and an AI-transparency
note. Nothing new to verify — this wrote up already-checked facts for a
public reader.

**Committed:** `89210af`, confirmed live (HTTP 200 against the public URL).

---

## Where things stood after steps 1–6

The four MVP views were built and live: the interactive map, the rank-shift
chart, the workday clock, and the methods page — on top of a 3-hourly live
data pipeline, a 1991–2020 baseline, and a verified scientific core.

At this point the project's thesis was still the original "misranking" idea:
rank cities by air temperature vs by estimated WBGT and highlight the cities
that look mild on temperature but rank dangerous on humid heat. The next two
steps are where that thesis was pressure-tested and, ultimately, sharpened
into something more defensible.

---

## Step 7 — External review: time semantics, validation gate, so-what layer (2026-07-04)

The live dashboard was run past an external review alongside a
fresh read-through. That surfaced one genuine launch blocker and several
legitimate improvements.

**The time-window bug (real, and instructive).** The pipeline requested
`timezone=UTC`, so hour 0 of each city's array was midnight UTC of the fetch
day — but the frontend treated hour 0 as "now" and the first 24 entries as
"today." So "current wet-bulb" was actually an hours-old forecast hour, and
the clock's "Today" row ran 05:30 IST today through 04:30 IST tomorrow. Fixed
in two halves: the pipeline now requests `timezone=Asia/Kolkata` and stores
both `time_ist` and a derived `time_utc` (the WBGT solar calc needs true
UTC); the frontend now defines "current" as the hour nearest the real moment
and "today" as the actual IST date, with rows labeled by real date so stale
data reads as stale. The normals join was also moved to the IST month-day
(the ~5.5h aggregation-window offset against UTC-built normals shifts a
30-year mean by <0.1°C, so it's documented rather than re-fetched).

**Data-robustness gate.** New `scripts/validate_latest.py` runs in CI after
every fetch and before every commit: freshness, all 50 cities present once,
contiguous hourly timestamps, physical-range checks, wet-bulb ≤ dry-bulb +
Stull's error bound, WBGT null exactly when the solver failed, and — the
strongest check — the stored WBGT must recombine from its own stored
components to within rounding. A failed check fails the workflow and the last
valid data stays live. What it still can't prove (no measured-WBGT ground
truth exists to check against; ERA5 grid-vs-street differences) is stated on
the methods page rather than papered over.

**Thesis tightened.** The day's actual "climbers" were inland northern cities
(Chandigarh/Surat/Ludhiana) while some Tamil Nadu cities *fell* — because
WBGT weighs sun and wind, not just humidity. An early framing (a fixed belt
of underrated coastal/eastern cities) isn't what the data shows day to day,
so the copy was changed to the defensible version: which cities dry-bulb
rankings misorder shifts with the weather, and that instability is exactly
why a live dashboard is the right vehicle. This was the first move toward the
Step 8 reframing.

**Also:** a Stull elevation caveat (Srinagar ~1,600m, Bengaluru ~900m — named
explicitly, with the wet-bulb overestimate direction noted and WBGT flagged
as unaffected since Liljegren takes real surface pressure); and a "so-what"
layer — a collapsible explainer and a movers card giving the *physical
reason* (humidity / sun / wind) each city moved, read from the stored WBGT
components.

**Verification:** 20/20 tests, validator green against live data, all JS
`node --check`ed, and the current-hour/IST logic exercised end-to-end in Node
against real served data.

**Committed:** `b16b874`.

---

## Step 8 — Sharpening the thesis: "The Overlooked Hours" (2026-07-05 → 07-08)

This is the project's most important turn, back-filled here for a week the
log skipped. The original "misranking" framing was set aside for a narrower,
more defensible claim, driven by evidence rather than preference.

**Why the reframe.** Three things converged: (1) the live data doesn't
support a stable "humid coastal cities are underrated" story — which cities
climb flips day to day with sun and wind; (2) India's warning system is not
humidity-blind (IMD defines "warm night" and "hot and humid" categories), so
a critique built on "India ignores humidity" wouldn't survive scrutiny; and
(3) two independent reviews both identified the misranking framing
as the weakest, most-attackable part. Rather than defend it, the project narrowed to the
claim the evidence actually supports.

**The reframe** (`7685911`, `ee22b4e`, `4c148c3`): India's Heat Action Plans
give outdoor workers fixed afternoon-avoidance windows and advise shifting
work to the morning/evening. The defensible, hourly finding is that on hot
days those shoulder hours themselves cross the NIOSH REL work-stress limit —
so the guidance relocates risk into the very hours it recommends. The
headline now counts those "overlooked hours" per city for a selectable
workload, wired to the map and clock. All ranking language was removed from
user-facing copy in favor of the government's own vocabulary; the misranking
views were deleted.

**Review-response hardening** (`774941b`, `fef0126`): harmonized the workload
metabolic rates to NIOSH's kcal/h basis after a review caught a units
mismatch; purged self-contradictory "safe hours" language; added a stale-data
banner and moved the cron to every 3h after verifying scheduled runs drift;
added a primary-sourced table of the audited HAP windows (Odisha 2018, AP
2020, Ahmedabad 2019, Delhi 2024-25, NDMA national — verbatim quotes with
page numbers from the actual government PDFs), establishing 11am–5pm as the
conservative union window; and added the ±1°C sensitivity band and a
quantitative map legend.

**Renamed** (`fa073bc`) to **"The Overlooked Hours"** — "Monitor"
over-promised an operational tool. The repo slug stays `india-heat-monitor`
(renaming would break the Pages URL).

---

## Step 9 — Official heat-alert logger: SACHET + IMD CAP (2026-07-10)

**Built** `scripts/fetch_alerts.py`, run by the 3-hourly workflow after the
forecast fetch. Each run it: (a) pulls active alerts from two public official
sources — NDMA's SACHET portal (JSON; includes state-SDMA alerts) and IMD's
signed CAP 1.2 feed (per-alert XML carrying the actual warning polygons) —
keeping the heat-related ones; (b) recomputes, in Python, the exact per-city
REL-exceedance record the frontend shows (mirrored from `heat/js/data.js` and
cross-checked to match); and (c) appends both to monthly logs under
`data/alerts/`. City matching is point-in-polygon for CAP polygons and
equal-area circles for SACHET centroids, never guessed when the coordinate
order is ambiguous.

**Why.** A future "official warnings vs estimated work-stress" comparison is
only honest if it uses *real* warnings, and that dataset only exists from the
day logging starts. Nothing on the site reads it yet, and the methods page
discloses the logging. A "zero alerts" line during monsoon is expected and is
itself the record.

**Failure policy.** The logger can never block the heat-data pipeline: every
fetch is isolated, total failure still exits 0, and source failures are
flagged in the log line so gaps are distinguishable from quiet days —
verified by simulating a total network failure.

**Verification:** 17 new tests (37 total) covering the CAP/SACHET parsers
(real-format fixtures including a real alert polygon), point-in-polygon,
IST→UTC conversion, window boundary semantics, and dedupe. Live run: both
sources 200, 0 heat alerts (July monsoon), 50 city signals; one city's line
was independently recomputed and matched exactly.

---

## Step 10 — Frontend redesign: "The Console" (2026-07-10)

**What changed.** The dashboard was re-skinned to a dark operations-console
layout: a topbar with live status and IST timestamp, a dynamic headline, four
KPI cards, a three-column console (workload/layer rail · Leaflet map ·
"most overlooked today" leaderboard), and a lower row (workday clock with a
shaded avoidance band · a by-workload panel). New type stack (Bricolage
Grotesque / Hanken Grotesk / Spline Sans Mono) and a favicon.

**What deliberately did not change.** The computation: `data.js` is untouched,
and the redesign was verified as a pure re-skin — the new page's headline
count, top city, sensitivity band, and by-workload counts were checked
against a Node re-run of the same functions on the same data and matched
exactly.

**Map: restyled, not replaced.** Leaflet was kept (pan/zoom/popups are the
centerpiece, and the planned district layer needs it) and restyled dark:
raster tiles dropped in favor of the vendored state boundaries as a dark
landmass — which also removes any tile-label issues — with a warm ramp, a
glow on cities with overlooked hours, and labels for the top cities.

**Carried over intact:** the explainer, glossary, stale-data banner, forecast
and sample-size labels, the conservative-lower-bound fine print, the
never-"safe-hours" footer, and the AI-transparency note. The previous light
theme is preserved on the `classic-frontend` branch.

**Verification:** 37/37 tests; all JS `node --check`ed; a banned-language
audit; and full in-browser verification via a sandbox-visible mirror — desktop
and mobile widths, workload switching exercised end-to-end, zero console
errors, methods page confirmed themed.

---

## Step 11 — Historical trend, 1980–2024 (2026-07-10)

Added the long view: overlooked hours per year, per city, from 45 years of
ERA5 reanalysis, using the same Stull/Liljegren/NIOSH code path and the same
overlooked-hour definition as the live count.

**Built** `scripts/compute_trends.py` (a one-time builder modeled on the
normals script — chunked by city × 5-year block, resumable via a cache, with
the same retry/backoff on rate limits) and `heat/js/trend.js` (a hand-rolled
inline-SVG line chart: the yearly series, a ±1°C sensitivity band, a 10-year
mean, and a plain-language takeaway). One city selector now drives both the
workday clock and the trend chart.

**Honesty guards.** The 11am–5pm window is today's audited guidance applied to
past years, labeled as such; 2025 is excluded as incomplete; reanalysis and
the live forecast are different data products and are never read against each
other. The starting year is 1980 (satellite-era ERA5) because pre-satellite
reanalysis is weakest in exactly the variables WBGT leans on — solar and wind.

**Verification:** 8 new aggregation tests (window boundaries, night-vs-day,
the sensitivity-band invariant, cold-hour handling, gap dropping); a real
city-block smoke test before the full run; and in-browser rendering checked
against a stand-in dataset while the full backfill ran.

---

## Step 12 — District layer: workers at risk (2026-07-10)

The map gained its first all-India layer, built story-first: not "here is
district weather" but "how many outdoor workers does the advice overlook,
and where." Each of the 640 Census-2011 districts is shaded by
worker-hours at risk today: its outdoor workforce times its forecast
overlooked hours at the selected workload.

**Workforce data** comes from Census 2011 table B-04 (main workers by
industrial category), parsed per district from the Census bureau's own
per-state files, counting the predominantly-outdoor categories (NIC A
agriculture, B mining, F construction) — ~212 million main workers
nationally, a deliberate under-count of outdoor exposure. Two integrity
gates ran before anything shipped: each state's district counts must sum
exactly to that state's own total row (all 35 states/UTs passed), and every
mapped district must join a workforce record (640/640).

**Heat data** is a new once-daily pipeline: one representative interior
point per district (computed to be guaranteed inside the polygon —
including repairing one invalid coastline geometry the simplification
produced), fetched in 8 batched calls, scored with the same
WBGT-vs-REL definition as everything else, and reduced to per-district
aggregates only (~55KB; no hourly arrays). Its workflow validates the
output (all districts present, plausible ranges) and refuses to commit
otherwise; the layer labels its data date if a refresh is missed.

**Boundaries:** DataMeet Census-2011 district shapefile, simplified ~10MB
→ ~1MB with all 641 shapes retained (including the no-census-data Kashmir
polygon, which renders as no-data rather than being dropped). The 2011
frame is deliberate: the Census join is exact, and post-2011 districts
appear within their parents.

**UI:** a fourth map layer ("Workers at risk, by district") — quantile-
binned choropleth (exposure is heavily right-skewed), plain-words popups
("≈4.2M worker-hours forecast over the heat-stress limit in this
district's shoulder hours today"), a legend in worker-hours, city dots
hidden while the choropleth is up, lazy-loading so the default page pays
nothing, and the 2011-vintage/one-grid-point caveats attached to the layer
itself rather than buried. A methods section covers sources, licenses, the
under-count direction, and why the shading ranks districts rather than
measures them.

**Verification:** 48 tests passing (3 new for the daily summarizer);
integrity gates above; live fetch of all 640 districts; in-browser check
of layer switching, workload re-binning (Light and Heavy produce different
quantile scales), popup content, and city-dot restoration.

**Post-ship polish (same day, from review):** the choropleth's class ramp
was rebuilt after feedback that classes read too alike — the original five
steps varied mostly in hue at similar lightness, and on a dark map
lightness is what reads as magnitude. The new single-hue ramp spans a
13.5× relative-luminance range with monotonic steps (validated
numerically, per the dataviz method: compute, don't eyeball). Districts
gained hover tooltips (name · state) so identification doesn't require a
click. The "most overlooked" city list became "Most workers at risk
today" — districts ranked by the layer's own worker-hours metric, so the
list and the map can never disagree. And a third workforce cross-check
was added: the 640-district file's category sums match the Census's own
separately-published national B-04 row exactly, to the person, in all
three categories (190,206,741 + 1,801,326 + 20,003,533 = 212,011,600).

## Step 13 — The policy overlay: what the rule on paper actually says (Phase 4)

The last planned layer is words, not weather: for the city you're looking
at, what does its state's Heat Action Plan actually tell outdoor workers?
A "rule on paper" card under the workday clock quotes the audited plan
verbatim (window, plan name, source page, link) for the four
primary-sourced plans (Odisha 2018, Andhra Pradesh 2020, Ahmedabad 2019,
Delhi 2024-25); every other state gets an honest "not audited here — the
count uses the widest audited window, so it stays a conservative lower
bound." City map popups carry a one-line version. Everything is
display-only: the computed 11am-5pm union stays the single analysis window.

For teeth, the card and methods page quote the Centre for Policy
Research's 2023 review of 37 HAPs — none identified the legal source of
their authority; only 11 discussed funding at all — with page citations.
One planned feature was cut on source-integrity grounds: per-plan
governance flags. CPR publishes only aggregate findings, no per-plan
scorecard, so per-plan flags would have been invented attribution. The
aggregate quote is labeled as being about India's plans overall, "not a
grade of this plan."

Also in this pass: both GitHub Actions workflows commit before rebasing
(a pull-over-unstaged-output race had the daily district job failing
whenever the 3-hourly job pushed mid-run); the map's warm ramp became one
light-to-dark orange family across every layer after feedback that
dark-brown-to-bright-orange read as two colors rather than a scale (the
caption said "darker = more" — now the colors agree with it); the
Liljegren accuracy caveat now attributes its ~1°C figure to the paper's
own U.S. validation sites and says plainly that no Indian
measured-WBGT validation exists; a root redirect and social-share
metadata were added.

## Step 14 — A live recency check on the workforce map (e-Shram)

The district worker-hours layer weights districts by Census-2011 outdoor
main-worker counts — accurate structure, but 15 years old. This step adds
a second, independent read: e-Shram, the Ministry of Labour's live
registry of unorganised-worker registrations, harvested district-by-
district (agriculture and construction sectors) via data.gov.in's public
API and folded onto the same 2011 district frame the map already uses.

The harvest itself needed persistence: the API's gateway returned 502s
under any concurrency and intermittently under the default Python-urllib
User-Agent specifically — fixed by sending a browser User-Agent and
running the ~2,700 count-queries strictly sequentially, checkpointed so
an interruption costs nothing.

The harder problem was the join. India has created roughly 150 new
districts and renamed several dozen since 2011 — Telangana split whole
from Andhra Pradesh in 2014; Karnataka renamed ten districts that same
year; Assam, Chhattisgarh, Manipur, Rajasthan, Andhra Pradesh, Gujarat,
Tamil Nadu, and others have each carved new districts since. A
first-pass join (documented renames only, plus fuzzy matching) landed at
89.5% coverage with a 0.765 rank correlation against the census layer —
under the ship gates, correctly, because the gap wasn't random noise: it
was concentrated in exactly the states where new districts are newest
and most numerous, which would have shown up as a biased map, not an
honest partial one.

Built out the crosswalk properly instead: a 205-entry rename/split-to-
2011-parent table, covering every state with post-2011 boundary changes,
plus five state-name aliases (the census file's own idiosyncratic
spellings — "Arunanchal Pradesh," "Andaman & Nicobar Island" — and
Telangana, which the 2011 frame has no entry for at all). The audit also
caught a live false-positive already latent in the fuzzy-matching logic
(North Garo Hills was silently matching South Garo Hills at a passing
score; the documented table now assigns it to its real 2011 parent, East
Garo Hills) — the join now logs every fuzzy match it uses so a future
harvest can't repeat that silently.

Result: all 640 census districts join, 0% of registrations unmatched,
rank correlation 0.81. Twenty-two of the newest districts were carved
from more than one 2011 parent; each is assigned to its majority parent,
a modeling choice disclosed on the methods page and bounded at about 1%
of national registrations — small enough that it cannot move the map.
Telangana's registrations, folded into their undivided-Andhra-Pradesh
parents, get their own disclosure in both methods and the map popup
itself, so a reader who knows Telangana exists doesn't read "Warangal,
Andhra Pradesh" as a bug.

Shipped as a fourth map layer ("Outdoor workforce — e-Shram registry"),
sharing the district geometry, ramp, and legend logic with the existing
worker-hours layer. Ship gates were tightened after the fact (coverage
≥98%, unmatched ≤1%, rank correlation ≥0.8) so they now catch future
drift — new districts India creates after this build — rather than
re-litigating the gap this step just closed.

**Correction (same day):** the layer initially shipped as "2026 registry"
and its copy said registrations were "2021-26" — wrong. e-Shram
registrations are a live cumulative total dating back to the portal's
2021 launch; only the harvest/snapshot is dated 2026. Calling it a "2026
registry" read as if the data were scoped to 2026 signups. Renamed to
"e-Shram registry" everywhere (layer label, methods heading, popup rows,
legend, caveat text); the actual snapshot date now surfaces dynamically
from the data file (`meta.as_of`) instead of being hardcoded into copy
that would otherwise go stale.

## Step 15 — Dropped the wet-bulb and anomaly map layers (2026-07-13)

The map shipped with two general-meteorology layers alongside the
labor-focused ones: "Current wet-bulb" (today's physiology reading) and
"Anomaly vs. 1991-2020 normal" (today's peak wet-bulb minus the
climatological normal for the date). Both predate the project's pivot to
a labor-exposure story and neither one advanced it — a raw wet-bulb
reading and a same-day climate anomaly don't say anything about who is
exposed or when, which is what every other layer on this map now answers
(overlooked hours, district worker-hours at risk, e-Shram registrations).
The anomaly layer specifically was never even documented on the methods
page. Removed both, along with the code and data that only existed to
feed them: `buildCityMetrics()` (replaced with a smaller
`buildCityRecords()` that just resolves city identity + today's-data
presence, since the map still needs that for every remaining layer),
the `normals.json` fetch out of `loadAllData()`, and the now-orphaned
`heat/data/normals.json` (3.7MB) and `scripts/compute_normals.py` — kept
around only for the layers just removed, with nothing else in the
pipeline reading either one. The "1991-2020 historical normal" methods
section, which existed to document that data source, went with it.
The wet-bulb temperature concept itself is untouched — it's still the
first stage of the WBGT pipeline (Stull wet-bulb → Liljegren WBGT → NIOSH
REL) and still explained in the glossary; only the standalone map layers
built on it are gone.

## Step 16 — HAP panel promoted, trend panel made collapsible, correlation cross-referenced (2026-07-13)

Three small fixes from an owner read-through, each planned first and
reviewed after implementation:

**The HAP policy card was reading as a footnote.** It had real content —
a verbatim quoted work-hour window with a source link, plus the CPR-2023
governance finding — but sat as the last element under the workday
clock's color legend, styled at 10.5-12.5px. Gave it its own full-width
panel (`#hap-panel`, between the lower row and the trend panel), split
into two columns: the selected state's audited plan on the left, the
national CPR finding on the right — the visual split itself enforces
that the CPR numbers are a national governance finding, not a grade of
whichever city is selected. `hap.json`'s audited scope is unchanged (4
states/cities + the national advisory); the "not audited here" fallback
is unchanged. No new content was invented — same verbatim quotes, same
sourced numbers, new hierarchy.

**"The long view" is now collapsible**, using the same `<details>`
pattern as the existing explainer/glossary sections, closed by default
(the site's established convention for "secondary to today's snapshot").
Confirmed before shipping that the trend chart's SVG uses a fixed
viewBox scaled by CSS, not a live width measurement, so it renders
correctly the first time the panel opens — no layout bug from starting
hidden. The lazy-load listeners (`citychange`, `workloadchange`) and the
3-second fallback fetch of `trends.json` are untouched and still fire
regardless of open/closed state.

**The census/e-Shram correlation (0.81) now shows up where it's actually
useful.** It defends the "Workers at risk" layer's use of a 15-year-old
census against the objection that it's stale — but the one sentence
citing it only rendered on the e-Shram layer's own caption, which a user
viewing the risk layer would never see. Added a one-line cross-reference
to the risk layer's caption pointing at it, and added a caution to the
methods-page paragraph: both series are absolute counts, so part of the
0.81 agreement is district size, not corroboration of the census levels
themselves — the check is still the right one for a layer that ranks by
absolute worker-hours, just not evidence of anything beyond ranking
agreement.
