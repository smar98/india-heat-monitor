/*
 * "So what" card rendered beside the map: today's biggest climbers and
 * fallers, with the physical reason for each climb read from the stored
 * WBGT components at that city's peak-WBGT hour (humidity / sun / wind),
 * so the claim is explainable rather than asserted.
 *
 * Deliberately shows BOTH directions: which cities the dry-bulb ranking
 * understates today (climbers) and which it overstates (fallers). The
 * direction varies day to day -- WBGT also weighs sun and wind -- and
 * pretending it always points at coastal cities would be dishonest.
 */

const N_CLIMBERS_SHOWN = 5;
const N_FALLERS_SHOWN = 3;

// Thresholds for the one-line "why": deliberately coarse -- these pick
// which factors to *mention*, they are not risk thresholds themselves.
const REASON_RH_PCT = 55;
const REASON_SOLAR_WM2 = 650;
const REASON_WIND_MS = 1.0;

function climbReasons(peakHour) {
  if (!peakHour) return "";
  const reasons = [];
  if (peakHour.rh_pct >= REASON_RH_PCT) reasons.push("high humidity");
  if (peakHour.solar_wm2 >= REASON_SOLAR_WM2) reasons.push("strong sun");
  if (peakHour.est_wind_speed_ms != null && peakHour.est_wind_speed_ms <= REASON_WIND_MS) {
    reasons.push("little wind");
  }
  return reasons.length ? reasons.join(" + ") : "combined heat/humidity/sun/wind";
}

function moverRow(r, direction) {
  const arrow = direction === "up" ? "▲" : "▼";
  const cls = direction === "up" ? "mover-up" : "mover-down";
  const reason = direction === "up"
    ? `<div class="mover-reason">${climbReasons(r.peakWbgtHour)}</div>`
    : "";
  return `
    <div class="mover-row ${cls}">
      <div class="mover-head">
        <span class="mover-name">${r.name}</span>
        <span class="mover-delta">${arrow}${Math.abs(r.misrankDelta)}</span>
      </div>
      <div class="mover-detail">dry-bulb #${r.dryBulbRank} &rarr; humid-heat #${r.wbgtRank} &middot; peak est. WBGT ${r.peakWbgt.toFixed(1)}&deg;C</div>
      ${reason}
    </div>`;
}

async function initInsights() {
  const { cities, latest, normals } = await loadAllData();
  const records = computeRanks(buildCityMetrics(cities, latest, normals));

  const sorted = [...records].sort((a, b) => b.misrankDelta - a.misrankDelta);
  const climbers = sorted.filter((r) => r.misrankDelta > 0).slice(0, N_CLIMBERS_SHOWN);
  const fallers = sorted.filter((r) => r.misrankDelta < 0).slice(-N_FALLERS_SHOWN).reverse();

  const el = document.getElementById("insights-card");
  el.innerHTML = `
    <h3>Today's biggest climbers</h3>
    <p class="insights-sub">Cities the ordinary temperature ranking understates today &mdash; and why.</p>
    ${climbers.map((r) => moverRow(r, "up")).join("")}
    <h3>…and the biggest fallers</h3>
    <p class="insights-sub">Cities that look scarier on raw temperature than their humid-heat risk warrants today.</p>
    ${fallers.map((r) => moverRow(r, "down")).join("")}
    <p class="insights-note">Recomputed every 6 hours. The direction changes with the weather &mdash;
    that instability is the finding: a fixed dry-bulb ranking can't capture it.</p>
  `;
}

initInsights().catch((err) => {
  console.error(err);
  const el = document.getElementById("insights-card");
  if (el) el.innerHTML = '<p style="color:#b3401f;">Could not load: ' + err.message + "</p>";
});
