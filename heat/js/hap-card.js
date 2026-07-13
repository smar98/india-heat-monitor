/* The rule on paper: what the selected city's state HAP actually tells
 * outdoor workers, quoted verbatim from the audited plan -- or an honest
 * "not audited here" when we have no primary source for that state. Its own
 * full-width panel (below the lower row), so this reads as a first-class
 * finding rather than an addendum under the workday clock. Follows the
 * shared city selection (citychange). Display-only: the computed avoidance
 * window everywhere on this site stays the 11am-5pm union of the audited
 * plans; nothing here feeds a number. */

let _hap = null;

function renderHapCard() {
  const host = document.getElementById("hap-card");
  const panel = document.getElementById("hap-panel");
  if (!host || !_hap) return;
  const cityId = typeof getSelectedCityId === "function" ? getSelectedCityId() : null;
  const cityMeta = (typeof clockCities !== "undefined" && cityId != null)
    ? clockCities.find((c) => c.id === cityId) : null;
  if (!cityMeta) { host.innerHTML = ""; if (panel) panel.hidden = true; return; }

  const plan = _hap.plans[cityMeta.state];
  let body;
  if (plan) {
    const src = plan.source_page ? `${plan.source_page}` : "source";
    body = `
      <p class="hap-plan-name">${plan.plan}</p>
      <blockquote class="hap-quote">&ldquo;${plan.window_text}&rdquo;
        <span class="hap-src">&mdash; <a href="${plan.source_url}" target="_blank" rel="noopener">${src}</a></span>
      </blockquote>
      ${plan.level_note ? `<p class="hap-note">Note: ${plan.level_note}.</p>` : ""}
      <p class="hap-note">The clock above shades 11am&ndash;5pm &mdash; the widest
      audited version of this advice &mdash; so hours flagged as overlooked fall
      outside even the most generous window on paper.</p>`;
  } else {
    body = `
      <p class="hap-note">No primary-sourced work-hour window for
      <strong>${cityMeta.state}</strong> is audited here (that means unaudited
      by this dashboard, not that no plan exists). The national advisory says
      &ldquo;${_hap.national.window_text}&rdquo; and the clock above shades
      11am&ndash;5pm, the widest window in any plan audited here &mdash; so the
      overlooked count stays a conservative lower bound for this city too.</p>`;
  }

  host.innerHTML = `
    <p class="hap-takeaway">The avoidance advice this dashboard tests is
    written government policy &mdash; the audited plans are quoted below
    verbatim. But a plan on paper is not a mandate: a 2023 national review
    found the plans weak on legal authority and funding.</p>
    <div class="hap-cols">
      <div>
        <div class="hap-head">${cityMeta.state} &mdash; ${plan ? "audited plan" : "not audited here"}</div>
        ${body}
      </div>
      <div class="hap-col-cpr">
        <div class="hap-head">Do the plans have teeth? &mdash; national finding</div>
        <p class="hap-cpr">A 2023 Centre for Policy Research review of 37
        Indian HAPs found that <em>none</em> identified the legal source of
        their authority, and only 11 discussed funding at all (eight of
        those asking departments to fund themselves).
        <a href="${_hap.cpr.url}" target="_blank" rel="noopener">CPR 2023</a>,
        ${_hap.cpr.source_page} &mdash; findings about India's plans overall,
        ${plan ? "not a grade of this plan" : "not a grade of any one state"}.</p>
      </div>
    </div>`;
  if (panel) panel.hidden = false;
}

function initHapCard() {
  fetch("data/hap.json")
    .then((r) => { if (!r.ok) throw new Error(`hap.json ${r.status}`); return r.json(); })
    .then((hap) => { _hap = hap; renderHapCard(); })
    .catch(() => {
      const host = document.getElementById("hap-card");
      const panel = document.getElementById("hap-panel");
      if (host) host.innerHTML = "";
      if (panel) panel.hidden = true;
    });
  document.addEventListener("citychange", renderHapCard);
}

initHapCard();
