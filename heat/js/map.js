/*
 * Interactive India map -- the misranking-delta overlay is the default
 * layer, with toggles for current wet-bulb and anomaly-vs-1991-2020-normal.
 * Built with Leaflet (CDN, MIT-licensed) + OpenStreetMap tiles + a vendored,
 * simplified India state-boundary GeoJSON (see heat/data/india_states.geojson.LICENSE.txt).
 */

const LAYER_DEFS = {
  misrank: {
    label: "Misranking delta",
    caption:
      "Dry-bulb rank minus humid-heat (WBGT) rank, today. Warm colors = " +
      "cities that look less dangerous on ordinary temperature but rank " +
      "far higher once humidity, radiant heat, and wind are counted.",
  },
  wetbulb: {
    label: "Current wet-bulb",
    caption:
      "Wet-bulb temperature right now (Stull 2011 approximation) -- the " +
      "humid-heat physiology story, kept separate from WBGT work-risk bands.",
  },
  anomaly: {
    label: "Anomaly vs. 1991-2020 normal",
    caption:
      "Today's peak wet-bulb minus the climatological normal peak wet-bulb " +
      "for this calendar date (1991-2020, Open-Meteo/ERA5).",
  },
};

function colorForMisrank(delta, maxAbs) {
  // Diverging: blue = overrated on dry-bulb (negative), gray = neutral, red/orange = underrated (climber)
  const t = Math.max(-1, Math.min(1, delta / (maxAbs || 1)));
  if (t >= 0) {
    // 0 -> gray, 1 -> strong orange/red
    const r = Math.round(150 + t * (179 - 150));
    const g = Math.round(150 - t * (150 - 64));
    const b = Math.round(150 - t * (150 - 31));
    return `rgb(${r},${g},${b})`;
  } else {
    const s = -t;
    const r = Math.round(150 - s * (150 - 70));
    const g = Math.round(150 - s * (150 - 100));
    const b = Math.round(150 + s * (200 - 150));
    return `rgb(${r},${g},${b})`;
  }
}

function colorForSequential(value, min, max) {
  const t = max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0.5;
  // pale straw -> deep red
  const r = Math.round(240 + t * (179 - 240));
  const g = Math.round(230 - t * (230 - 64));
  const b = Math.round(200 - t * (200 - 31));
  return `rgb(${r},${g},${b})`;
}

// NIOSH RAL (unacclimatized) / REL (acclimatized) WBGT thresholds for
// "moderate work" (300 kcal/h ~= 349W), evaluated from NIOSH DHHS 2016-106's
// own stated equations -- see scripts/wbgt.py for the source and derivation.
// Duplicated here (not computed dynamically) because this is a browser-side
// script with no access to the Python module; kept as named constants, not
// magic numbers, so the two copies are easy to compare if either changes.
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

function colorForAnomaly(anomaly, maxAbs) {
  const t = Math.max(-1, Math.min(1, anomaly / (maxAbs || 1)));
  if (t >= 0) {
    const r = Math.round(200 + t * (179 - 200));
    const g = Math.round(200 - t * (200 - 64));
    const b = Math.round(200 - t * (200 - 31));
    return `rgb(${r},${g},${b})`;
  } else {
    const s = -t;
    const r = Math.round(200 - s * (200 - 90));
    const g = Math.round(200 - s * (200 - 130));
    const b = Math.round(210 + s * (235 - 210));
    return `rgb(${r},${g},${b})`;
  }
}

async function initMap() {
  const { cities, latest, normals } = await loadAllData();
  const records = computeRanks(buildCityMetrics(cities, latest, normals));

  const map = L.map("map", { scrollWheelZoom: true }).setView([22.5, 80], 5);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 10,
    minZoom: 4,
  }).addTo(map);

  fetch("data/india_states.geojson")
    .then((r) => r.json())
    .then((geo) => {
      L.geoJSON(geo, {
        style: { color: "#55534c", weight: 0.6, fillOpacity: 0, opacity: 0.5 },
        interactive: false,
      }).addTo(map);
    });

  const maxAbsDelta = Math.max(...records.map((r) => Math.abs(r.misrankDelta)), 1);
  const wetBulbValues = records.map((r) => r.currentWetBulb).filter((v) => v != null);
  const minWetBulb = Math.min(...wetBulbValues);
  const maxWetBulb = Math.max(...wetBulbValues);
  const anomalyValues = records.map((r) => r.wetBulbAnomaly).filter((v) => v != null);
  const maxAbsAnomaly = anomalyValues.length ? Math.max(...anomalyValues.map(Math.abs), 1) : 1;

  let currentLayer = "misrank";
  const markers = [];

  function styleFor(record) {
    if (currentLayer === "misrank") {
      const radius = 5 + Math.min(10, Math.abs(record.misrankDelta) * 0.35);
      return { radius, color: colorForMisrank(record.misrankDelta, maxAbsDelta) };
    }
    if (currentLayer === "wetbulb") {
      const v = record.currentWetBulb;
      return { radius: 7, color: v != null ? colorForSequential(v, minWetBulb, maxWetBulb) : "#999" };
    }
    // anomaly
    const a = record.wetBulbAnomaly;
    return { radius: a != null ? 6 + Math.min(8, Math.abs(a) * 2) : 5, color: a != null ? colorForAnomaly(a, maxAbsAnomaly) : "#999" };
  }

  function popupHtml(record) {
    return `
      <div class="popup-city">${record.name}</div>
      <div class="popup-state">${record.state}</div>
      <div class="popup-row"><span class="label">Dry-bulb rank (today)</span><span class="value">#${record.dryBulbRank} of 50</span></div>
      <div class="popup-row"><span class="label">Humid-heat (WBGT) rank</span><span class="value">#${record.wbgtRank} of 50</span></div>
      <div class="popup-row"><span class="label">Peak dry-bulb</span><span class="value">${record.peakDryBulb.toFixed(1)}&deg;C</span></div>
      <div class="popup-row"><span class="label">Peak wet-bulb (Stull)</span><span class="value">${record.peakWetBulb != null ? record.peakWetBulb.toFixed(1) + "&deg;C" : "n/a"}</span></div>
      <div class="popup-row"><span class="label">Peak est. WBGT</span><span class="value">${record.peakWbgt.toFixed(1)}&deg;C</span></div>
      ${record.wetBulbAnomaly != null ? `<div class="popup-row"><span class="label">vs. 1991-2020 normal</span><span class="value">${record.wetBulbAnomaly >= 0 ? "+" : ""}${record.wetBulbAnomaly.toFixed(1)}&deg;C</span></div>` : ""}
      <div class="popup-row" style="margin-top:0.35rem;font-size:0.78rem;color:#55534c;">${wbgtRiskLabel(record.peakWbgt)}</div>
      ${record.misrankDelta >= 10 ? `<div class="popup-climb">Climbs ${record.misrankDelta} ranks under humid-heat vs. ordinary temperature.</div>` : ""}
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
    marker.bindPopup(popupHtml(record));
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

  redraw();

  const generatedDate = new Date(latest.generated_at_utc);
  document.getElementById("data-updated").textContent = generatedDate.toUTCString();
}

initMap().catch((err) => {
  console.error(err);
  document.getElementById("map").innerHTML =
    '<p style="padding:1rem;color:#b3401f;">Could not load map data: ' + err.message + "</p>";
});
