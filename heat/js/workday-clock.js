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

// Tier colors are the design handoff's (design/README.md) and match the
// legend swatches in index.html 1:1.
const CLOCK_TIER_COLOR = {
  "below-rel": "#2f3a44",
  "stress-window": "#7a5238",
  "stress-shoulder": "#ef6a3a",
  "stress-dark": "#6f6486",
  "unknown": "#3a3f46",
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

/** The city currently selected in the shared selector (used by the trend
 * chart, which shows the same city -- one "city view", one selector). */
function getSelectedCityId() {
  return clockSelectedCityId;
}

function renderWorkdayClock(cityId) {
  const changed = clockSelectedCityId !== cityId;
  clockSelectedCityId = cityId;
  if (changed) {
    document.dispatchEvent(new CustomEvent("citychange", { detail: { cityId } }));
  }
  const rel = getRelThreshold();
  const hourly = buildHourlySeriesForCity(cityId, clockLatest, rel);
  const container = document.getElementById("workday-clock");
  container.innerHTML = "";

  if (hourly.length === 0) {
    container.innerHTML = '<p style="color:#ef8a4a;">No hourly data for this city.</p>';
    return;
  }

  const dateKeys = [...new Set(hourly.map((h) => h.istDateKey))].sort();
  const rows = dateKeys.slice(0, 2).map((key) => hourly.filter((h) => h.istDateKey === key));
  const todayIst = nowInIst().dateKey;
  const rowLabels = dateKeys.slice(0, 2).map((key) => {
    const dayNum = (k) => Math.round(Date.parse(k + "T00:00Z") / 86400000);
    const diff = dayNum(key) - dayNum(todayIst);
    const long = formatIstDateLong(key); // "July 5"
    if (diff === 0) return `Today · ${long}`;
    if (diff === 1) return `Tmrw · ${long}`;
    return long;
  });

  const scroll = document.createElement("div");
  scroll.className = "clock-scroll";
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

    // Shaded 11am-5pm avoidance band overlaid across the row (design
    // handoff). Positioned by the row's actual hour span, since a partial
    // day (data starting mid-day) would make fixed 11/24 fractions wrong.
    const firstHour = row[0].istHour;
    const lastHour = row[row.length - 1].istHour;
    const span = lastHour - firstHour + 1;
    const bandStart = Math.max(HAP_WINDOW_START, firstHour);
    const bandEnd = Math.min(HAP_WINDOW_END, lastHour + 1);
    if (bandEnd > bandStart) {
      const band = document.createElement("div");
      band.className = "clock-band";
      band.style.left = `${((bandStart - firstHour) / span) * 100}%`;
      band.style.width = `${((bandEnd - bandStart) / span) * 100}%`;
      if (rowIdx === 0) {
        const bl = document.createElement("div");
        bl.className = "clock-band-label";
        bl.textContent = "AVOID 11–5";
        band.appendChild(bl);
      }
      cellsEl.appendChild(band);
    }

    for (const h of row) {
      const cell = document.createElement("div");
      cell.className = "clock-cell";
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

  scroll.appendChild(table);
  container.appendChild(scroll);

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
  const { cities, latest } = await loadAllData();
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
    '<p style="color:#ef8a4a;">Could not load workday clock: ' + err.message + "</p>";
});
