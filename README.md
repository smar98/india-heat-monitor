# The Overlooked Hours — India outdoor-work heat stress

A live dashboard showing where India's fixed "avoid the afternoon" work-hour
guidance overlooks outdoor heat stress. India's Heat Action Plans tell
outdoor workers to shift work to the morning and evening; on hot days those
shoulder hours themselves can exceed the occupational heat-stress limit. This
dashboard estimates that, live, for ~50 large Indian cities.

**Live site:** https://smar98.github.io/india-heat-monitor/heat/

## What it does

For each city, every forecast hour is scored against the NIOSH REL
occupational heat-stress reference limit (for a selectable workload) using
estimated **WBGT** (Wet Bulb Globe Temperature) — a metric that folds
humidity, solar radiation, and wind into one number, unlike the maximum air
temperature that IMD heat-wave declarations rest on. The headline counts the
**overlooked hours**: hours that exceed the limit *outside* the 11am–5pm
afternoon-avoidance window (the union of audited state HAP windows, used as a
conservative bound), with the sun up.

Three metrics are kept strictly separate and never compared against each
other's thresholds:

- **Wet-bulb temperature** — Stull (2011) approximation, from temperature and
  humidity.
- **Estimated WBGT** — a Python port of James Liljegren's (2008) reference
  model, verified numerically against the original author's compiled C code
  (see `tests/`).
- **NIOSH RAL/REL limits** — the occupational heat-stress reference lines,
  reported for acclimatized workers (REL) as the defensible default for
  India's chronically heat-exposed outdoor laborers.

Language discipline: the site says "exceeds the NIOSH heat-stress reference
limit," never "safe hours."

## How it's built

- Static site: plain HTML/CSS/JS, no build step. Hosted on GitHub Pages.
- Data: Open-Meteo Forecast API (no key). A GitHub Actions workflow targets a
  refresh every 6 hours; scheduled runs are best-effort, so the page shows a
  stale-data warning if the data is more than ~9 hours old.
- 1991–2020 climatological normals (ERA5) are computed once for the map's
  anomaly layer.

See `heat/methods.html` for full methodology, sources, validity ranges, and
caveats, and `BUILD_LOG.md` for the build history and decisions.

> Framing note: this is an exploratory, transparent, live policy dashboard
> highlighting a plausible blind spot in fixed work-hour guidance — not
> validated occupational-exposure evidence. Figures are forecast, on a ~25km
> grid, for a 50-city sample, and are not a national estimate.
