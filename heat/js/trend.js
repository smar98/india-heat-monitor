/*
 * The long view: overlooked hours per year, 1980-2024 (ERA5 reanalysis),
 * for the city selected in the workday clock's selector and the workload
 * selected in the rail. Hand-rolled inline SVG -- no chart library, same
 * as the rest of the site.
 *
 * Data: heat/data/trends.json, built once by scripts/compute_trends.py with
 * the SAME Liljegren/Stull/NIOSH code path as the live pipeline and the
 * same overlooked-hour definition as data.js. Lazy-loaded the first time
 * the panel scrolls into view, so the ~0.4MB history never delays the
 * live dashboard.
 *
 * Honesty notes rendered with the chart (not just here): reanalysis vs the
 * live forecast are different data products and are never mixed; the 11-5
 * avoidance window is TODAY'S audited HAP union applied to past years; the
 * band is the REL +/- 1C sensitivity, matching the headline's.
 */

let _trends = null;          // parsed trends.json
let _trendsLoading = null;   // in-flight fetch promise

function loadTrends() {
  if (!_trendsLoading) {
    _trendsLoading = fetch("data/trends.json")
      .then((r) => {
        if (!r.ok) throw new Error(`trends.json: HTTP ${r.status}`);
        return r.json();
      })
      .then((json) => { _trends = json; return json; });
  }
  return _trendsLoading;
}

function trailingMean(values, window) {
  return values.map((_, i) => {
    const from = Math.max(0, i - window + 1);
    const slice = values.slice(from, i + 1);
    return slice.reduce((s, v) => s + v, 0) / slice.length;
  });
}

