// Faction Relationship Web — D3 force-directed graph

let factionWebInitialized = false;
let fwebSim = null;

const MORALE_COLORS = { Rising: "#4e9e6a", Stable: "#4e7e9e", Declining: "#b87040", Critical: "#b83030" };
const REL_COLORS = { alliance: "#c9a84c", rivalry: "#b83030", war: "#8b1a1a", neutral: "#3a3a5a" };

function initFactionWeb(state) {
  const container = document.getElementById("faction-web-container");
  if (!container) return;
  container.innerHTML = "";

  const W = container.offsetWidth || 700;
  const H = 480;

  if (fwebSim) fwebSim.stop();

  const morale = state.faction_morale || [];
  const relationships = state.relationships || [];

  if (!morale.length) {
    container.innerHTML = `<div style="color:var(--text-dim);font-style:italic;padding:40px;text-align:center;">No faction data yet.</div>`;
    return;
  }

  const nodes = morale.map(f => ({
    id: f.faction,
    status: f.status,
    reason: f.reason,
    power: (state.faction_power || []).find(p => p.faction === f.faction) || null,
  }));

  const links = relationships.map(r => ({
    source: r.faction_a,
    target: r.faction_b,
    type: r.type,
    intensity: r.intensity,
  })).filter(l => nodes.find(n => n.id === l.source) && nodes.find(n => n.id === l.target));

  const svg = d3.select("#faction-web-container").append("svg")
    .attr("width", W).attr("height", H);

  svg.append("defs").append("marker")
    .attr("id", "arrow").attr("viewBox", "0 -4 8 8").attr("refX", 18).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6).attr("orient", "auto")
    .append("path").attr("d", "M0,-4L8,0L0,4").attr("fill", "#3a3a5a");

  const link = svg.append("g").selectAll("line").data(links).enter().append("line")
    .attr("stroke", d => REL_COLORS[d.type] || REL_COLORS.neutral)
    .attr("stroke-width", d => Math.max(1, d.intensity / 3))
    .attr("stroke-opacity", 0.6)
    .attr("stroke-dasharray", d => d.type === "rivalry" ? "4,3" : null)
    .attr("marker-end", d => d.type !== "alliance" ? "url(#arrow)" : null);

  const node = svg.append("g").selectAll("g").data(nodes).enter().append("g")
    .style("cursor", "pointer")
    .call(d3.drag()
      .on("start", (event, d) => { if (!event.active) fwebSim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
      .on("end", (event, d) => { if (!event.active) fwebSim.alphaTarget(0); d.fx = null; d.fy = null; })
    );

  node.append("circle")
    .attr("r", 22)
    .attr("fill", d => MORALE_COLORS[d.status] || "#2a2a45")
    .attr("fill-opacity", 0.18)
    .attr("stroke", d => MORALE_COLORS[d.status] || "#2a2a45")
    .attr("stroke-width", 1.5);

  node.append("text")
    .attr("text-anchor", "middle").attr("dy", "0.35em")
    .attr("font-family", "Cinzel, serif").attr("font-size", "7")
    .attr("fill", d => MORALE_COLORS[d.status] || "#7a7a8a")
    .text(d => d.id.split(" ").slice(0, 2).join("\n"))
    .each(function(d) {
      const words = d.id.split(" ").slice(0, 3);
      d3.select(this).text(null);
      words.forEach((w, i) => {
        d3.select(this).append("tspan")
          .attr("x", 0).attr("dy", i === 0 ? `${-(words.length - 1) * 0.55}em` : "1.1em")
          .text(w);
      });
    });

  // Tooltip panel
  const panel = d3.select("#faction-web-container").append("div")
    .style("display", "none")
    .style("position", "absolute")
    .style("background", "var(--surface2)")
    .style("border", "1px solid var(--border2)")
    .style("border-left", "3px solid var(--gold-dim)")
    .style("padding", "12px 16px")
    .style("border-radius", "4px")
    .style("max-width", "260px")
    .style("font-size", "13px")
    .style("pointer-events", "none")
    .style("z-index", "100");

  node.on("mouseenter", (event, d) => {
    let html = `<div style="font-family:Cinzel,serif;color:var(--gold);margin-bottom:6px;">${d.id}</div>`;
    html += `<div style="color:${MORALE_COLORS[d.status]};font-size:10px;letter-spacing:2px;margin-bottom:6px;">${d.status.toUpperCase()}</div>`;
    html += `<div style="color:var(--text-dim);font-family:'Crimson Text',serif;font-size:14px;margin-bottom:6px;">${d.reason}</div>`;
    if (d.power) {
      html += `<div style="font-size:10px;color:var(--text-dim);">Military ${d.power.military} · Political ${d.power.political} · Economic ${d.power.economic} · Influence ${d.power.influence}</div>`;
    }
    panel.html(html).style("display", "block");
  });
  node.on("mousemove", (event) => {
    const rect = container.getBoundingClientRect();
    panel.style("left", (event.clientX - rect.left + 12) + "px")
         .style("top", (event.clientY - rect.top - 20) + "px");
  });
  node.on("mouseleave", () => panel.style("display", "none"));

  fwebSim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(110))
    .force("charge", d3.forceManyBody().strength(-280))
    .force("center", d3.forceCenter(W / 2, H / 2))
    .force("collision", d3.forceCollide(30))
    .on("tick", () => {
      link
        .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
      node.attr("transform", d => `translate(${d.x},${d.y})`);
    });

  factionWebInitialized = true;
}
