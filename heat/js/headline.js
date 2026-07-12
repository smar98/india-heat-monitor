/*
 * Console header: the headline count, KPI cards, workload rail, the
 * "most overlooked today" leaderboard, and the by-workload panel.
 *
 * India's Heat Action Plans tell outdoor workers to avoid the afternoon and
 * shift work to the morning and evening. These views show, live, how often
 * those shoulder hours THEMSELVES cross the acclimatized heat-stress limit
 * (REL) for the selected workload. All numbers come from
 * computeOverlookedSummary in data.js -- the same functions the map and
 * clock use, so the views can never disagree.
 *
 * Owns the workload selector (via setWorkload in data.js); the map and the
 * workday clock listen for the resulting "workloadchange" event.
 */

let _headlineCities = null;
let _headlineLatest = null;
let _districtStats = null; // { workers, daily } -- for the workers-at-risk leaderboard

function renderWorkloadRail() {
  const host = document.getElementById("workload-rail");
  host.innerHTML = "";
  const current = getWorkload();
  for (const w of WORKLOAD_LEVELS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.workload = w.key;
    btn.className = "wbtn" + (w.key === current.key ? " on" : "");
    // Visible-on-hover/focus explainer (the ⓘ): what this intensity means
    // in real tasks, and why the limit differs. CSS renders data-tip.
    btn.dataset.tip =
      `${w.label} work ≈ ${w.watts} W — e.g. ${w.examples}. ` +
      `Heavier work makes more body heat, so the WBGT limit is lower ` +
      `(${nioshRelC(w.watts).toFixed(1)}°C here).`;
    btn.setAttribute("aria-label", `${w.label} work, about ${w.watts} watts: ${w.examples}`);
    btn.innerHTML =
      `<span class="wl">${w.label} <span class="info" aria-hidden="true">&#9432;</span></span>` +
      `<span class="rel">${nioshRelC(w.watts).toFixed(1)}&deg;</span>`;
    btn.addEventListener("click", () => setWorkload(w.key));
    host.appendChild(btn);
  }
  // Rail buttons render stacked with a small gap, like the rail chips.
  host.style.display = "flex";
  host.style.flexDirection = "column";
  host.style.gap = "8px";
}

function renderHeadline() {
  const rel = getRelThreshold();
  const workload = getWorkload();
  const summary = computeOverlookedSummary(_headlineCities, _headlineLatest, rel);

  const countEl = document.getElementById("hl-count");
  if (summary.citiesTotal === 0) {
    countEl.textContent = "…";
    document.getElementById("overlooked-list").innerHTML =
      '<p class="empty">No current data available.</p>';
    return;
  }

  // Sensitivity to the ~1C estimation error in WBGT: recompute the headline
  // at the limit +/- 1C. Lower limit (rel-1) => more hours qualify => higher
  // count, so the band runs [count(rel+1) .. count(rel-1)]. This shows the
  // finding survives the estimate's uncertainty rather than hiding it.
  const loose = computeOverlookedSummary(_headlineCities, _headlineLatest, rel - 1);
  const tight = computeOverlookedSummary(_headlineCities, _headlineLatest, rel + 1);
  const cityLo = Math.min(tight.citiesWithShoulder, summary.citiesWithShoulder, loose.citiesWithShoulder);
  const cityHi = Math.max(tight.citiesWithShoulder, summary.citiesWithShoulder, loose.citiesWithShoulder);

  countEl.textContent = `${summary.citiesWithShoulder} of ${summary.citiesTotal}`;
  // Plain-language so-what, kept dynamic per workload: the guidance doesn't
  // remove the risk, it moves it into the hours it recommends instead.
  document.getElementById("headline-dek").innerHTML =
    `India's heat guidance tells outdoor workers to shift into the morning ` +
    `and evening. On hot days, those hours can cross the heat-stress limit ` +
    `just as the afternoon does &mdash; for <strong>${workload.label.toLowerCase()}</strong> ` +
    `work, that's <em>forecast</em> today in <strong>${summary.citiesWithShoulder} of ` +
    `${summary.citiesTotal}</strong> cities. The guidance shifts workers out of ` +
    `one risky window and into another. Among this 50-city sample; not a ` +
    `national estimate.`;

  // KPI cards. The city count's bar is "at least one hour" -- say so, and
  // give the depth distribution descriptively. NIOSH's limit applies to
  // each hour of continuous work; it defines no hours-per-day threshold,
  // so none is invented here (see methods).
  const deep = summary.perCity.filter((c) => c.shoulder >= 3).length;
  document.getElementById("kpi-cities").innerHTML =
    `${summary.citiesWithShoulder} <small>/ ${summary.citiesTotal}</small>`;
  document.getElementById("kpi-cities-k").innerHTML =
    `Cities forecast to have at least one overlooked work-stress hour today` +
    (deep > 0 ? ` &mdash; <strong>${deep}</strong> of them for 3+ hours` : ``) +
    `. Among this 50-city sample`;
  document.getElementById("kpi-hours").textContent = summary.totalShoulderHours;
  document.getElementById("kpi-hours-k").innerHTML =
    `City-hours outside the window, over the limit, sun up &mdash; forecast, not observed` +
    (summary.totalDarkHumid > 0
      ? `. (+${summary.totalDarkHumid} after dark, humidity-driven, reported separately)`
      : ``);
  const top0 = summary.perCity.find((c) => c.shoulder > 0);
  const kpiTop = document.getElementById("kpi-top");
  const kpiTopK = document.getElementById("kpi-top-k");
  if (top0) {
    kpiTop.textContent = top0.name;
    const hoursLabel = top0.shoulderHours.map((h) => h.istLabel).join(", ");
    kpiTopK.innerHTML = `Most overlooked today &mdash; ${top0.shoulder} hr at ${hoursLabel} IST`;
  } else {
    kpiTop.textContent = "—";
    kpiTopK.textContent = `No city crosses the ${workload.label.toLowerCase()}-work limit outside the window today`;
  }
  document.getElementById("kpi-band").textContent = `${cityLo}–${cityHi}`;

  renderWorkersLeaderboard();
  renderSensPanel();
}

