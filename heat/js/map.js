/*
 * Interactive India map. Default layer: today's overlooked hours per city
 * (work-stress hours outside the 11am-5pm avoidance window, sun up, at the
 * selected workload) -- the same metric as the headline section, shown
 * spatially. Toggle layers: current wet-bulb (a separate humid-heat
 * physiology reading), and anomaly vs the 1991-2020 normal.
 *
 * Built with Leaflet (CDN, MIT) + Esri Light Gray Canvas tiles (English
 * labels) + a vendored, simplified India state-boundary GeoJSON (see
 * heat/data/india_states.geojson.LICENSE.txt).
 */

const LAYER_DEFS = {
  overlooked: {
    label: "Overlooked hours",
    caption:
      "Work-stress hours today that fall OUTSIDE the 11am-5pm avoidance " +
      "window, with the sun up, at the selected workload -- the morning and " +
      "evening hours guidance tells workers to shift into. Bigger, redder " +
      "dots = more overlooked hours.",
  },
  wetbulb: {
    label: "Current wet-bulb",
    caption:
      "Wet-bulb temperature right now (Stull 2011 approximation): how well " +
      "sweating can still cool a person once humidity is counted. A separate " +
      "physiology reading, not the work-stress count.",
  },
  anomaly: {
    label: "Anomaly vs. 1991-2020 normal",
    caption:
      "Today's peak wet-bulb minus the climatological normal peak wet-bulb " +
      "for this calendar date (1991-2020, Open-Meteo/ERA5).",
  },
};

function colorForOverlooked(count, maxCount) {
  if (count <= 0) return "#b9b4a6"; // none today: muted gray
  const t = Math.max(0, Math.min(1, count / (maxCount || 1)));
  const r = Math.round(230 + t * (179 - 230));
  const g = Math.round(165 - t * (165 - 64));
  const b = Math.round(140 - t * (140 - 31));
  return `rgb(${r},${g},${b})`;
}

function colorForSequential(value, min, max) {
  const t = max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0.5;
  const r = Math.round(240 + t * (179 - 240));
  const g = Math.round(230 - t * (230 - 64));
  const b = Math.round(200 - t * (200 - 31));
  return `rgb(${r},${g},${b})`;
}

function colorForAnomaly(anomaly, maxAbs) {
  const t = Math.max(-1, Math.min(1, anomaly / (maxAbs || 1)));
  if (t >= 0) {
    const r = Math.round(200 + t * (179 - 200));
    const g = Math.round(200 - t * (200 - 64));
    const b = Math.round(200 - t * (200 - 31));
    return `rgb(${r},${g},${b})`;
  }
  const s = -t;
  const r = Math.round(200 - s * (200 - 90));
  const g = Math.round(200 - s * (200 - 130));
  const b = Math.round(210 + s * (235 - 210));
  return `rgb(${r},${g},${b})`;
}

