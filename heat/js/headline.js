/*
 * Headline section: "The overlooked hours."
 *
 * India's Heat Action Plans tell outdoor workers to avoid the afternoon and
 * shift work to the morning and evening. This section shows, live, how often
 * those shoulder hours THEMSELVES cross the acclimatized heat-stress limit
 * (REL) for the selected workload -- i.e. the guidance sends workers into
 * hours that aren't actually safe. That is the dashboard's central,
 * empirically-verified claim.
 *
 * It owns the workload selector (via setWorkload in data.js), which the
 * workday clock also listens to, so the whole page recomputes together.
 */

function renderWorkloadControls() {
  const host = document.getElementById("workload-controls");
  host.innerHTML = "";
  const current = getWorkload();

  const label = document.createElement("span");
  label.className = "workload-label";
  label.textContent = "Workload:";
  host.appendChild(label);

  for (const w of WORKLOAD_LEVELS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.workload = w.key;
    btn.className = "workload-btn" + (w.key === current.key ? " active" : "");
    btn.textContent = w.label;
    btn.title = `${w.label} work (~${w.watts} W): ${w.examples}`;
    btn.addEventListener("click", () => setWorkload(w.key));
    host.appendChild(btn);
  }

  const rel = getRelThreshold();
  const note = document.createElement("span");
  note.className = "workload-note";
  note.innerHTML =
    `${current.label} work (~${current.watts} W) &rarr; ` +
    `heat-stress limit <strong>${rel.toFixed(1)}&deg;C WBGT</strong>. ` +
    `<span class="workload-eg">e.g. ${current.examples}</span>`;
  host.appendChild(note);
}

let _headlineCities = null;
let _headlineLatest = null;

function renderHeadline() {
  const rel = getRelThreshold();
  const summary = computeOverlookedSummary(_headlineCities, _headlineLatest, rel);

  const statHost = document.getElementById("overlooked-stat");
  if (summary.citiesTotal === 0) {
    statHost.innerHTML = '<p style="color:#b3401f;">No current data available.</p>';
    return;
  }

  const workload = getWorkload();
  statHost.innerHTML = `
    <div class="stat-big"><span class="stat-num">${summary.citiesWithShoulder}</span> of ${summary.citiesTotal} cities</div>
    <div class="stat-say">have outdoor work-stress hours today that fall in the
      morning or evening &mdash; <em>outside</em> the afternoon window
      (11am&ndash;5pm) that guidance says to avoid &mdash; for
      <strong>${workload.label.toLowerCase()}</strong> work.</div>
    <div class="stat-sub">${summary.totalShoulderHours} such city-hours in all, with the sun up.
      ${summary.totalDarkHumid > 0 ? `(${summary.totalDarkHumid} more after dark, driven by humidity &mdash; reported separately below.)` : ""}</div>
  `;

  // Top cities by overlooked shoulder-hours.
  const listHost = document.getElementById("overlooked-list");
  const top = summary.perCity.filter((c) => c.shoulder > 0).slice(0, 8);
  if (top.length === 0) {
    listHost.innerHTML =
      `<p class="insights-sub">No city crosses the ${workload.label.toLowerCase()}-work limit ` +
      `outside the afternoon window today. Try a heavier workload, or check back as conditions change.</p>`;
    return;
  }
  listHost.innerHTML =
    `<h3>Most overlooked hours today</h3>` +
    top.map((c) => {
      const label = c.shoulderHours
        .map((h) => h.istLabel).join(", ");
      return `
        <div class="overlooked-row">
          <div class="overlooked-head">
            <span class="overlooked-name">${c.name}</span>
            <span class="overlooked-count">${c.shoulder} hr outside window</span>
          </div>
          <div class="overlooked-detail">${c.state} &middot; work-stress at ${label} IST
            &middot; ${c.insideWindow} more inside the 11&ndash;5 window</div>
        </div>`;
    }).join("");
}

async function initHeadline() {
  const { cities, latest } = await loadAllData();
  _headlineCities = cities;
  _headlineLatest = latest;

  renderWorkloadControls();
  renderHeadline();

  // Recompute whenever the workload changes (buttons live here, but the
  // workday clock can't change workload, so this only fires from our buttons).
  document.addEventListener("workloadchange", () => {
    renderWorkloadControls();
    renderHeadline();
  });
}

initHeadline().catch((err) => {
  console.error(err);
  const el = document.getElementById("overlooked-stat");
  if (el) el.innerHTML = '<p style="color:#b3401f;">Could not load: ' + err.message + "</p>";
});
