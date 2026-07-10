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
  // The dek carries the so-what: crossing the limit means the body gains
  // heat faster than it can shed it at that work intensity -- the advice
  // relocates the risk into the recommended hours rather than removing it.
  document.getElementById("headline-dek").innerHTML =
    `"Avoid the afternoon, work the morning and evening" &mdash; but for ` +
    `<strong>${workload.label.toLowerCase()}</strong> work, those morning and ` +
    `evening hours are <em>forecast</em> to cross ${rel.toFixed(1)}&deg;C ` +
    `estimated WBGT &mdash; the point above which, per NIOSH, sustained ` +
    `${workload.label.toLowerCase()} work risks heating the body faster ` +
    `than it can cool itself, even for workers used to the heat. The risk ` +
    `isn't removed &mdash; it's relocated to the very hours the advice ` +
    `recommends. Among this 50-city sample; not a national estimate.`;

  // KPI cards.
  document.getElementById("kpi-cities").innerHTML =
    `${summary.citiesWithShoulder} <small>/ ${summary.citiesTotal}</small>`;
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

  // Leaderboard: top cities by overlooked shoulder-hours.
  const listHost = document.getElementById("overlooked-list");
  const top = summary.perCity.filter((c) => c.shoulder > 0).slice(0, 6);
  if (top.length === 0) {
    listHost.innerHTML =
      `<p class="empty">No city crosses the ${workload.label.toLowerCase()}-work limit ` +
      `outside the afternoon window today. Try a heavier workload, or check back as conditions change.</p>`;
  } else {
    listHost.innerHTML = top.map((c) => {
      const label = c.shoulderHours.map((h) => h.istLabel).join(", ");
      return `
        <div class="crow">
          <div>
            <div class="nm">${c.name}</div>
            <div class="st">${c.state}</div>
            <div class="rs">${label} IST &middot; +${c.insideWindow} inside window</div>
          </div>
          <div class="dl">${c.shoulder}<small>HR OUT</small></div>
        </div>`;
    }).join("");
  }

  renderSensPanel();
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
}

initHeadline().catch((err) => {
  console.error(err);
  const el = document.getElementById("overlooked-list");
  if (el) el.innerHTML = '<p class="empty">Could not load: ' + err.message + "</p>";
});