function renderTrend() {
  const host = document.getElementById("trend-chart");
  const noteEl = document.getElementById("trend-note");
  const tagEl = document.getElementById("trend-panel-tag");
  if (!host || !_trends) return;

  const cityId = typeof getSelectedCityId === "function" ? getSelectedCityId() : null;
  if (cityId == null) return;
  const city = _trends.cities[String(cityId)];
  const workload = getWorkload();
  const cityMeta = clockCities.find((c) => c.id === cityId);
  const cityName = cityMeta ? cityMeta.name : `city ${cityId}`;

  if (!city || !city[workload.key]) {
    host.innerHTML = '<p class="empty" style="padding:12px 2px;">No history available for this city.</p>';
    return;
  }

  const years = _trends.years;
  const ovl = city[workload.key].ovl;
  const hi = city[workload.key].ovl_hi;   // stricter limit (REL+1): fewer hours
  const lo = city[workload.key].ovl_lo;   // looser limit (REL-1): more hours
  const days = city[workload.key].days;
  const mean10 = trailingMean(ovl, 10);

  // ---- geometry ----
  const W = 720, H = 260, padL = 46, padR = 14, padT = 14, padB = 30;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const yMax = Math.max(10, ...lo);   // band's upper series sets the scale
  const x = (i) => padL + (i / (years.length - 1)) * innerW;
  const y = (v) => padT + innerH - (v / yMax) * innerH;
  const pathOf = (vals) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

  // Sensitivity band polygon: lo (upper edge) forward, hi (lower edge) back.
  const band = lo.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")
    + " " + hi.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).reverse().join(" ");

  // y gridlines at ~4 round steps.
  const step = Math.max(50, Math.ceil(yMax / 4 / 50) * 50);
  let grid = "";
  for (let v = step; v <= yMax; v += step) {
    grid += `<line x1="${padL}" y1="${y(v)}" x2="${W - padR}" y2="${y(v)}" stroke="#232a32" stroke-width="1"/>`
      + `<text x="${padL - 6}" y="${y(v) + 3}" text-anchor="end" class="trend-tick">${v}</text>`;
  }
  // x ticks each decade.
  let xticks = "";
  years.forEach((yr, i) => {
    if (yr % 10 === 0) {
      xticks += `<line x1="${x(i)}" y1="${padT + innerH}" x2="${x(i)}" y2="${padT + innerH + 4}" stroke="#3a424d"/>`
        + `<text x="${x(i)}" y="${padT + innerH + 15}" text-anchor="middle" class="trend-tick">${yr}</text>`;
    }
  });

  // Hover targets: one invisible-ish dot per year with a title tooltip.
  const dots = years.map((yr, i) =>
    `<circle cx="${x(i)}" cy="${y(ovl[i])}" r="6" fill="transparent">` +
    `<title>${yr} — ${ovl[i]} overlooked hours (${hi[i]}–${lo[i]} across the ±1°C band), ` +
    `${days[i]} days with ≥1 such hour, ${workload.label.toLowerCase()} work</title></circle>`
  ).join("");

  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block" role="img"
         aria-label="Overlooked hours per year in ${cityName}, 1980 to 2024">
      <text x="${padL - 6}" y="${padT - 3}" text-anchor="end" class="trend-tick">hrs/yr</text>
      ${grid}${xticks}
      <polygon points="${band}" fill="rgba(224,113,58,.14)"/>
      <path d="${pathOf(ovl)}" fill="none" stroke="#ef8a4a" stroke-width="1.6"/>
      <path d="${pathOf(mean10)}" fill="none" stroke="#f2f4f7" stroke-width="1.2" stroke-dasharray="5 4" opacity=".75"/>
      ${dots}
    </svg>`;

  if (tagEl) tagEl.textContent = `${cityName} · ERA5 · 1980–2024`;

  // ---- The so-what, in human units. ----
  // "Hours over the limit" means little raw; translate it: how many DAYS a
  // year does this happen, and how much working time does it add up to
  // (8-hour-workday equivalents)? The decade comparison is CLIMATE-only --
  // same city, same workload, same 11-5 rule for all 45 years -- and the
  // copy must say so, or "vs the 1980s" invites an economic reading the
  // chart doesn't support.
  const decadeMean = (arr, from, to) => {
    const slice = arr.slice(from, to + 1);
    return slice.reduce((s, v) => s + v, 0) / slice.length;
  };
  const lastIdx = years.length - 1;
  const lateHours = decadeMean(ovl, lastIdx - 9, lastIdx);    // 2015-2024
  const earlyHours = decadeMean(ovl, 0, 9);                   // 1980-1989
  const lateDays = Math.round(decadeMean(days, lastIdx - 9, lastIdx));
  const workdays = Math.round(lateHours / 8);                 // 8-hour-workday equivalents

  const takeawayEl = document.getElementById("trend-takeaway");
  if (takeawayEl) {
    if (lateHours < 15) {
      takeawayEl.innerHTML =
        `For ${workload.label.toLowerCase()} work, this is rare in <strong>${cityName}</strong>: ` +
        `morning and evening hours crossed the limit only ` +
        `<strong>&asymp;${Math.round(lateHours)} hours a year</strong> over the last decade.`;
    } else {
      takeawayEl.innerHTML =
        `Over the last decade in <strong>${cityName}</strong>, morning and evening work hours ` +
        `crossed the heat-stress limit for ${workload.label.toLowerCase()} work on ` +
        `<strong class="hot">&asymp;${lateDays} days a year</strong> &mdash; ` +
        `<strong>&asymp;${Math.round(lateHours)} hours annually, the equivalent of ` +
        `${workdays} eight-hour workdays</strong> spent over the limit in the very hours ` +
        `the guidance recommends.`;
    }
  }

  if (noteEl) {
    const pct = earlyHours >= 50 ? Math.round(((lateHours - earlyHours) / earlyHours) * 100) : null;
    const deltaAbs = Math.round(lateHours - earlyHours);
    let deltaText;
    if (pct != null && Math.abs(pct) >= 5) {
      deltaText = `That's <strong>${pct > 0 ? "up" : "down"} ~${Math.abs(pct)}%</strong> compared with the 1980s`;
    } else if (pct != null) {
      deltaText = `That's <strong>roughly unchanged</strong> since the 1980s`;
    } else {
      deltaText = `That's <strong>${deltaAbs >= 0 ? `${deltaAbs} hours/year more` : `${-deltaAbs} hours/year fewer`}</strong> than in the 1980s`;
    }
    noteEl.innerHTML =
      `${deltaText} &mdash; and the comparison holds everything about the work constant: ` +
      `same workload, same 11am&ndash;5pm rule, all 45 years. Only the weather differs, ` +
      `so the change you see is climate, not economics or population.`;
  }
}

function initTrend() {
  const panel = document.getElementById("trend-panel");
  if (!panel) return;

  let started = false;
  function start() {
    if (started) return;
    started = true;
    loadTrends()
      .then(() => renderTrend())
      .catch((err) => {
        console.error(err);
        const host = document.getElementById("trend-chart");
        if (host) host.innerHTML =
          '<p class="empty" style="padding:12px 2px;">The 1980&ndash;2024 history is still being computed ' +
          "&mdash; this panel lights up automatically once it lands. (" + err.message + ")</p>";
      });
  }

  // Lazy-load when the panel first approaches the viewport, with a timed
  // fallback so the history always arrives even where IntersectionObserver
  // never fires (some embedded/headless contexts) -- the point of laziness
  // is only to keep the ~0.4MB file off the critical first paint.
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { io.disconnect(); start(); }
    }, { rootMargin: "300px" });
    io.observe(panel);
    setTimeout(start, 3000);
  } else {
    start();
  }

  document.addEventListener("citychange", () => { if (_trends) renderTrend(); });
  document.addEventListener("workloadchange", () => { if (_trends) renderTrend(); });
}

initTrend();
