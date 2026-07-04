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

async function loadAllData() {
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
}

/** "MM-DD" for a given Date, in UTC (matches how normals.json is keyed). */
function monthDayKey(date) {
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  return `${mm}-${dd}`;
}

/**
 * Builds one metrics record per city: today's peak dry-bulb, peak WBGT,
 * peak wet-bulb, the most-recent hour's wet-bulb ("current"), and the
 * anomaly of today's peak wet-bulb vs. the 1991-2020 normal for this
 * calendar date. Cities with no valid hourly data are skipped (not
 * zero-filled) so a data gap can't silently masquerade as "no risk."
 */
function buildCityMetrics(cities, latest, normals) {
  const cityById = new Map(cities.map((c) => [c.id, c]));
  const normalsById = normals.cities; // keyed by string(id) in normals.json
  const now = new Date();
  const todayKey = monthDayKey(now);

  const records = [];
  for (const cityLatest of latest.cities) {
    const city = cityById.get(cityLatest.id);
    if (!city || !cityLatest.hourly || cityLatest.hourly.length === 0) continue;

    // "Today" = the first 24 hours of the forecast window (matches the
    // pipeline's forecast_days=2 fetch: hour 0 is "now" onward).
    const todayHours = cityLatest.hourly.slice(0, 24);
    if (todayHours.length === 0) continue;

    const dryBulbValues = todayHours.map((h) => h.temp_c).filter((v) => v != null);
    const wbgtValues = todayHours
      .filter((h) => h.wbgt_status === 0 && h.wbgt_c != null)
      .map((h) => h.wbgt_c);
    const wetBulbValues = todayHours.map((h) => h.wet_bulb_c).filter((v) => v != null);

    if (dryBulbValues.length === 0 || wbgtValues.length === 0) continue;

    const peakDryBulb = Math.max(...dryBulbValues);
    const peakWbgt = Math.max(...wbgtValues);
    const peakWetBulb = wetBulbValues.length ? Math.max(...wetBulbValues) : null;
    const currentWetBulb = todayHours[0].wet_bulb_c;
    const currentWbgt = todayHours[0].wbgt_status === 0 ? todayHours[0].wbgt_c : null;

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
