# India Humid Heat Monitor

A live dashboard tracking which Indian cities look less dangerous on ordinary
dry-bulb air-temperature rankings but become high-risk once humidity,
radiant heat, and time-of-day are accounted for.

Public heat communication in India is largely anchored to dry-bulb
temperature. This dashboard keeps three metrics strictly separate — dry-bulb
temperature, wet-bulb temperature (Stull 2011 approximation), and estimated
WBGT (Liljegren-type method) for outdoor work-risk bands — and updates on a
schedule from free public weather data (Open-Meteo).

See `existing_tools_research.md` for the prior-art review that shaped this
project's scope, and `heat/methods.html` (once built) for full methodology,
sources, and caveats.

Data pipeline runs via GitHub Actions every 6 hours. Site is static, hosted
on GitHub Pages, built with plain HTML/CSS/JS (no build step) plus Python
scripts for data fetching.
