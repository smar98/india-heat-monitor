/*
 * Workday clock: hourly estimated-WBGT bands for one city, today and
 * tomorrow, in IST wall-clock time. Coloring is relative to the SELECTED
 * workload's REL (acclimatized) heat-stress limit, and distinguishes the
 * three cases that carry the story:
 *   - over the limit INSIDE the 11am-5pm avoidance window (guidance already
 *     tells workers to avoid this),
 *   - over the limit OUTSIDE the window with the sun up = the overlooked
 *     morning/evening shoulder hours (the headline claim),
 *   - over the limit after dark = humidity-driven, which IMD's warm-night
 *     category already speaks to.
 *
 * Listens for workload changes (from the headline section) so the whole page
 * recomputes together.
 */

const CLOCK_TIER_COLOR = {
  "below-rel": "#d7dde0",
  "stress-window": "#e6b8a2",
  "stress-shoulder": "#b3401f",
  "stress-dark": "#8a7f9c",
  "unknown": "#e8e4d8",
};

const CLOCK_TIER_LABEL = {
  "below-rel": "below the heat-stress limit for this workload",
  "stress-window": "over the limit, but inside the 11am-5pm avoidance window (guidance covers this)",
  "stress-shoulder": "over the limit, OUTSIDE the avoidance window, sun up -- an overlooked hour",
  "stress-dark": "over the limit after dark -- humidity-driven (IMD 'warm night' territory)",
  "unknown": "no estimate (solver did not converge for this hour)",
};

let clockCities = [];
let clockLatest = null;
let clockSelectedCityId = null;

function renderWorkdayClock(cityId) {
  clockSelectedCityId = cityId;
  const rel = getRelThreshold();
  const hourly = buildHourlySeriesForCity(cityId, clockLatest, rel);
  const container = document.getElementById("workday-clock");
  container.innerHTML = "";

  if (hourly.length === 0) {
    container.innerHTML = '<p style="color:#b3401f;">No hourly data for this city.</p>';
    return;
  }

  const dateKeys = [...new Set(hourly.map((h) => h.istDateKey))].sort();
  const rows = dateKeys.slice(0, 2).map((key) => hourly.filter((h) => h.istDateKey === key));
  const todayIst = nowInIst().dateKey;
  const rowLabels = dateKeys.slice(0, 2).map((key) => {
    const dayNum = (k) => Math.round(Date.parse(k + "T00:00Z") / 86400000);
    const diff = dayNum(key) - dayNum(todayIst);
    const short = key.slice(5).replace("-", "/");
    if (diff === 0) return `Today ${short}`;
    if (diff === 1) return `Tmrw ${short}`;
    return short;
  });

  const table = document.createElement("div");
  table.className = "clock-grid";

  rows.forEach((row, rowIdx) => {
    if (row.length === 0) return;
    const rowEl = document.createElement("div");
    rowEl.className = "clock-row";

    const label = document.createElement("div");
    label.className = "clock-row-label";
    label.textContent = rowLabels[rowIdx];
    rowEl.appendChild(label);

    const cellsEl = document.createElement("div");
    cellsEl.className = "clock-cells";
    for (const h of row) {
      const cell = document.createElement("div");
      cell.className = "clock-cell" + (h.insideWindow ? " clock-cell-window" : "");
      cell.style.background = CLOCK_TIER_COLOR[h.clockTier];
      const wbgtText = h.wbgt_status === 0 && h.wbgt_c != null ? `${h.wbgt_c.toFixed(1)}°C WBGT` : "no estimate";
      cell.title = `${h.istLabel} IST — ${wbgtText}: ${CLOCK_TIER_LABEL[h.clockTier]}`;
      if (h.istHour % 3 === 0) {
        const tick = document.createElement("div");
        tick.className = "clock-cell-tick";
        tick.textContent = h.istLabel;
        cell.appendChild(tick);
      }
      cellsEl.appendChild(cell);
    }
    rowEl.appendChild(cellsEl);
    table.appendChild(rowEl);
  });

  container.appendChild(table);

  // Per-city one-line takeaway tied to the selected workload.
  const ws = computeCityWorkStress(cityId, clockLatest, rel, todayIst);
  const note = document.getElementById("clock-city-note");
  if (note && ws) {
    const w = getWorkload();
    note.innerHTML = ws.shoulder > 0
      ? `Today, ${clockCities.find((c) => c.id === cityId).name} has <strong>${ws.shoulder} work-stress hour${ws.shoulder === 1 ? "" : "s"}</strong> for ${w.label.toLowerCase()} work outside the 11&ndash;5 avoidance window (sun up), plus ${ws.insideWindow} inside it.`
      : `Today, no ${w.label.toLowerCase()}-work hour crosses the limit outside the 11&ndash;5 window in this city.`;
  }
}

async function initWorkdayClock() {
  const { cities, latest, normals } = await loadAllData();
  clockCities = cities;
  clockLatest = latest;

  // Default to the city with the most overlooked shoulder-hours today, so the
  // clock opens on the sharpest example of the headline claim.
  const summary = computeOverlookedSummary(cities, latest, getRelThreshold());
  const defaultCityId = summary.perCity.length ? summary.perCity[0].id : cities[0].id;

  const select = document.getElementById("clock-city-select");
  const sortedCities = [...cities].sort((a, b) => a.name.localeCompare(b.name));
  for (const c of sortedCities) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.name} (${c.state})`;
    if (c.id === defaultCityId) opt.selected = true;
    select.appendChild(opt);
  }

  select.addEventListener("change", () => renderWorkdayClock(Number(select.value)));
  document.addEventListener("workloadchange", () => {
    if (clockSelectedCityId != null) renderWorkdayClock(clockSelectedCityId);
  });

  renderWorkdayClock(defaultCityId);
}

initWorkdayClock().catch((err) => {
  console.error(err);
  document.getElementById("workday-clock").innerHTML =
    '<p style="color:#b3401f;">Could not load workday clock: ' + err.message + "</p>";
});
