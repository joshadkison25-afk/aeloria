// World Timeline — D3 horizontal scrollable timeline

let timelineInitialized = false;
let allTicks = [];
let activeFilter = null;

const EVENT_COLORS = {
  war:         "#b83030",
  political:   "#c9a84c",
  supernatural:"#9b7fd4",
  economic:    "#4e9e9e",
  default:     "#7a7a8a",
};

function classifyEvent(text) {
  const t = text.toLowerCase();
  if (t.includes("attack") || t.includes("war") || t.includes("army") || t.includes("battle") || t.includes("smite") || t.includes("siege")) return "war";
  if (t.includes("king") || t.includes("queen") || t.includes("court") || t.includes("elect") || t.includes("throne") || t.includes("council")) return "political";
  if (t.includes("omen") || t.includes("prophecy") || t.includes("magic") || t.includes("ritual") || t.includes("curse") || t.includes("divine") || t.includes("dragon")) return "supernatural";
  if (t.includes("trade") || t.includes("gold") || t.includes("mine") || t.includes("market") || t.includes("caravan")) return "economic";
  return "default";
}

async function initTimeline() {
  const container = document.getElementById("timeline-container");
  if (!container) return;
  container.innerHTML = `<div style="color:var(--text-dim);font-style:italic;padding:20px;">Loading chronicle...</div>`;

  try {
    const r = await fetch("/api/history");
    allTicks = (await r.json()).reverse();
  } catch(e) {
    container.innerHTML = `<div style="color:var(--critical);padding:20px;">Failed to load timeline.</div>`;
    return;
  }

  if (!allTicks.length) {
    container.innerHTML = `<div style="color:var(--text-dim);font-style:italic;padding:20px;">No history yet.</div>`;
    return;
  }

  timelineInitialized = true;
  renderTimeline();
}

function renderTimeline() {
  const container = document.getElementById("timeline-container");
  if (!container || !allTicks.length) return;
  container.innerHTML = "";

  const W = Math.max(allTicks.length * 120, container.offsetWidth || 800);
  const H = 280;
  const PX = 80, PY = 140;

  const svg = d3.select("#timeline-container").append("svg")
    .attr("width", W).attr("height", H)
    .style("overflow", "visible");

  // Background line
  svg.append("line")
    .attr("x1", PX).attr("y1", PY).attr("x2", W - PX).attr("y2", PY)
    .attr("stroke", "#2a2a45").attr("stroke-width", 2);

  const xScale = d3.scaleLinear()
    .domain([0, allTicks.length - 1])
    .range([PX, W - PX]);

  allTicks.forEach((tick, i) => {
    const x = xScale(i);
    const events = [];
    if (tick.major_event) events.push({ text: tick.major_event, type: classifyEvent(tick.major_event) });
    const mainEvent = events[0];
    const color = mainEvent ? EVENT_COLORS[mainEvent.type] : EVENT_COLORS.default;
    const r = mainEvent ? 10 : 6;
    const isFiltered = activeFilter && mainEvent && mainEvent.type !== activeFilter;

    // Vertical connector
    svg.append("line")
      .attr("x1", x).attr("y1", PY - r).attr("x2", x).attr("y2", PY - 30)
      .attr("stroke", isFiltered ? "#1a1a2a" : color).attr("stroke-width", 1).attr("opacity", 0.4);

    // Node
    const g = svg.append("g").attr("transform", `translate(${x}, ${PY})`).style("cursor", "pointer");

    g.append("circle").attr("r", r)
      .attr("fill", isFiltered ? "#0c0c18" : color)
      .attr("stroke", isFiltered ? "#2a2a35" : color)
      .attr("stroke-width", mainEvent ? 2 : 1)
      .attr("opacity", isFiltered ? 0.3 : 1);

    // Tick number
    g.append("text")
      .attr("y", 22).attr("text-anchor", "middle")
      .attr("font-family", "Cinzel, serif").attr("font-size", "9")
      .attr("fill", isFiltered ? "#2a2a45" : "#7a6232")
      .text(tick.tick);

    // Date label (alternating above/below)
    const dateY = i % 2 === 0 ? -28 : 38;
    g.append("text")
      .attr("y", dateY).attr("text-anchor", "middle")
      .attr("font-family", "Crimson Text, serif").attr("font-size", "9")
      .attr("fill", isFiltered ? "#2a2a45" : "#6a6a7e")
      .text((tick.world_date || "").split(",")[0]);

    // Hover tooltip
    const tip = document.createElement("div");
    tip.className = "timeline-tip";
    tip.style.display = "none";
    document.body.appendChild(tip);

    g.on("mouseenter", (event) => {
      tip.innerHTML = `<strong>${tick.world_date || "Unknown"}</strong><br>${mainEvent ? mainEvent.text : "Uneventful month"}`;
      tip.style.display = "block";
      tip.style.left = event.pageX + 12 + "px";
      tip.style.top = event.pageY - 40 + "px";
    });
    g.on("mousemove", (event) => {
      tip.style.left = event.pageX + 12 + "px";
      tip.style.top = event.pageY - 40 + "px";
    });
    g.on("mouseleave", () => { tip.style.display = "none"; });
    g.on("click", () => { openTimelineTick(tick.tick); tip.style.display = "none"; });
  });

  // Legend
  const legendG = svg.append("g").attr("transform", `translate(${PX}, 14)`);
  Object.entries(EVENT_COLORS).filter(([k]) => k !== "default").forEach(([type, color], i) => {
    const lx = i * 120;
    legendG.append("circle").attr("cx", lx).attr("cy", 0).attr("r", 5).attr("fill", color);
    legendG.append("text").attr("x", lx + 10).attr("y", 4)
      .attr("font-family", "Inter, sans-serif").attr("font-size", "9")
      .attr("fill", color).style("cursor", "pointer")
      .text(type.toUpperCase())
      .on("click", () => {
        activeFilter = activeFilter === type ? null : type;
        renderTimeline();
      });
  });

  // Reset filter text
  if (activeFilter) {
    legendG.append("text").attr("x", 480).attr("y", 4)
      .attr("font-family", "Cinzel, serif").attr("font-size", "9")
      .attr("fill", "#9b7fd4").style("cursor", "pointer")
      .text("CLEAR FILTER")
      .on("click", () => { activeFilter = null; renderTimeline(); });
  }
}

async function openTimelineTick(tickNum) {
  const detail = document.getElementById("timeline-detail");
  if (!detail) return;
  try {
    const r = await fetch(`/api/history/${tickNum}`);
    const state = await r.json();
    detail.style.display = "block";
    detail.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <span style="font-family:Cinzel,serif;color:var(--gold);font-size:16px;">${state.world_date}</span>
        <button class="back-btn" onclick="document.getElementById('timeline-detail').style.display='none'">✕</button>
      </div>
      ${(state.recent_events||[]).map(e => `<div class="event-item"><div class="event-region">${e.region}</div><div class="event-text">${e.text}</div></div>`).join("")}
      ${state.chronicle ? `<div style="font-family:'Crimson Text',serif;font-style:italic;color:var(--text-dim);margin-top:16px;font-size:16px;line-height:1.6;">${state.chronicle.substring(0,400)}...</div>` : ""}
    `;
  } catch(e) { console.error(e); }
}
