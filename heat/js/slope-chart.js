/*
 * Rank-shift (slope) chart: cities ranked by dry-bulb temperature (left)
 * vs. estimated WBGT (right), today. The "climbers" -- cities whose
 * humid-heat rank is much higher-risk than their dry-bulb rank suggests --
 * are highlighted; the rest are drawn muted so the story isn't buried in
 * 50 crossing lines. Built with Observable Plot (CDN).
 */

const TOP_CLIMBERS_TO_LABEL = 10;

async function initSlopeChart() {
  const { cities, latest, normals } = await loadAllData();
  const records = computeRanks(buildCityMetrics(cities, latest, normals));

  const sortedByClimb = [...records].sort((a, b) => b.misrankDelta - a.misrankDelta);
  const climberIds = new Set(sortedByClimb.slice(0, TOP_CLIMBERS_TO_LABEL).map((r) => r.id));

  const points = [];
  for (const r of records) {
    const isClimber = climberIds.has(r.id);
    points.push({ x: "Dry-bulb rank", y: r.dryBulbRank, city: r.name, id: r.id, isClimber });
    points.push({ x: "Humid-heat (WBGT) rank", y: r.wbgtRank, city: r.name, id: r.id, isClimber });
  }

  const climberPoints = points.filter((p) => p.isClimber);
  const otherPoints = points.filter((p) => !p.isClimber);

  const labelPoints = records
    .filter((r) => climberIds.has(r.id))
    .map((r) => ({ x: "Humid-heat (WBGT) rank", y: r.wbgtRank, city: r.name }));

  const plot = Plot.plot({
    width: Math.max(700, document.getElementById("slope-chart").clientWidth || 700),
    height: 900,
    marginLeft: 60,
    marginRight: 140,
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
        stroke: "#b3401f", strokeWidth: 2,
      }),
      Plot.dot(points, { x: "x", y: "y", r: 2, fill: (d) => (d.isClimber ? "#b3401f" : "#c9c4b6") }),
      Plot.text(labelPoints, {
        x: "x", y: "y", text: "city",
        dx: 8, textAnchor: "start", fontSize: 11, fill: "#1c1c1a",
      }),
    ],
  });

  const container = document.getElementById("slope-chart");
  container.innerHTML = "";
  container.appendChild(plot);
}

initSlopeChart().catch((err) => {
  console.error(err);
  document.getElementById("slope-chart").innerHTML =
    '<p style="color:#b3401f;">Could not load chart data: ' + err.message + "</p>";
});
