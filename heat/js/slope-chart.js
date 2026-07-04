/*
 * Rank-shift (slope) chart: cities ranked by dry-bulb temperature (left)
 * vs. estimated WBGT (right), today. The "climbers" -- cities whose
 * humid-heat rank is much higher-risk than their dry-bulb rank suggests --
 * get highlighted lines; every city gets a right-side label showing how
 * many places it moves (▲ = more dangerous under humid-heat than dry-bulb
 * ranking suggests, ▼ = less). Built with Observable Plot (CDN).
 *
 * The direction is not fixed: WBGT also weighs sun and wind, so on some
 * days inland northern cities climb and coastal ones fall. That day-to-day
 * instability is the point of the dashboard being live.
 */

const TOP_CLIMBERS_TO_HIGHLIGHT = 10;

const CLIMB_COLOR = "#b3401f";   // moves up the danger ranking under WBGT
const FALL_COLOR = "#4a5a63";    // moves down
const FLAT_COLOR = "#8d897d";

function moveLabel(r) {
  if (r.misrankDelta > 0) return `${r.name} ▲${r.misrankDelta}`;
  if (r.misrankDelta < 0) return `${r.name} ▼${Math.abs(r.misrankDelta)}`;
  return `${r.name} ·0`;
}

function moveColor(r) {
  if (r.misrankDelta > 0) return CLIMB_COLOR;
  if (r.misrankDelta < 0) return FALL_COLOR;
  return FLAT_COLOR;
}

async function initSlopeChart() {
  const { cities, latest, normals } = await loadAllData();
  const records = computeRanks(buildCityMetrics(cities, latest, normals));

  const sortedByClimb = [...records].sort((a, b) => b.misrankDelta - a.misrankDelta);
  const climberIds = new Set(
    sortedByClimb.slice(0, TOP_CLIMBERS_TO_HIGHLIGHT).filter((r) => r.misrankDelta > 0).map((r) => r.id)
  );

  const points = [];
  for (const r of records) {
    const isClimber = climberIds.has(r.id);
    points.push({ x: "Dry-bulb rank", y: r.dryBulbRank, city: r.name, id: r.id, isClimber });
    points.push({ x: "Humid-heat (WBGT) rank", y: r.wbgtRank, city: r.name, id: r.id, isClimber });
  }

  const climberPoints = points.filter((p) => p.isClimber);
  const otherPoints = points.filter((p) => !p.isClimber);

  const labelPoints = records.map((r) => ({
    x: "Humid-heat (WBGT) rank",
    y: r.wbgtRank,
    label: moveLabel(r),
    color: moveColor(r),
    bold: climberIds.has(r.id),
  }));

  const container = document.getElementById("slope-chart");
  const plot = Plot.plot({
    width: Math.max(700, container.clientWidth || 700),
    height: 940,
    marginLeft: 60,
    marginRight: 170,
    y: {
      domain: [records.length, 1], // rank 1 (most extreme) at top
      label: "Rank (1 = highest)",
      ticks: 10,
    },
    x: { domain: ["Dry-bulb rank", "Humid-heat (WBGT) rank"], label: null },
    marks: [
      Plot.line(otherPoints, {
        x: "x", y: "y", z: "id",
        stroke: "#c9c4b6", strokeWidth: 1, opacity: 0.7,
      }),
      Plot.line(climberPoints, {
        x: "x", y: "y", z: "id",
        stroke: CLIMB_COLOR, strokeWidth: 2,
      }),
      Plot.dot(points, { x: "x", y: "y", r: 2, fill: (d) => (d.isClimber ? CLIMB_COLOR : "#c9c4b6") }),
      Plot.text(labelPoints, {
        x: "x", y: "y", text: "label",
        dx: 8, textAnchor: "start", fontSize: 10.5,
        fill: "color",
        fontWeight: (d) => (d.bold ? "bold" : "normal"),
      }),
    ],
  });

  container.innerHTML = "";
  container.appendChild(plot);
}

initSlopeChart().catch((err) => {
  console.error(err);
  document.getElementById("slope-chart").innerHTML =
    '<p style="color:#b3401f;">Could not load chart data: ' + err.message + "</p>";
});