/* Leaderboard: districts ranked by worker-hours at risk today -- the
 * district layer's own metric (Census-2011 outdoor workers x today's
 * overlooked hours at the selected workload), so the list and the map can
 * never disagree. */
function renderWorkersLeaderboard() {
  const listHost = document.getElementById("overlooked-list");
  if (!listHost) return;
  if (!_districtStats) {
    listHost.innerHTML = `<p class="empty">Loading district workforce data&hellip;</p>`;
    return;
  }
  const workload = getWorkload();
  const rows = [];
  for (const [code, w] of Object.entries(_districtStats.workers.districts)) {
    const d = _districtStats.daily.districts[code];
    if (!d) continue;
    const hours = d.o[workload.key] || 0;
    if (hours > 0) rows.push({ w, hours, exposure: w.outdoor_workers * hours });
  }
  rows.sort((a, b) => b.exposure - a.exposure);
  const top = rows.slice(0, 6);
  if (top.length === 0) {
    listHost.innerHTML =
      `<p class="empty">No district has overlooked hours forecast today at ` +
      `${workload.label.toLowerCase()} workload.</p>`;
    return;
  }
  listHost.innerHTML = top.map(({ w, hours, exposure }) => `
    <div class="crow">
      <div>
        <div class="nm">${w.name}</div>
        <div class="st">${w.state || ""}</div>
        <div class="rs">&asymp;${formatWorkerCount(w.outdoor_workers)} outdoor workers &times; ${hours} hr overlooked</div>
      </div>
      <div class="dl">${formatWorkerCount(exposure)}<small>WORKER-HRS</small></div>
    </div>`).join("");
}

/* "By workload": cities affected at each workload's REL -- the same forecast
 * read against all four thresholds, with the selected one highlighted. */
function renderSensPanel() {
  const host = document.getElementById("sens-panel");
  if (!host) return;
  const current = getWorkload();
  const counts = WORKLOAD_LEVELS.map((w) => {
    const rel = nioshRelC(w.watts);
    const s = computeOverlookedSummary(_headlineCities, _headlineLatest, rel);
    return { w, rel, count: s.citiesWithShoulder };
  });
  const maxCount = Math.max(1, ...counts.map((c) => c.count));
  host.innerHTML = counts.map(({ w, rel, count }) => `
    <div class="srow${w.key === current.key ? " on" : ""}">
      <div class="sh"><span>${w.label} <span class="rel">${rel.toFixed(1)}&deg;C</span></span><span class="cnt">${count}</span></div>
      <div class="track"><div class="fill" style="width:${Math.round((count / maxCount) * 100)}%"></div></div>
    </div>`).join("");
}

async function initHeadline() {
  const { cities, latest } = await loadAllData();
  _headlineCities = cities;
  _headlineLatest = latest;

  renderWorkloadRail();
  renderHeadline();

  document.addEventListener("workloadchange", () => {
    renderWorkloadRail();
    renderHeadline();
  });

  // The leaderboard's two district files (~110KB total; the big boundary
  // geometry is NOT needed here) load after the main view renders.
  Promise.all([
    fetch("data/district_workers.json").then((r) => r.json()),
    fetch("data/districts_daily.json").then((r) => r.json()),
  ]).then(([workers, daily]) => {
    _districtStats = { workers, daily };
    renderWorkersLeaderboard();
  }).catch((err) => {
    console.error(err);
    const el = document.getElementById("overlooked-list");
    if (el) el.innerHTML = '<p class="empty">Could not load district workforce data.</p>';
  });
}

initHeadline().catch((err) => {
  console.error(err);
  const el = document.getElementById("overlooked-list");
  if (el) el.innerHTML = '<p class="empty">Could not load: ' + err.message + "</p>";
});
