/*
 * Shared data loading and ranking logic for the India Humid Heat Monitor.
 * Used by both map.js and slope-chart.js so the two views can never
 * disagree about how a city's rank or misranking delta is computed.
 *
 * Core definition (the dashboard's central editorial claim, made concrete):
 *   - "Dry-bulb rank": cities ranked by today's peak (max) dry-bulb air
 *     temperature, hottest = rank 1. This is the public-conversation metric.
 *   - "Humid-heat rank": the same cities ranked by today's peak estimated
 *     WBGT, highest = rank 1. This is the metric that accounts for
 *     humidity, radiant heat (solar), and wind.
 *   - "Misranking delta" = dry-bulb rank MINUS humid-heat rank. A large
 *     POSITIVE delta means a city looks unremarkable on ordinary
 *     temperature (a high, unremarkable rank number) but is actually near
 *     the top of the humid-heat danger list (a low rank number) -- these
 *     are the "climbers" this dashboard exists to surface. A negative
 *     delta means the opposite: a city that looks scarier on raw
 *     temperature than its humid-heat risk actually warrants.
 *
 * Never mix wet-bulb values into this ranking -- the rank-shift comparison
 * is specifically dry-bulb vs. WBGT (the two metrics the project brief
 * says should be compared), with plain wet-bulb kept as its own separate
 * display metric (see the "current wet-bulb" map layer).
 */

const DATA_BASE = "data";

// map.js, slope-chart.js, and workday-clock.js each call loadAllData() on
// the same page load -- without caching, that's three separate fetches of
// normals.json (~3.7MB) alone. Cache the one in-flight/completed request so
// every caller shares it.
let _loadAllDataPromise = null;

