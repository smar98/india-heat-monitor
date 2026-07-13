/*
 * Interactive India map (Leaflet). Default layer: today's overlooked hours
 * per city (work-stress hours outside the 11am-5pm avoidance window, sun up,
 * at the selected workload) -- the same metric as the headline, spatially.
 * Toggle layers: district worker-hours at risk, and the e-Shram registry.
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
  eshram: {
    label: "Outdoor workforce — e-Shram registry",
    tag: "e-Shram · registrations",
    caption:
      "Live recency check: e-Shram outdoor-sector registrations " +
      "(agriculture + construction, Ministry of Labour, cumulative since " +
      "2021), folded to the 2011 census district frame -- darker = more " +
      "registered outdoor workers. Districts created after 2011 are " +
      "counted in their 2011 parent; Telangana's fold into undivided Andhra Pradesh " +
      "(see popup). Registrations are not a workforce count.",
  },
};

// Design-handoff map tokens.
const MAP_THEME = {
  land: "#1c2229",
  border: "#2f3945",
  zero: "#4a5460",
  // One orange family, light -> dark, dark = worse (same scale the district
  // layer uses, so every layer reads the same way).
  warm: ["#fbdcb2", "#e07f33", "#8f3d08"],
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

async function initMap() {
  const { cities, latest } = await loadAllData();
  const records = buildCityRecords(cities, latest);

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

  let currentLayer = "overlooked";
  const markers = [];
  let labelMarkers = [];

  // Only the "overlooked" layer plots city dots (districts/eshram remove
  // them for the choropleth -- see redraw()), so this has one case.
  function styleFor(record) {
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
      ${shoulderLine}
      ${hapPopupLine(record.state)}
    `;
  }

  /* One-line policy pointer, fed by hap.json via hap-card.js (display-only;
   * the computed window is always the 11-5 union). Silently absent until
   * that file loads or if it fails. */
  function hapPopupLine(state) {
    if (typeof _hap === "undefined" || !_hap) return "";
    const plan = _hap.plans[state];
    const text = plan
      ? `State HAP on paper: ${plan.window_display} (${plan.short})`
      : `State HAP window not audited here &mdash; count uses the widest audited window (11&ndash;5)`;
    return `<div class="popup-row" style="color:#8b95a1;font-size:11px;">${text}</div>`;
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
        // The e-Shram registry layer is optional: if its file is missing
        // the risk layer must keep working, so a failed fetch resolves to null.
        fetch("data/district_eshram.json").then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]).then(([geo, workers, daily, eshram]) => {
        districtBundle = { geo, workers, daily, eshram };
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

  const fmtWorkerHours = formatWorkerCount; // shared formatter from data.js

  /* Two district modes share the geometry, ramp, and bin logic:
   * "risk" (worker-hours at risk today) and "registry" (e-Shram
   * cumulative outdoor registrations). */
  function districtMode() {
    return currentLayer === "eshram" ? "registry" : "risk";
  }

  function districtValue(code) {
    if (districtMode() === "registry") {
      const e = districtBundle.eshram && districtBundle.eshram.districts[String(code)];
      return e ? e.agri + e.constr : null;
    }
    const info = districtInfo(code);
    return info ? info.exposure : null;
  }

  function computeDistrictBins() {
    const values = [];
    for (const feat of districtBundle.geo.features) {
      const v = districtValue(feat.properties.censuscode);
      if (v != null && v > 0) values.push(v);
    }
    values.sort((a, b) => a - b);
    const q = (p) => values.length ? values[Math.min(values.length - 1, Math.floor(p * values.length))] : 0;
    // Both measures are heavily right-skewed (a few huge rural districts),
    // so the class breaks are quantiles of the NONZERO values, not equal steps.
    districtBins = [q(0.4), q(0.7), q(0.9), q(0.98)];
  }

  // Sequential class ramp: ONE hue with monotonically increasing lightness
  // (13.5x relative-luminance spread bottom->top), because on a dark map
  // lightness -- not hue wobble -- is what reads as magnitude. Brightest =
  // most worker-hours at risk.
  // Light -> dark within one orange family: darker = more worker-hours at
  // risk. Verified numerically: monotonic luminance, ~1.5x between adjacent
  // steps, darkest still 2.2:1 against the landmass.
  const DISTRICT_COLORS = ["#fbdcb2", "#f2ab62", "#e07f33", "#bc5a14", "#8f3d08"];
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
    const v = districtValue(feature.properties.censuscode);
    return {
      fillColor: v != null ? districtColor(v) : DISTRICT_NODATA,
      fillOpacity: 1,
      color: "#0f1216",
      weight: 0.5,
      opacity: 1,
    };
  }

  function districtPopupHtml(feature) {
    const p = feature.properties;
    if (districtMode() === "registry") return registryPopupHtml(p);
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

  // These 10 Andhra Pradesh 2011-census districts are where Telangana sat
  // before its 2014 split; the e-Shram join folds every modern Telangana
  // district's registrations into whichever of these it was carved from
  // (see scripts/build_district_eshram.py). Say so on the popup, not just
  // in methods -- a reader who knows Telangana exists would otherwise read
  // "Warangal, Andhra Pradesh" as a bug.
  const TELANGANA_FOLDED_INTO_AP = new Set([532, 533, 534, 535, 536, 537, 538, 539, 540, 541]);

  function registryPopupHtml(p) {
    const e = districtBundle.eshram && districtBundle.eshram.districts[String(p.censuscode)];
    const w = districtBundle.workers.districts[String(p.censuscode)];
    const asOf = (districtBundle.eshram && districtBundle.eshram.meta && districtBundle.eshram.meta.as_of) || "unknown date";
    const telanganaNote = TELANGANA_FOLDED_INTO_AP.has(p.censuscode)
      ? `<div class="popup-row" style="color:#8b95a1;font-size:11px;">2011 frame: includes districts now in Telangana.</div>`
      : "";
    if (!e) {
      return `<div class="popup-city">${p.DISTRICT}</div>
        <div class="popup-state">${p.ST_NM}</div>
        <div class="popup-row" style="color:#8b95a1;font-size:11px;">No matched e-Shram registrations for this 2011 district.</div>
        ${telanganaNote}`;
    }
    return `
      <div class="popup-city">${p.DISTRICT}</div>
      <div class="popup-state">${p.ST_NM}</div>
      <div class="popup-row"><span class="label">Registered, agriculture</span><span class="value">${fmtWorkerHours(e.agri)}</span></div>
      <div class="popup-row"><span class="label">Registered, construction</span><span class="value">${fmtWorkerHours(e.constr)}</span></div>
      <div class="popup-row"><span class="label">Outdoor workers (Census 2011)</span><span class="value">${w ? fmtWorkerHours(w.outdoor_workers) : "n/a"}</span></div>
      <div class="popup-row" style="color:#8b95a1;font-size:11px;">Registrations (unorganised workers, ages 16&ndash;59) cumulative since 2021, as of ${asOf} &mdash; not a headcount, and not the risk layer's input.</div>
      ${telanganaNote}
    `;
  }

  function renderDistrictLayer() {
    computeDistrictBins();
    if (!districtLayer) {
      districtLayer = L.geoJSON(districtBundle.geo, { style: districtStyle });
      districtLayer.eachLayer((lyr) => {
        lyr.bindPopup(() => districtPopupHtml(lyr.feature));
        // Hover = name; click = the full story. Sticky so it follows the cursor.
        const p = lyr.feature.properties;
        lyr.bindTooltip(`${p.DISTRICT} · ${p.ST_NM}`, {
          sticky: true, direction: "top", className: "district-tip", opacity: 1,
        });
      });
    } else {
      districtLayer.setStyle(districtStyle);
    }
    districtLayer.addTo(map);
  }

  function renderLegend() {
    const host = document.getElementById("map-legend");
    if (!host) return;
    let stops;
    if (currentLayer === "districts" || currentLayer === "eshram") {
      if (!districtBundle) { host.innerHTML = ""; return; }
      const items = [{ label: "0", color: DISTRICT_ZERO }].concat(
        districtBins.map((b, i) => ({ label: `&le;${fmtWorkerHours(b)}`, color: DISTRICT_COLORS[i] })),
        [{ label: `&gt;${fmtWorkerHours(districtBins[districtBins.length - 1])}`, color: DISTRICT_COLORS[4] }]
      );
      const title = currentLayer === "eshram"
        ? "Registered outdoor workers, cumulative (darker = more):"
        : "Worker-hours at risk today (darker = more):";
      host.innerHTML = `<span>${title}</span>` + items.map((s) =>
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

    if (currentLayer === "districts" || currentLayer === "eshram") {
      // Choropleth view: city dots come off (polygon + dots is unreadable).
      for (const { marker } of markers) map.removeLayer(marker);
      renderLabels(); // clears the city labels (non-overlooked layer)
      const captionEl = document.getElementById("layer-caption");
      if (!districtBundle) {
        captionEl.textContent = "Loading district data (boundaries + workforce + today's forecast)…";
        const wanted = currentLayer;
        loadDistrictBundle().then(() => {
          if (currentLayer !== wanted) return; // user already switched away
          redraw();
        }).catch((err) => {
          console.error(err);
          captionEl.textContent = "Could not load district data: " + err.message;
        });
        renderLegend();
        return;
      }
      if (currentLayer === "eshram" && !districtBundle.eshram) {
        captionEl.textContent = "The e-Shram registry file isn't published yet — the layer lights up automatically once it lands.";
        renderLegend();
        return;
      }
      renderDistrictLayer();
      let caveat;
      if (currentLayer === "eshram") {
        // The so-what is the cross-check: say how well the registry agrees
        // with the census map the risk layer leans on, from the data file's
        // own recorded validation stats.
        const meta = districtBundle.eshram.meta || {};
        caveat = meta.spearman_vs_census_outdoor
          ? ` District-for-district, this registry geography agrees closely with the Census-2011 outdoor-workforce map (rank correlation ${meta.spearman_vs_census_outdoor}, snapshot as of ${meta.as_of}) — the risk layer isn't leaning on a stale picture.`
          : "";
      } else {
        // Vintage + staleness, stated with the layer, not buried: workforce
        // shares are 2011; the heat summary is dated and refreshed daily.
        caveat = ` Workforce: Census 2011 (structure moves slowly, but it is 2011 — post-2011 districts appear within parent boundaries). One forecast point per district, ~25 km grid.`;
        const esMeta = districtBundle.eshram && districtBundle.eshram.meta;
        if (esMeta && esMeta.spearman_vs_census_outdoor) {
          caveat += ` Cross-checked against the live e-Shram registry (rank correlation ${esMeta.spearman_vs_census_outdoor} — switch to the e-Shram layer for detail).`;
        }
        const todayIst = nowInIst().dateKey;
        if (districtBundle.daily.ist_date !== todayIst) {
          caveat = ` ⚠ District heat shown is for ${districtBundle.daily.ist_date} (IST) — today's refresh hasn't landed yet.` + caveat;
        }
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