async function initMap() {
  const { cities, latest, normals } = await loadAllData();
  const records = buildCityMetrics(cities, latest, normals);

  // Per-city work-stress breakdown at the currently selected workload,
  // recomputed on workloadchange so the default layer and popups stay live.
  let workStressById = new Map();
  function recomputeWorkStress() {
    const rel = getRelThreshold();
    const todayKey = nowInIst().dateKey;
    workStressById = new Map();
    for (const r of records) {
      const ws = computeCityWorkStress(r.id, latest, rel, todayKey);
      if (ws) workStressById.set(r.id, ws);
    }
  }
  recomputeWorkStress();

  const map = L.map("map", { scrollWheelZoom: true }).setView([22.5, 80], 5);

  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ", maxZoom: 10, minZoom: 4 }
  ).addTo(map);
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 10, minZoom: 4 }
  ).addTo(map);

  fetch("data/india_states.geojson")
    .then((r) => r.json())
    .then((geo) => {
      L.geoJSON(geo, {
        style: { color: "#55534c", weight: 0.6, fillOpacity: 0, opacity: 0.5 },
        interactive: false,
      }).addTo(map);
    });

  const wetBulbValues = records.map((r) => r.currentWetBulb).filter((v) => v != null);
  const minWetBulb = Math.min(...wetBulbValues);
  const maxWetBulb = Math.max(...wetBulbValues);
  const anomalyValues = records.map((r) => r.wetBulbAnomaly).filter((v) => v != null);
  const maxAbsAnomaly = anomalyValues.length ? Math.max(...anomalyValues.map(Math.abs), 1) : 1;

  let currentLayer = "overlooked";
  const markers = [];

  function styleFor(record) {
    if (currentLayer === "overlooked") {
      const ws = workStressById.get(record.id);
      const count = ws ? ws.shoulder : 0;
      const maxCount = Math.max(1, ...[...workStressById.values()].map((w) => w.shoulder));
      return { radius: 5 + Math.min(11, count * 1.4), color: colorForOverlooked(count, maxCount) };
    }
    if (currentLayer === "wetbulb") {
      const v = record.currentWetBulb;
      return { radius: 7, color: v != null ? colorForSequential(v, minWetBulb, maxWetBulb) : "#999" };
    }
    const a = record.wetBulbAnomaly;
    return { radius: a != null ? 6 + Math.min(8, Math.abs(a) * 2) : 5, color: a != null ? colorForAnomaly(a, maxAbsAnomaly) : "#999" };
  }

  // Popup is a function so Leaflet re-evaluates it each open -- it always
  // reflects the currently selected workload without rebinding.
  function popupHtml(record) {
    const ws = workStressById.get(record.id);
    const w = getWorkload();
    const shoulderLine = ws && ws.shoulder > 0
      ? `<div class="popup-climb">${ws.shoulder} overlooked hour${ws.shoulder === 1 ? "" : "s"} today for ${w.label.toLowerCase()} work &mdash; outside the 11&ndash;5 window, sun up${ws.shoulderHours.length ? ` (${ws.shoulderHours.map((h) => h.istLabel).join(", ")} IST)` : ""}.</div>`
      : `<div class="popup-row" style="color:#55534c;font-size:0.8rem;">No overlooked work-stress hours today at ${w.label.toLowerCase()} workload.</div>`;
    return `
      <div class="popup-city">${record.name}</div>
      <div class="popup-state">${record.state}</div>
      ${ws ? `<div class="popup-row"><span class="label">Inside 11&ndash;5 window</span><span class="value">${ws.insideWindow} stress hr</span></div>` : ""}
      ${ws ? `<div class="popup-row"><span class="label">After dark (humidity)</span><span class="value">${ws.darkHumid} hr</span></div>` : ""}
      <div class="popup-row"><span class="label">Current wet-bulb</span><span class="value">${record.currentWetBulb != null ? record.currentWetBulb.toFixed(1) + "&deg;C" : "n/a"}</span></div>
      ${record.wetBulbAnomaly != null ? `<div class="popup-row"><span class="label">vs. 1991-2020 normal</span><span class="value">${record.wetBulbAnomaly >= 0 ? "+" : ""}${record.wetBulbAnomaly.toFixed(1)}&deg;C</span></div>` : ""}
      ${shoulderLine}
    `;
  }

  for (const record of records) {
    const style = styleFor(record);
    const marker = L.circleMarker([record.lat, record.lon], {
      radius: style.radius,
      fillColor: style.color,
      color: "#1c1c1a",
      weight: 0.75,
      fillOpacity: 0.85,
    }).addTo(map);
    marker.bindPopup(() => popupHtml(record));
    markers.push({ record, marker });
  }

  function redraw() {
    for (const { record, marker } of markers) {
      const style = styleFor(record);
      marker.setStyle({ radius: style.radius, fillColor: style.color });
    }
    document.getElementById("layer-caption").textContent = LAYER_DEFS[currentLayer].caption;
    document.querySelectorAll(".layer-controls button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.layer === currentLayer);
    });
  }

  document.querySelectorAll(".layer-controls button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentLayer = btn.dataset.layer;
      redraw();
    });
  });

  // Keep the default layer + open popups current when workload changes.
  document.addEventListener("workloadchange", () => {
    recomputeWorkStress();
    if (currentLayer === "overlooked") redraw();
  });

  redraw();

  const generatedDate = new Date(latest.generated_at_utc);
  document.getElementById("data-updated").textContent = generatedDate.toUTCString();

  // Stale-data guard. The pipeline targets every 6 hours, but GitHub Actions
  // scheduled runs are best-effort and can be delayed or dropped, and a
  // missed run leaves the last-good data in place with no server-side signal.
  // So the browser checks the data's actual age and warns if it's older than
  // ~9h (i.e. we've likely missed at least one 6-hour cycle).
  const ageHours = (Date.now() - generatedDate.getTime()) / 3600000;
  const warnEl = document.getElementById("stale-warning");
  if (warnEl && ageHours > 9) {
    warnEl.hidden = false;
    warnEl.textContent =
      `⚠ Data is ${Math.round(ageHours)} hours old (target refresh is every 6 hours). ` +
      `Automated updates can lag; the figures below may not reflect the latest forecast.`;
  }
}

initMap().catch((err) => {
  console.error(err);
  document.getElementById("map").innerHTML =
    '<p style="padding:1rem;color:#b3401f;">Could not load map data: ' + err.message + "</p>";
});
