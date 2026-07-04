# Existing Tools Research: India Humid Heat Misranking Monitor

Date: 4 July 2026

## Short Verdict

I did not find an obvious public tool that does exactly this proposed project for India:

> A live city-ranked humid-heat dashboard comparing ordinary air-temperature risk against wet-bulb / estimated WBGT risk, same-date historical normal, and outdoor-work implications.

But the topic is crowded around it. A generic "wet-bulb heat monitor" would be derivative. The project is only differentiated if it becomes a **misranking diagnostic**:

> Which Indian cities look less dangerous on ordinary temperature rankings, but become high-risk once humidity, historical normal, and outdoor-work heat stress are considered?

That is the useful gap.

## What Already Exists

### 1. ClimateCHIP / WorkHeat

Source:
- [ClimateCHIP](https://www.climatechip.org/)
- [WorkHeat](https://www.climatechip.org/heat-effects-assessment-tool)
- [ClimateCHIP heat-stress index notes](https://www.climatechip.org/heat-stress-index-calculation)

What it does:
- Global heat-stress tools.
- Includes "Your Area" views and a WorkHeat tool for workplace heat challenges.
- Uses climate/weather data and occupational heat-stress logic, including ISO 7243-style thinking.
- Can look at current and future heat conditions globally.

Why it matters:
- This proves the occupational heat-risk framing is legitimate.
- It also shows that "work + heat stress" is not a novel category.

Where our project can differ:
- ClimateCHIP is not an India city-ranking editorial product.
- It is not focused on how dry-bulb rankings differ from humid-heat rankings.
- It is not designed around Heat Action Plan communication.
- It is not built as a public-facing Indian city misranking dashboard.

Implication:
- Do not frame this project as "we discovered occupational heat risk."
- Frame it as "we make the humid-heat ranking mismatch visible for Indian cities."

### 2. Copernicus ERA5-HEAT

Source:
- [ERA5-HEAT thermal comfort dataset](https://cds.climate.copernicus.eu/datasets/derived-utci-historical?tab=overview)

What it does:
- Provides a serious global thermal-comfort dataset derived from ERA5.
- Includes thermal stress variables such as UTCI.
- Covers historical data from 1940 onward at hourly time resolution.
- Uses global gridded data at roughly 0.25 degree scale.

Why it matters:
- This is scientifically more mature than just calculating wet-bulb temperature from temperature and humidity.
- It gives a possible benchmark or future upgrade path.

Where our project can differ:
- Copernicus provides data, not an India-facing decision product.
- It does not give an accessible city-ranked story for Indian public/policy users.
- It does not directly answer: which cities are underrated by dry-bulb rankings?

Implication:
- Use Open-Meteo for a feasible MVP, but mention Copernicus ERA5-HEAT as a validation/future upgrade candidate.
- Avoid pretending that a simple wet-bulb formula is the most sophisticated possible method.

### 3. Earth Nullschool

Source:
- [earth.nullschool.net](https://earth.nullschool.net/)

What it does:
- Global live weather map.
- Includes overlays for temperature, relative humidity, wet-bulb temperature, and related comfort/stress indicators.

Why it matters:
- Live wet-bulb maps already exist.
- So "look, wet-bulb on a map" is not enough.

Where our project can differ:
- Earth Nullschool is a map explorer, not a city-ranking tool.
- It does not provide Indian city comparisons.
- It does not compare dry-bulb vs humid-heat rankings.
- It does not include same-date historical normal.
- It does not include outdoor-work interpretation.

Implication:
- Do not make the primary visual a generic map. The main visual should be a rank-shift or misranking chart.

### 4. NWS / CDC HeatRisk

Sources:
- [CDC HeatRisk](https://www.cdc.gov/heatrisk/)
- [Heat.gov](https://www.heat.gov/)
- [Time explainer on CDC/NWS HeatRisk](https://time.com/6970280/extreme-heat-risk-cdc-national-weather-service-tool/)

What it does:
- US-focused heat-risk forecast system.
- Combines forecast heat with public-health risk categories.
- Emphasizes location-specific unusual heat and health risk.
- Gives risk levels and protective guidance.

Why it matters:
- The "today vs what is normal for this place/date" logic is already accepted in serious heat-warning systems.
- This validates our idea of comparing today's humid heat against a 1991-2020 same-date normal.

Where our project can differ:
- HeatRisk is US-only.
- It is not an India city-ranking tool.
- It is not designed around India's dry-bulb vs humid-heat communication gap.

Implication:
- Our historical-normal comparison is a strong, defensible feature.
- We should describe it as borrowing from serious heat-risk communication logic, not as an arbitrary charting choice.

### 5. NWS WBGT and OSHA Occupational Heat Guidance

Sources:
- [NWS Wet Bulb Globe Temperature guidance](https://www.weather.gov/tsa/wbgt)
- [OSHA heat exposure guidance](https://www.osha.gov/heat-exposure/hazards)

What they say:
- WBGT is preferred for occupational heat because it incorporates more than air temperature and humidity.
- WBGT accounts for factors such as radiant heat, sunlight, wind, and workload.
- OSHA explicitly warns that simpler measures like heat index miss important occupational heat-risk factors.

Why it matters:
- This is the biggest methodological warning for our project.
- Wet-bulb temperature is not the same thing as WBGT.
- We cannot responsibly say "safe outdoor work hours" based only on wet-bulb temperature.

Where our project can differ:
- Use wet-bulb for the humid-heat physiology story.
- Use estimated WBGT, with caveats, for work-risk bands.
- Label the output carefully as "lower-risk outdoor work windows under estimated WBGT assumptions," not as guaranteed safe hours.

Implication:
- If we blur wet-bulb and WBGT, experts will notice.
- This must be fixed before the project is publishable.

## India-Specific Landscape

### 1. NDMA / IMD Heat-Wave Guidance

Source:
- [NDMA Heat Wave page](https://ndma.gov.in/Natural-Hazards/Heat-Wave)

What it does:
- Presents official heat-wave guidance and links to advisories.
- Official heat-wave criteria remain heavily tied to maximum temperature thresholds and departures from normal.
- Also includes advisories related to informal workers and heat preparedness.

Why it matters:
- This supports the project premise: public heat communication in India is still strongly anchored in air temperature.

Where our project can differ:
- Translate dry-bulb alert logic into a comparison against humid-heat risk.
- Show which cities move up the ranking when humidity is included.

Implication:
- We can say official communication remains dry-bulb-heavy, but we should avoid overstating that India has no heat-risk communication infrastructure.

### 2. IMD Experimental Heat Index / "Feels Like" Measures

Source:
- [Times of India report on IMD feels-like index](https://timesofindia.indiatimes.com/city/nagpur/feels-like-imd-index-to-capture-actual-heat-impact-in-nagpur-vidarbha/articleshow/130478280.cms)

What it suggests:
- IMD has been experimenting with heat-index / feels-like measures that incorporate humidity and wind.
- This indicates official recognition that air temperature alone is incomplete.

Why it matters:
- We should not claim that IMD ignores humidity entirely.
- The stronger claim is that there is no widely accessible, India-wide, city-ranking tool that helps users see where humid heat changes the risk order.

Where our project can differ:
- City ranking.
- Historical normal.
- Rank-shift visualization.
- Outdoor-work interpretation.
- Transparent methods page.

Implication:
- Our project should complement, not dismiss, official work.

### 3. Urban Heat Vulnerability Mapping in India

Sources:
- [Wired on SEEDS / Chintan / Microsoft Sunny Lives heat-risk mapping](https://www.wired.com/story/india-is-using-ai-and-satellites-to-map-urban-heat-vulnerability-down-to-the-building-level)
- [CAPA Heat Watch](https://www.capastrategies.com/heat-watch)
- [Heat.gov mapping campaigns](https://www.heat.gov/pages/mapping-campaigns)

What they do:
- High-resolution within-city heat and vulnerability mapping.
- Often use satellites, ground campaigns, building-level data, or urban heat island methods.
- Focus on vulnerable neighborhoods, buildings, informal settlements, or urban microclimates.

Why it matters:
- The India heat-risk space is active.
- AI and satellite-based heat vulnerability work already exists.

Where our project can differ:
- Those projects are mostly within-city vulnerability tools.
- Our project is a between-city humid-heat misranking tool.
- We are not trying to identify the hottest block in Delhi; we are asking whether Chennai, Kolkata, Mumbai, Bhubaneswar, or other humid cities are under-prioritized when attention goes to headline dry-bulb heat.

Implication:
- Keep the scope clear: city-level public/policy communication, not neighborhood-level vulnerability mapping.

## What This Means For The Portfolio Project

### Do Not Build

Do not build:
- A generic wet-bulb map.
- A weather dashboard with 50 city cards.
- A "safe hours" tool based only on wet-bulb temperature.
- A project claiming "no one tracks heat risk in India."

Those would be weak or inaccurate.

### Build This Instead

Build:

> **India Humid Heat Misranking Monitor**

Core question:

> Which Indian cities look less dangerous on ordinary temperature rankings, but become high-risk once humidity, historical normal, and outdoor-work heat stress are included?

Main visual:
- A rank-shift chart.
- Left side: cities ranked by dry-bulb temperature.
- Right side: same cities ranked by wet-bulb or estimated WBGT.
- Highlight cities that jump upward in risk rank.
- Add today's deviation from 1991-2020 normal.

Supporting views:
- Hourly outdoor work-risk bands using estimated WBGT, with explicit caveats.
- City profile pages or cards showing dry-bulb, wet-bulb, estimated WBGT, normal, and forecast peak.
- Later: outdoor-worker exposure weighting, but only after the Census data is verified.

## Defensible Project Claim

Use this claim:

> Most public heat communication in India remains anchored in air temperature or local heat-wave alerts. This dashboard shows how city rankings change when humid heat, local historical normal, and outdoor-work heat stress are considered.

Avoid this claim:

> No one is tracking heat risk in India.

That is too broad and probably false.

## Differentiation Summary

| Existing tool type | What it already does | Gap our dashboard fills |
|---|---|---|
| ClimateCHIP / WorkHeat | Global workplace heat-stress assessment | India-specific city ranking and policy narrative |
| Copernicus ERA5-HEAT | Serious thermal comfort dataset | Public-facing Indian city dashboard |
| Earth Nullschool | Live global wet-bulb map | Ranking, historical normal, and misranking insight |
| NWS / CDC HeatRisk | US heat-health risk forecast | India adaptation with humid-heat rank comparison |
| NDMA / IMD guidance | Official heat-wave alerts and advisories | Shows where dry-bulb communication may understate humid heat |
| Urban heat vulnerability maps | Within-city heat-risk mapping | Between-city humid-heat comparison |

## Final Assessment

This is a credible first portfolio project if the central product is not "a wet-bulb dashboard" but a **humid-heat misranking diagnostic**.

The portfolio value comes from showing that you can:
- Identify a policy-relevant measurement gap.
- Use public climate/weather data responsibly.
- Separate similar-but-not-identical metrics like wet-bulb and WBGT.
- Build a live, reproducible data pipeline.
- Design a sharp visual argument rather than a generic chart page.
- Explain limitations honestly.

That combination can stand up to scrutiny better than a polished but shallow weather dashboard.