function loadAllData() {
  if (!_loadAllDataPromise) {
    _loadAllDataPromise = (async () => {
      const [citiesResp, latestResp, normalsResp] = await Promise.all([
        fetch(`${DATA_BASE}/cities.json`),
        fetch(`${DATA_BASE}/latest.json`),
        fetch(`${DATA_BASE}/normals.json`),
      ]);
      const [cities, latest, normals] = await Promise.all([
        citiesResp.json(),
        latestResp.json(),
        normalsResp.json(),
      ]);
      return { cities, latest, normals };
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

// Note on normals keying: normals.json aggregates ERA5 hours into UTC
// calendar dates (the one-time compute_normals.py run requested
// timezone=UTC), while the live pipeline works in IST calendar days. We
// look up the normal for today's IST date's "MM-DD". At worst this pairs
// an IST day against a normal whose 24-hour aggregation window is offset
// by 5.5 hours -- for a 30-year climatological average that changes the
// value by well under 0.1 degC day-to-day, so it's an accepted
// approximation (documented in BUILD_LOG.md step 7), not an oversight.

/**
 * Builds one metrics record per city: today's peak dry-bulb, peak WBGT,
 * peak wet-bulb, the hour nearest the real current moment ("current"), and
 * the anomaly of today's peak wet-bulb vs. the 1991-2020 normal for this
 * calendar date. Cities with no valid hourly data are skipped (not
 * zero-filled) so a data gap can't silently masquerade as "no risk."
 *
 * "Today" is the actual current IST calendar date (matched against each
 * hour's real time_ist field), not just "the first 24 array entries" --
 * that distinction matters if the data was fetched close to IST midnight
 * and hasn't refreshed yet by the time a user loads the page.
 */
function buildCityMetrics(cities, latest, normals) {
  const cityById = new Map(cities.map((c) => [c.id, c]));
  const normalsById = normals.cities; // keyed by string(id) in normals.json
  const { dateKey: todayIstDateKey, nowUtcMs } = nowInIst();
  // normals.json is keyed "MM-DD"; use the IST date's month-day so the
  // normal we compare against matches the same calendar day the "today"
  // window (below) is built from.
  const todayKey = todayIstDateKey.slice(5);

  const records = [];
  for (const cityLatest of latest.cities) {
    const city = cityById.get(cityLatest.id);
    if (!city || !cityLatest.hourly || cityLatest.hourly.length === 0) continue;

    const todayHours = cityLatest.hourly.filter((h) => istDateKeyOf(h.time_ist) === todayIstDateKey);
    if (todayHours.length === 0) continue; // data hasn't refreshed for today's IST date yet

    const dryBulbValues = todayHours.map((h) => h.temp_c).filter((v) => v != null);
    const wbgtValues = todayHours
      .filter((h) => h.wbgt_status === 0 && h.wbgt_c != null)
      .map((h) => h.wbgt_c);
    const wetBulbValues = todayHours.map((h) => h.wet_bulb_c).filter((v) => v != null);

    if (dryBulbValues.length === 0 || wbgtValues.length === 0) continue;

    const peakDryBulb = Math.max(...dryBulbValues);
    const peakWbgt = Math.max(...wbgtValues);
    const peakWetBulb = wetBulbValues.length ? Math.max(...wetBulbValues) : null;

    // "Current" = the hour whose true UTC instant is nearest the real
    // current moment, not just the first array entry (which used to be
    // wrong by up to ~12 hours -- see BUILD_LOG.md step 7).
    const nearestHour = [...cityLatest.hourly].sort(
      (a, b) => Math.abs(new Date(a.time_utc + "Z").getTime() - nowUtcMs) -
                Math.abs(new Date(b.time_utc + "Z").getTime() - nowUtcMs)
    )[0];
    const currentWetBulb = nearestHour ? nearestHour.wet_bulb_c : null;
    const currentWbgt = nearestHour && nearestHour.wbgt_status === 0 ? nearestHour.wbgt_c : null;

    const cityNormals = normalsById[String(city.id)];
    const normalToday = cityNormals ? cityNormals.normals_by_date[todayKey] : null;
    const wetBulbAnomaly =
      normalToday && peakWetBulb != null
        ? peakWetBulb - normalToday.normal_max_wet_bulb_c
        : null;

    records.push({
      id: city.id,
      name: city.name,
      state: city.state,
      lat: city.lat,
      lon: city.lon,
      peakDryBulb,
      peakWbgt,
      peakWetBulb,
      currentWetBulb,
      currentWbgt,
      wetBulbAnomaly,
      normalMaxWetBulb: normalToday ? normalToday.normal_max_wet_bulb_c : null,
      peakWbgtHour: todayHours.find((h) => h.wbgt_status === 0 && h.wbgt_c === peakWbgt) || null,
    });
  }
  return records;
}

/** Adds dryBulbRank, wbgtRank, misrankDelta to each record (mutates and returns the array). */
function computeRanks(records) {
  const byDryBulbDesc = [...records].sort((a, b) => b.peakDryBulb - a.peakDryBulb);
  byDryBulbDesc.forEach((r, i) => { r.dryBulbRank = i + 1; });

  const byWbgtDesc = [...records].sort((a, b) => b.peakWbgt - a.peakWbgt);
  byWbgtDesc.forEach((r, i) => { r.wbgtRank = i + 1; });

  for (const r of records) {
    r.misrankDelta = r.dryBulbRank - r.wbgtRank;
  }
  return records;
}

// ---------------------------------------------------------------------------
// NIOSH RAL (unacclimatized) / REL (acclimatized) WBGT thresholds for
// "moderate work" (300 kcal/h ~= 349W), evaluated from NIOSH DHHS 2016-106's
// own stated equations -- see scripts/wbgt.py for the source and derivation.
// Duplicated here rather than computed server-side because this is a static
// site with no shared backend between the Python pipeline and the browser;
// kept as named constants (not magic numbers) so the two copies are easy to
// diff if either changes. Shared by map.js and workday-clock.js.
// ---------------------------------------------------------------------------
const NIOSH_RAL_MODERATE_C = 59.9 - 14.1 * Math.log10(349);
const NIOSH_REL_MODERATE_C = 56.7 - 11.5 * Math.log10(349);

function wbgtRiskLabel(wbgtC) {
  if (wbgtC >= NIOSH_REL_MODERATE_C) {
    return "above NIOSH's own limit (REL) for continuous moderate work, even heat-acclimatized";
  }
  if (wbgtC >= NIOSH_RAL_MODERATE_C) {
    return "above NIOSH's limit (RAL) for unacclimatized workers at moderate work";
  }
  return "below NIOSH's moderate-work alert limits";
}

/** Coarse risk tier for the workday clock's cell coloring. */
function wbgtRiskTier(wbgtC) {
  if (wbgtC >= NIOSH_REL_MODERATE_C) return "above-rel";
  if (wbgtC >= NIOSH_RAL_MODERATE_C) return "above-ral";
  return "below-ral";
}

// ---------------------------------------------------------------------------
// Workload levels + the REL work-stress threshold that depends on them.
//
// The NIOSH REL/RAL limits are not single numbers -- they slide with how hard
// the work is (heavier work => lower safe WBGT). Metabolic rates follow the
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

const WORKLOAD_LEVELS = [
  { key: "light",     label: "Light",      watts: 200, examples: "standing supervision, light assembly" },
  { key: "moderate",  label: "Moderate",   watts: 300, examples: "brisk walking with a load, street vending" },
  { key: "heavy",     label: "Heavy",      watts: 415, examples: "digging, brick-carrying, most farm labour" },
  { key: "very-high", label: "Very heavy", watts: 520, examples: "sustained shovelling, peak harvest / construction bursts" },
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
      riskTier: hasWbgt ? wbgtRiskTier(h.wbgt_c) : "unknown", // kept for backward compat
    };
  });
}
