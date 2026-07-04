/*
 * Workday clock: hourly estimated-WBGT risk bands for one city, today and
 * tomorrow, in IST wall-clock time -- including evening/night hours on
 * purpose. Humid heat can stay in a higher risk band well after sunset as
 * relative humidity climbs, which "just avoid the afternoon" guidance
 * misses; this view is built specifically to make that visible.
 *
 * Risk tiers use the same NIOSH RAL/REL moderate-work thresholds as the
 * map's popups (see data.js), so a city's color here never contradicts
 * what its map popup says.
 */

const RISK_TIER_COLOR = {
  "below-ral": "#cdd6d9",
  "above-ral": "#e0a458",
  "above-rel": "#b3401f",
  "unknown": "#e8e4d8",
};

const RISK_TIER_LABEL = {
  "below-ral": "Below NIOSH's alert limit (RAL) for moderate work",
  "above-ral": "Above RAL (unacclimatized risk), below REL",
  "above-rel": "Above NIOSH's own limit (REL) for moderate work, even heat-acclimatized",
  "unknown": "No estimate (solver did not converge for this hour)",
};

let clockCities = [];
let clockLatest = null;

function renderWorkdayClock(cityId) {
  const hourly = buildHourlySeriesForCity(cityId, clockLatest);
  const container = document.getElementById("workday-clock");
  container.innerHTML = "";

  if (hourly.length === 0) {
    container.innerHTML = '<p style="color:#b3401f;">No hourly data for this city.</p>';
    return;
  }

  const rowLength = 24;
  const rows = [hourly.slice(0, rowLength), hourly.slice(rowLength, rowLength * 2)];
  const rowLabels = ["Today", "Tomorrow"];

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
      cell.className = "clock-cell" + (h.isNight ? " clock-cell-night" : "");
      cell.style.background = RISK_TIER_COLOR[h.riskTier];
      const wbgtText = h.wbgt_status === 0 && h.wbgt_c != null ? `${h.wbgt_c.toFixed(1)}°C WBGT` : "no estimate";
      cell.title = `${h.istLabel} IST -- ${wbgtText} (${RISK_TIER_LABEL[h.riskTier]})${h.isNight ? " -- night hour" : ""}`;
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
}

async function initWorkdayClock() {
  const { cities, latest, normals } = await loadAllData();
  clockCities = cities;
  clockLatest = latest;

  const records = computeRanks(buildCityMetrics(cities, latest, normals));
  const biggestClimber = [...records].sort((a, b) => b.misrankDelta - a.misrankDelta)[0];
  const defaultCityId = biggestClimber ? biggestClimber.id : cities[0].id;

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
  renderWorkdayClock(defaultCityId);

  if (biggestClimber) {
    document.getElementById("clock-default-note").textContent =
      `Defaulted to ${biggestClimber.name} -- today's biggest climber ` +
      `(dry-bulb rank #${biggestClimber.dryBulbRank}, humid-heat rank #${biggestClimber.wbgtRank}).`;
  }
}

initWorkdayClock().catch((err) => {
  console.error(err);
  document.getElementById("workday-clock").innerHTML =
    '<p style="color:#b3401f;">Could not load workday clock: ' + err.message + "</p>";
});
