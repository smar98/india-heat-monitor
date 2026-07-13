/*
 * Shared data loading and computation for "The Overlooked Hours".
 * Used by every view (headline, map, chart, workday clock) so they can
 * never disagree about how a number was computed.
 *
 * The dashboard's central claim, made concrete: India's heat guidance
 * tells outdoor workers to avoid the afternoon (we use 11:00-17:00 IST,
 * the union of audited state HAP windows -- see HAP_WINDOW notes below)
 * and shift work to the morning/evening shoulders. This module counts,
 * per city and per selected workload, the hours in those shoulders that
 * THEMSELVES cross the NIOSH acclimatized work-stress limit (REL) while
 * the sun is up -- "the overlooked hours." After-dark exceedances are
 * humidity-driven (the WBGT solar term is ~zero at night) and are always
 * reported separately, never folded into the headline count.
 */

const DATA_BASE = "data";

// headline.js, map.js, and workday-clock.js each call loadAllData() on the
// same page load. Cache the one in-flight/completed request so every caller
// shares it instead of double-fetching cities.json/latest.json.
let _loadAllDataPromise = null;

function loadAllData() {
  if (!_loadAllDataPromise) {
    _loadAllDataPromise = (async () => {
      const [citiesResp, latestResp] = await Promise.all([
        fetch(`${DATA_BASE}/cities.json`),
        fetch(`${DATA_BASE}/latest.json`),
      ]);
      const [cities, latest] = await Promise.all([
        citiesResp.json(),
        latestResp.json(),
      ]);
      return { cities, latest };
    })();
  }
  return _loadAllDataPromise;
}

// IST = UTC+5:30, fixed offset (India does not observe daylight saving time).
const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

/** The real current moment, expressed as IST wall-clock Y/M/D/H/M (a plain
 * object, not a Date, since we only ever need to compare/format its parts --
 * building a real Date from these would just reintroduce a timezone to
 * fight with). */
function nowInIst() {
  const nowUtcMs = Date.now();
  const istMs = nowUtcMs + IST_OFFSET_MS;
  const d = new Date(istMs); // used purely as a UTC-field calendar calculator
  return {
    dateKey: `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`,
    nowUtcMs,
  };
}

/** "YYYY-MM-DD" prefix of an Open-Meteo IST-labeled time string like "2026-07-04T13:00". */
function istDateKeyOf(timeIstString) {
  return timeIstString.slice(0, 10);
}

/**
 * Builds one identity record per city for the MAP (id/name/state/lat/lon).
 * Cities with no valid hourly data today are skipped (not zero-filled) so a
 * data gap can't silently masquerade as "no risk." The overlooked-hours
 * work-stress numbers are computed separately (computeCityWorkStress /
 * *Summary), not here.
 */
function buildCityRecords(cities, latest) {
  const cityById = new Map(cities.map((c) => [c.id, c]));
  const { dateKey: todayIstDateKey } = nowInIst();

  const records = [];
  for (const cityLatest of latest.cities) {
    const city = cityById.get(cityLatest.id);
    if (!city || !cityLatest.hourly || cityLatest.hourly.length === 0) continue;

    const todayHours = cityLatest.hourly.filter((h) => istDateKeyOf(h.time_ist) === todayIstDateKey);
    if (todayHours.length === 0) continue; // data hasn't refreshed for today's IST date yet

    records.push({ id: city.id, name: city.name, state: city.state, lat: city.lat, lon: city.lon });
  }
  return records;
}

// (The old dry-bulb-rank vs WBGT-rank "misranking" computation, and the
// fixed moderate-work NIOSH constants that supported it, were removed when
// the dashboard reframed around the overlooked-hours claim -- see BUILD_LOG.md.
// The NIOSH equations now live below with a selectable workload.)

const MONTH_NAMES = ["January","February","March","April","May","June",
  "July","August","September","October","November","December"];

/** "2026-07-07" -> "July 7" (human date, no leading zero). */
function formatIstDateLong(dateKey) {
  const month = MONTH_NAMES[Number(dateKey.slice(5, 7)) - 1];
  return `${month} ${Number(dateKey.slice(8, 10))}`;
}

