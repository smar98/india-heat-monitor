/*
 * Interactive India map (Leaflet). Default layer: today's overlooked hours
 * per city (work-stress hours outside the 11am-5pm avoidance window, sun up,
 * at the selected workload) -- the same metric as the headline, spatially.
 * Toggle layers: current wet-bulb, and anomaly vs the 1991-2020 normal.
 *
 * Dark console restyle: no raster basemap -- the vendored India state
 * GeoJSON is rendered as a dark landmass (design-handoff tokens), which
 * also sidesteps tile-label language issues entirely. Pan/zoom/popups stay:
 * the interactive map is the centerpiece, per the project brief.
 */

const LAYER_DEFS = {
  overlooked: {
    label: "Overlooked hours",
    tag: "Overlooked · forecast today",
    caption:
      "Work-stress hours today that fall OUTSIDE the 11am-5pm avoidance " +
      "window, with the sun up, at the selected workload -- the morning and " +
      "evening hours guidance tells workers to shift into. Bigger, brighter " +
      "dots = more overlooked hours.",
  },
  wetbulb: {
    label: "Current wet-bulb",
    tag: "Wet-bulb · now",
    caption:
      "Wet-bulb temperature right now (Stull 2011 approximation): how well " +
      "sweating can still cool a person once humidity is counted. A separate " +
      "physiology reading, not the work-stress count.",
  },
  anomaly: {
    label: "Anomaly vs. 1991-2020 normal",
    tag: "Anomaly · vs normal",
    caption:
      "Today's peak wet-bulb minus the climatological normal peak wet-bulb " +
      "for this calendar date (1991-2020, Open-Meteo/ERA5).",
  },
  districts: {
    label: "Workers at risk, by district",
    tag: "Districts · forecast today",
    caption:
      "Where the overlooked workers are: each district is shaded by " +
      "worker-hours at risk today -- its outdoor workforce (farm, " +
      "construction, and mining main workers, Census 2011) multiplied by " +
      "today's overlooked morning/evening hours at the selected workload. " +
      "Darker orange = more people spending more over-limit hours in the " +
      "very hours guidance recommends.",
  },
};

// Design-handoff map tokens.
const MAP_THEME = {
  land: "#1c2229",
  border: "#2f3945",
  zero: "#4a5460",
  warm: ["#c9b79a", "#e0913a", "#ef6a3a"], // ramp for "more heat stress"
  cool: "#7f9fb0",                          // anomaly negative end
  dotStroke: "rgba(0,0,0,.5)",
  glow: "drop-shadow(0 0 4px rgba(239,106,58,.55))",
};