/** 4,200,000 -> "4.2M"; 61,500 -> "62k" (worker/worker-hour figures). */
function formatWorkerCount(x) {
  if (x >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
  if (x >= 1e3) return `${Math.round(x / 1e3)}k`;
  return String(Math.round(x));
}

// ---------------------------------------------------------------------------
// Workload levels + the REL work-stress threshold that depends on them.
//
// The NIOSH REL/RAL limits are not single numbers -- they slide with how hard
// the work is (heavier work => lower WBGT limit). Metabolic rates follow the
// ISO 8996 activity classes (average W/m^2 x a standard ~1.8 m^2 worker).
// Occupation examples are ILLUSTRATIVE task intensities, not fixed per-job
// values -- the same job spans a wide range depending on the specific task.
// We report the REL (acclimatized-worker) line, because India's chronically
// heat-exposed outdoor laborers are among the most acclimatized workers
// anywhere; RAL (unacclimatized) would understate their tolerance.
//   REL[degC WBGT] = 56.7 - 11.5*log10(M),  M in watts   (NIOSH DHHS 2016-106)
// ---------------------------------------------------------------------------
function nioshRelC(m) { return 56.7 - 11.5 * Math.log10(m); }
function nioshRalC(m) { return 59.9 - 14.1 * Math.log10(m); }

// Metabolic rates on the NIOSH kcal/h basis (NIOSH DHHS 2016-106's own
// worked example uses 300 kcal/h for moderate work), converted at
// 1 kcal/h = 1.163 W, so the frontend, the methods page, and scripts/wbgt.py
// all use ONE workload scale. Occupation examples are illustrative task
// intensities, not fixed per-job values.
//   light 180 kcal/h -> 209 W | moderate 300 -> 349 | heavy 400 -> 465 | very heavy 500 -> 581
const WORKLOAD_LEVELS = [
  { key: "light",     label: "Light",      watts: 209, examples: "standing supervision, light assembly" },
  { key: "moderate",  label: "Moderate",   watts: 349, examples: "brisk walking with a load, street vending" },
  { key: "heavy",     label: "Heavy",      watts: 465, examples: "digging, brick-carrying, most farm labour" },
  { key: "very-high", label: "Very heavy", watts: 581, examples: "sustained shovelling, peak harvest / construction bursts" },
];
const DEFAULT_WORKLOAD_KEY = "heavy"; // the outdoor laborers this whole story is about

function workloadByKey(key) {
  return WORKLOAD_LEVELS.find((w) => w.key === key) || WORKLOAD_LEVELS[2];
}

// Shared selected-workload state so the headline section and the workday clock
// always agree. setWorkload() fires a DOM event both modules listen for.
let _selectedWorkloadKey = DEFAULT_WORKLOAD_KEY;
function getWorkload() { return workloadByKey(_selectedWorkloadKey); }
function getRelThreshold() { return nioshRelC(getWorkload().watts); }
function setWorkload(key) {
  _selectedWorkloadKey = key;
  document.dispatchEvent(new CustomEvent("workloadchange", { detail: { key } }));
}

// ---------------------------------------------------------------------------
// HAP afternoon-avoidance window, as a CONSERVATIVE bound.
//
// There is no single national work-hour window. Audited state Heat Action
// Plans differ: IMD national advice 12:00-15:00; Andhra Pradesh 12:00-16:00;
// Odisha 11:00-15:30; Gujarat (parts) 13:00-17:00. We take the UNION of the
// audited windows -- earliest start (Odisha's 11:00) to latest end (Gujarat's
// 17:00) -- so an hour flagged "outside the window" falls outside even the
// most generous afternoon-avoidance guidance any audited state uses. That
// makes the overlooked-hours count a LOWER BOUND: under any real state window
// (all narrower), the count can only be higher. No per-state data is claimed.
// ---------------------------------------------------------------------------
const HAP_WINDOW_START = 11; // inclusive IST hour
const HAP_WINDOW_END = 17;   // exclusive IST hour (covers 11:00-16:59)
function isInsideHapWindow(istHour) {
  return istHour >= HAP_WINDOW_START && istHour < HAP_WINDOW_END;
}

// Sun-up cutoff: only daytime hours (meaningful solar load) count toward the
// headline "overlooked shoulder-hours". After dark the WBGT globe/solar term
// is ~zero, so a high night WBGT is essentially wet-bulb (hot+humid) -- real
// discomfort, but already spoken to by IMD's "warm night" category, so we
// report it SEPARATELY rather than folding it into the shoulder-hours claim.
const SUN_UP_WM2 = 50;

/**
 * For one city, classify today's work-stress hours (WBGT >= the selected
 * workload's REL line) into: inside the avoidance window; outside-but-sun-up
 * (the "overlooked shoulder-hours" -- morning/evening, real solar load); and
 * dark/humid (reported separately). Returns null if the city has no valid
 * hours today.
 */
function computeCityWorkStress(cityId, latest, relThreshold, todayDateKey) {
  const series = buildHourlySeriesForCity(cityId, latest).filter(
    (h) => h.istDateKey === todayDateKey && h.wbgt_status === 0 && h.wbgt_c != null
  );
  if (series.length === 0) return null;

  let insideWindow = 0, shoulder = 0, darkHumid = 0;
  const shoulderHours = [];
  for (const h of series) {
    if (h.wbgt_c < relThreshold) continue;
    if (isInsideHapWindow(h.istHour)) {
      insideWindow++;
    } else if (h.solar_wm2 > SUN_UP_WM2) {
      shoulder++;
      shoulderHours.push(h);
    } else {
      darkHumid++;
    }
  }
  return {
    insideWindow,
    shoulder,           // overlooked daytime shoulder-hours (the headline claim)
    darkHumid,          // separate, humidity-driven, reported not headlined
    stressHours: insideWindow + shoulder + darkHumid,
    shoulderHours,      // the actual hour objects, for tooltips / detail
    hoursToday: series.length,
  };
}

/**
 * Aggregate the overlooked-shoulder-hours story across all cities for a given
 * REL threshold (i.e. a given workload). Returns per-city breakdowns (sorted
 * by overlooked shoulder-hours, descending) plus totals for the headline.
 */
function computeOverlookedSummary(cities, latest, relThreshold) {
  const todayDateKey = nowInIst().dateKey;
  const perCity = [];
  for (const c of cities) {
    const ws = computeCityWorkStress(c.id, latest, relThreshold, todayDateKey);
    if (!ws) continue;
    perCity.push({ id: c.id, name: c.name, state: c.state, ...ws });
  }
  perCity.sort((a, b) => b.shoulder - a.shoulder || b.stressHours - a.stressHours);

  const citiesWithShoulder = perCity.filter((c) => c.shoulder > 0).length;
  const totalShoulderHours = perCity.reduce((s, c) => s + c.shoulder, 0);
  const totalDarkHumid = perCity.reduce((s, c) => s + c.darkHumid, 0);
  return {
    perCity,
    citiesWithShoulder,
    citiesTotal: perCity.length,
    totalShoulderHours,
    totalDarkHumid,
    relThreshold,
  };
}

/**
 * Builds the full hourly series (today + tomorrow) for one city, in IST
 * wall-clock time for display, with an `isNight` flag (19:00-06:00 IST) --
 * used by the workday clock to make explicit that humid heat can stay in a
 * higher risk band well after sunset, which plain "avoid the afternoon"
 * guidance misses.
 *
 * time_ist is already IST wall-clock time as labeled by Open-Meteo (the
 * pipeline requests timezone=Asia/Kolkata specifically so this is a direct
 * read, not a UTC+5:30 arithmetic conversion done client-side -- an earlier
 * version did that arithmetic and got the label wrong, see BUILD_LOG.md
 * step 7).
 */
function buildHourlySeriesForCity(cityId, latest, relThreshold) {
  const cityLatest = latest.cities.find((c) => c.id === cityId);
  if (!cityLatest) return [];
  const rel = relThreshold != null ? relThreshold : getRelThreshold();

  return cityLatest.hourly.map((h) => {
    const istHour = Number(h.time_ist.slice(11, 13));
    const istMinute = Number(h.time_ist.slice(14, 16));
    const isNight = istHour >= 19 || istHour < 6;
    const hasWbgt = h.wbgt_status === 0 && h.wbgt_c != null;
    const insideWindow = isInsideHapWindow(istHour);
    const sunUp = h.solar_wm2 > SUN_UP_WM2;
    // Classification for the workday clock, relative to the SELECTED workload:
    //   below-rel      : under the acclimatized work-stress limit
    //   stress-window  : over the limit, inside the afternoon-avoidance window
    //   stress-shoulder: over the limit, outside the window, sun up (overlooked)
    //   stress-dark    : over the limit, outside the window, after dark (humid)
    let clockTier = "unknown";
    if (hasWbgt) {
      if (h.wbgt_c < rel) clockTier = "below-rel";
      else if (insideWindow) clockTier = "stress-window";
      else if (sunUp) clockTier = "stress-shoulder";
      else clockTier = "stress-dark";
    }
    return {
      ...h,
      istHour,
      istMinute,
      istDateKey: istDateKeyOf(h.time_ist),
      istLabel: `${String(istHour).padStart(2, "0")}:${String(istMinute).padStart(2, "0")}`,
      isNight,
      insideWindow,
      sunUp,
      aboveRel: hasWbgt && h.wbgt_c >= rel,
      clockTier,
    };
  });
}