/* Linear interpolation across the warm ramp's hex stops (t in [0,1]). */
function _hexToRgb(hex) {
  return [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
}
function _mix(hexA, hexB, t) {
  const a = _hexToRgb(hexA), b = _hexToRgb(hexB);
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}
function warmRamp(t) {
  t = Math.max(0, Math.min(1, t));
  const [c0, c1, c2] = MAP_THEME.warm;
  return t <= 0.5 ? _mix(c0, c1, t / 0.5) : _mix(c1, c2, (t - 0.5) / 0.5);
}

function colorForOverlooked(count, maxCount) {
  if (count <= 0) return MAP_THEME.zero;
  return warmRamp(count / (maxCount || 1));
}

function colorForSequential(value, min, max) {
  const t = max > min ? (value - min) / (max - min) : 0.5;
  return warmRamp(t);
}

function colorForAnomaly(anomaly, maxAbs) {
  const t = Math.max(-1, Math.min(1, anomaly / (maxAbs || 1)));
  if (t >= 0) return warmRamp(t);
  return _mix(MAP_THEME.zero, MAP_THEME.cool, -t);
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

  const map = L.map("map", {
    scrollWheelZoom: true,
    minZoom: 4,
    maxZoom: 9,
    maxBounds: [[4, 58], [41, 108]],
    attributionControl: true,
    zoomControl: false, // re-added top-right so popups near the top-left corner never sit under it
  }).setView([22.5, 80], 5);
  L.control.zoom({ position: "topright" }).addTo(map);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution(
    'Boundaries: <a href="https://github.com/datameet/maps">DataMeet</a> (MIT)');

  // Dark landmass instead of raster tiles: vendored simplified state shapes.
  fetch("data/india_states.geojson")
    .then((r) => r.json())
    .then((geo) => {
      L.geoJSON(geo, {
        style: {
          color: MAP_THEME.border, weight: 0.7, opacity: 0.9,
          fillColor: MAP_THEME.land, fillOpacity: 1,
        },
        interactive: false,
      }).addTo(map);
      // Keep dots/labels above the landmass polygons.
      for (const { marker } of markers) marker.bringToFront();
    });

  const wetBulbValues = records.map((r) => r.currentWetBulb).filter((v) => v != null);
  const minWetBulb = Math.min(...wetBulbValues);
  const maxWetBulb = Math.max(...wetBulbValues);
  const anomalyValues = records.map((r) => r.wetBulbAnomaly).filter((v) => v != null);
  const maxAbsAnomaly = anomalyValues.length ? Math.max(...anomalyValues.map(Math.abs), 1) : 1;

  let currentLayer = "overlooked";
  const markers = [];
  let labelMarkers = [];

  function styleFor(record) {
    if (currentLayer === "overlooked") {
      const ws = workStressById.get(record.id);
      const count = ws ? ws.shoulder : 0;
      const maxCount = Math.max(1, ...[...workStressById.values()].map((w) => w.shoulder));
      return {
        radius: count <= 0 ? 3.5 : 4 + Math.min(11, count * 1.6),
        color: colorForOverlooked(count, maxCount),
        glow: count > 0,
        opacity: count <= 0 ? 0.55 : 0.9,
      };
    }
    if (currentLayer === "wetbulb") {
      const v = record.currentWetBulb;
      return { radius: 7, color: v != null ? colorForSequential(v, minWetBulb, maxWetBulb) : "#555e69", glow: false, opacity: 0.9 };
    }
    const a = record.wetBulbAnomaly;
    return {
      radius: a != null ? 6 + Math.min(8, Math.abs(a) * 2) : 5,
      color: a != null ? colorForAnomaly(a, maxAbsAnomaly) : "#555e69",
      glow: false,
      opacity: 0.9,
    };
  }

  // Popup is a function so Leaflet re-evaluates it each open -- it always
  // reflects the currently selected workload without rebinding.
  function popupHtml(record) {
    const ws = workStressById.get(record.id);
    const w = getWorkload();
    const shoulderLine = ws && ws.shoulder > 0
      ? `<div class="popup-climb">${ws.shoulder} overlooked hour${ws.shoulder === 1 ? "" : "s"} today for ${w.label.toLowerCase()} work &mdash; outside the 11&ndash;5 window, sun up${ws.shoulderHours.length ? ` (${ws.shoulderHours.map((h) => h.istLabel).join(", ")} IST)` : ""}.</div>`
      : `<div class="popup-row" style="color:#8b95a1;font-size:11px;">No overlooked work-stress hours today at ${w.label.toLowerCase()} workload.</div>`;
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
      color: MAP_THEME.dotStroke,
      weight: 0.7,
      fillOpacity: style.opacity,
    }).addTo(map);
    marker.bindPopup(() => popupHtml(record));
    markers.push({ record, marker });
  }

  /* Mono labels with a dark halo for the top-5 overlooked cities (design
   * handoff). Rebuilt on every redraw; only shown on the overlooked layer. */
  function renderLabels() {
    for (const lm of labelMarkers) map.removeLayer(lm);
    labelMarkers = [];
    if (currentLayer !== "overlooked") return;
    const top = [...workStressById.entries()]
      .map(([id, ws]) => ({ id, shoulder: ws.shoulder }))
      .filter((x) => x.shoulder > 0)
      .sort((a, b) => b.shoulder - a.shoulder)
      .slice(0, 5);
    for (const { id } of top) {
      const record = records.find((r) => r.id === id);
      if (!record) continue;
      const lm = L.marker([record.lat, record.lon], {
        icon: L.divIcon({ className: "city-lbl", html: record.name, iconAnchor: [-9, 7] }),
        interactive: false,
        keyboard: false,
      }).addTo(map);
      labelMarkers.push(lm);
    }
  }

  // ------------------------------------------------------------------
  // District layer: worker-hours at risk (Census 2011 outdoor workforce x
  // today's overlooked hours). All three data files are lazy-loaded the
  // first time the layer is switched on, so the default page load pays
  // nothing for them.
  // ------------------------------------------------------------------
  let districtBundle = null;   // { geo, workers, daily }
  let districtLoadPromise = null;
  let districtLayer = null;    // the L.geoJSON layer, built once
  let districtBins = [];       // exposure thresholds for the current workload

  function loadDistrictBundle() {
    if (!districtLoadPromise) {
      districtLoadPromise = Promise.all([
        fetch("data/india_districts_2011.geojson").then((r) => r.json()),
        fetch("data/district_workers.json").then((r) => r.json()),
        fetch("data/districts_daily.json").then((r) => r.json()),
      ]).then(([geo, workers, daily]) => {
        districtBundle = { geo, workers, daily };
        return districtBundle;
      });
    }
    return districtLoadPromise;
  }

  function districtInfo(code) {
    const w = districtBundle.workers.districts[String(code)];
    const d = districtBundle.daily.districts[String(code)];
    if (!w || !d) return null;
    const hours = d.o[getWorkload().key] || 0;
    return { workers: w, hours, maxWbgt: d.max_wbgt, exposure: w.outdoor_workers * hours };
  }

  function fmtWorkerHours(x) {
    if (x >= 1e6) return `${(x / 1e6).toFixed(1)}M`;
    if (x >= 1e3) return `${Math.round(x / 1e3)}k`;
    return String(Math.round(x));
  }

  function computeDistrictBins() {
    const values = [];
    for (const feat of districtBundle.geo.features) {
      const info = districtInfo(feat.properties.censuscode);
      if (info && info.exposure > 0) values.push(info.exposure);
    }
    values.sort((a, b) => a - b);
    const q = (p) => values.length ? values[Math.min(values.length - 1, Math.floor(p * values.length))] : 0;
    // Exposure is heavily right-skewed (a few huge rural districts), so the
    // class breaks are quantiles of the NONZERO values, not equal steps.
    districtBins = [q(0.4), q(0.7), q(0.9), q(0.98)];
  }

  const DISTRICT_COLORS = [warmRamp(0.12), warmRamp(0.42), warmRamp(0.7), warmRamp(0.88), warmRamp(1)];
  const DISTRICT_ZERO = "#2a323c";
  const DISTRICT_NODATA = "#20262c";

  function districtColor(exposure) {
    if (exposure <= 0) return DISTRICT_ZERO;
    for (let i = 0; i < districtBins.length; i++) {
      if (exposure <= districtBins[i]) return DISTRICT_COLORS[i];
    }
    return DISTRICT_COLORS[DISTRICT_COLORS.length - 1];
  }

  function districtStyle(feature) {
    const info = districtInfo(feature.properties.censuscode);
    return {
      fillColor: info ? districtColor(info.exposure) : DISTRICT_NODATA,
      fillOpacity: 1,
      color: "#0f1216",
      weight: 0.5,
      opacity: 1,
    };
  }

  function districtPopupHtml(feature) {
    const p = feature.properties;
    const info = districtInfo(p.censuscode);
    if (!info) {
      return `<div class="popup-city">${p.DISTRICT}</div>
        <div class="popup-state">${p.ST_NM}</div>
        <div class="popup-row" style="color:#8b95a1;font-size:11px;">No Census-2011 data for this area.</div>`;
    }
    const w = getWorkload();
    const story = info.hours > 0
      ? `<div class="popup-climb">&asymp;${fmtWorkerHours(info.exposure)} worker-hours forecast over the
           heat-stress limit in this district's morning/evening shoulder hours today
           (${w.label.toLowerCase()} work).</div>`
      : `<div class="popup-row" style="color:#8b95a1;font-size:11px;">No overlooked hours forecast today at ${w.label.toLowerCase()} workload.</div>`;
    return `
      <div class="popup-city">${p.DISTRICT}</div>
      <div class="popup-state">${p.ST_NM}</div>
      <div class="popup-row"><span class="label">Outdoor workers (Census 2011)</span><span class="value">${fmtWorkerHours(info.workers.outdoor_workers)}</span></div>
      <div class="popup-row"><span class="label">Overlooked hours today</span><span class="value">${info.hours} hr</span></div>
      <div class="popup-row"><span class="label">Peak est. WBGT today</span><span class="value">${info.maxWbgt != null ? info.maxWbgt.toFixed(1) + "&deg;C" : "n/a"}</span></div>
      ${story}
    `;
  }

  function renderDistrictLayer() {
    computeDistrictBins();
    if (!districtLayer) {
      districtLayer = L.geoJSON(districtBundle.geo, { style: districtStyle });
      districtLayer.eachLayer((lyr) => lyr.bindPopup(() => districtPopupHtml(lyr.feature)));
    } else {
      districtLayer.setStyle(districtStyle);
    }
    districtLayer.addTo(map);
  }

  function renderLegend() {
    const host = document.getElementById("map-legend");
    if (!host) return;
    let stops;
    if (currentLayer === "districts") {
      if (!districtBundle) { host.innerHTML = ""; return; }
      const items = [{ label: "0", color: DISTRICT_ZERO }].concat(
        districtBins.map((b, i) => ({ label: `&le;${fmtWorkerHours(b)}`, color: DISTRICT_COLORS[i] })),
        [{ label: `&gt;${fmtWorkerHours(districtBins[districtBins.length - 1])}`, color: DISTRICT_COLORS[4] }]
      );
      host.innerHTML = `<span>Worker-hours at risk today:</span>` + items.map((s) =>
        `<span class="legend-item"><span class="legend-dot" style="width:13px;height:13px;border-radius:3px;background:${s.color};"></span>${s.label}</span>`
      ).join("");
      return;
    }
    if (currentLayer === "overlooked") {
      const maxCount = Math.max(1, ...[...workStressById.values()].map((w) => w.shoulder));
      const vals = [0, Math.max(1, Math.round(maxCount / 3)), Math.max(2, Math.round((2 * maxCount) / 3)), maxCount];
      stops = vals.map((v) => ({
        label: v === 0 ? "0 hr" : `${v} hr`,
        color: colorForOverlooked(v, maxCount),
        r: v <= 0 ? 3.5 : 4 + Math.min(11, v * 1.6),
      }));
      host.innerHTML = `<span>Overlooked hours (outside 11&ndash;5, sun up):</span>` + legendItems(stops) + `<span>size = hours out</span>`;
    } else if (currentLayer === "wetbulb") {
      const vals = [minWetBulb, (minWetBulb + maxWetBulb) / 2, maxWetBulb];
      stops = vals.map((v) => ({ label: `${v.toFixed(0)}°C`, color: colorForSequential(v, minWetBulb, maxWetBulb), r: 7 }));
      host.innerHTML = `<span>Current wet-bulb:</span>` + legendItems(stops);
    } else {
      const vals = [-maxAbsAnomaly, 0, maxAbsAnomaly];
      stops = vals.map((v) => ({ label: `${v >= 0 ? "+" : ""}${v.toFixed(1)}°C`, color: colorForAnomaly(v, maxAbsAnomaly), r: 7 }));
      host.innerHTML = `<span>Wet-bulb vs. normal:</span>` + legendItems(stops);
    }
  }

  function legendItems(stops) {
    return stops.map((s) =>
      `<span class="legend-item"><span class="legend-dot" style="width:${(s.r * 2).toFixed(0)}px;height:${(s.r * 2).toFixed(0)}px;background:${s.color};"></span>${s.label}</span>`
    ).join("");
  }

  function redraw() {
    const def = LAYER_DEFS[currentLayer];
    document.getElementById("layer-caption").textContent = def.caption;
    const tagEl = document.getElementById("map-panel-tag");
    if (tagEl) tagEl.textContent = def.tag;
    document.querySelectorAll("#layer-rail .layer-btn").forEach((btn) => {
      btn.classList.toggle("on", btn.dataset.layer === currentLayer);
    });

    if (currentLayer === "districts") {
      // Choropleth view: city dots come off (polygon + dots is unreadable).
      for (const { marker } of markers) map.removeLayer(marker);
      renderLabels(); // clears the city labels (non-overlooked layer)
      const captionEl = document.getElementById("layer-caption");
      if (!districtBundle) {
        captionEl.textContent = "Loading district data (boundaries + Census workforce + today's forecast)…";
        loadDistrictBundle().then(() => {
          if (currentLayer !== "districts") return; // user already switched away
          redraw();
        }).catch((err) => {
          console.error(err);
          captionEl.textContent = "Could not load district data: " + err.message;
        });
        renderLegend();
        return;
      }
      renderDistrictLayer();
      // Vintage + staleness, stated with the layer, not buried: workforce
      // shares are 2011; the heat summary is dated and refreshed daily.
      let caveat = ` Workforce: Census 2011 (structure moves slowly, but it is 2011 — post-2011 districts appear within parent boundaries). One forecast point per district, ~25 km grid.`;
      const todayIst = nowInIst().dateKey;
      if (districtBundle.daily.ist_date !== todayIst) {
        caveat = ` ⚠ District heat shown is for ${districtBundle.daily.ist_date} (IST) — today's refresh hasn't landed yet.` + caveat;
      }
      captionEl.textContent = def.caption + caveat;
      renderLegend();
      return;
    }

    if (districtLayer) map.removeLayer(districtLayer);
    for (const { record, marker } of markers) {
      if (!map.hasLayer(marker)) marker.addTo(map);
      const style = styleFor(record);
      marker.setStyle({ radius: style.radius, fillColor: style.color, fillOpacity: style.opacity });
      // Orange glow on dots that carry overlooked hours (SVG filter on the
      // rendered path element; set here because setStyle can't change it).
      const el = marker.getElement();
      if (el) el.style.filter = style.glow ? MAP_THEME.glow : "";
    }
    renderLabels();
    renderLegend();
  }

  document.querySelectorAll("#layer-rail .layer-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentLayer = btn.dataset.layer;
      redraw();
    });
  });

  // Keep the workload-dependent layers + open popups current on change.
  document.addEventListener("workloadchange", () => {
    recomputeWorkStress();
    if (currentLayer === "overlooked" || currentLayer === "districts") redraw();
  });

  redraw();

  // Topbar timestamp, in IST (the audience's clock).
  const generatedDate = new Date(latest.generated_at_utc);
  const istMs = generatedDate.getTime() + (5 * 60 + 30) * 60 * 1000;
  const ist = new Date(istMs); // read via UTC fields = IST wall clock
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  document.getElementById("data-updated").textContent =
    `${DAYS[ist.getUTCDay()]} ${pad(ist.getUTCDate())} ${MONS[ist.getUTCMonth()]}, ` +
    `${pad(ist.getUTCHours())}:${pad(ist.getUTCMinutes())} IST`;

  // Stale-data guard. The pipeline targets every 3 hours, but GitHub Actions
  // scheduled runs are best-effort and can be delayed or dropped, and a
  // missed run leaves the last-good data in place with no server-side signal.
  // So the browser checks the data's actual age and warns past ~9h.
  const ageHours = (Date.now() - generatedDate.getTime()) / 3600000;
  const warnEl = document.getElementById("stale-warning");
  if (warnEl && ageHours > 9) {
    warnEl.hidden = false;
    warnEl.textContent =
      `⚠ Data is ${Math.round(ageHours)} hours old (target refresh is every 3 hours). ` +
      `Automated updates can lag; the figures below may not reflect the latest forecast.`;
  }
}

initMap().catch((err) => {
  console.error(err);
  document.getElementById("map").innerHTML =
    '<p style="padding:1rem;color:#ef8a4a;">Could not load map data: ' + err.message + "</p>";
});
