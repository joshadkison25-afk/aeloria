// Aeloria Interactive Map

const REGION_FACTION = {
  faerwood:    "Shadow Court",
  lostfeld:    "Lostfeld Dwarves",
  dragonscar:  "Ice Dragons",
  glenhaven:   "Glenhaven Elves",
  twincities:  "Twin Cities",
  tidefall:    "Tidefall",
  dreadwind:   "Dreadwind Islands",
  durkhadur:   "Dur Khadur",
  farrock:     "Farrock",
  gilgeth:     "Gilgeth & Groth Orcs",
  rockplains:  "Vilefin Goblins",
  stonebreak:  "Monastery of Druids",
  watchtowers: null,
  frostvale:   null,
  sinking:     null,
};

const MORALE_FILL = {
  Rising:   { fill: "rgba(78,158,106,0.22)",  stroke: "#4e9e6a" },
  Stable:   { fill: "rgba(78,126,158,0.18)",  stroke: "#4e7e9e" },
  Declining:{ fill: "rgba(184,112,64,0.22)",  stroke: "#b87040" },
  Critical: { fill: "rgba(184,48,48,0.25)",   stroke: "#b83030" },
  default:  { fill: "rgba(30,30,55,0.5)",     stroke: "#2a2a45" },
};

const REGIONS = [
  { id:"watchtowers", label:"Northern Watchtowers",  cx:460, cy:82,  points:"180,65 790,65 790,105 620,112 380,112 180,100",        small:true },
  { id:"dragonscar",  label:"Dragonscar Peaks",      cx:500, cy:125, points:"355,65 630,65 640,140 575,172 445,172 360,140" },
  { id:"frostvale",   label:"Frostvale",             cx:262, cy:172, points:"198,108 322,108 332,190 272,215 198,198" },
  { id:"lostfeld",    label:"Lostfeld",              cx:205, cy:232, points:"135,162 268,152 295,202 282,272 202,292 148,260" },
  { id:"faerwood",    label:"Faerwood",              cx:138, cy:352, points:"82,245 188,228 228,262 245,325 228,408 162,445 90,422 72,342" },
  { id:"gilgeth",     label:"Gilgeth & Groth",       cx:732, cy:165, points:"632,78 828,78 858,182 795,235 665,228 625,158" },
  { id:"twincities",  label:"Twin Cities",           cx:432, cy:342, points:"348,272 518,272 538,382 468,418 348,402 318,358" },
  { id:"stonebreak",  label:"Stonebreak",            cx:285, cy:398, points:"238,332 348,332 348,452 275,472 228,435" },
  { id:"rockplains",  label:"Rock Plains",           cx:585, cy:358, points:"518,278 658,278 678,418 602,448 512,428 492,372" },
  { id:"durkhadur",   label:"Dur Khadur",            cx:748, cy:298, points:"662,198 838,198 872,362 818,402 678,392 652,312" },
  { id:"farrock",     label:"Farrock",               cx:888, cy:358, points:"838,268 948,268 958,418 868,448 832,388" },
  { id:"glenhaven",   label:"Glenhaven",             cx:532, cy:495, points:"442,418 642,418 668,548 592,592 438,572 392,492" },
  { id:"tidefall",    label:"Tidefall",              cx:168, cy:515, points:"102,432 242,432 258,568 208,622 128,612 95,532" },
  { id:"dreadwind",   label:"Dreadwind Islands",     cx:68,  cy:402, points:"32,328 108,322 118,462 58,482 28,418",               island:true },
  { id:"sinking",     label:"The Sinking Island",   cx:188, cy:648, points:"138,618 258,612 252,680 148,682 122,648",             island:true, sinking:true },
];

const REGION_CENTROIDS = {};
REGIONS.forEach(r => { REGION_CENTROIDS[r.id] = { x: r.cx, y: r.cy }; });

function buildMap(state) {
  const container = document.getElementById("map-svg-container");
  if (!container) return;

  const moraleMap = {};
  (state.faction_morale || []).forEach(f => { moraleMap[f.faction] = f; });

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 1000 700");
  svg.setAttribute("width", "100%");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.style.cssText = "max-height:520px;display:block;";

  // Defs — gradients + filters
  const defs = document.createElementNS(svgNS, "defs");
  defs.innerHTML = `
    <radialGradient id="sea-grad" cx="50%" cy="50%">
      <stop offset="0%" stop-color="#060c18"/>
      <stop offset="100%" stop-color="#030608"/>
    </radialGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="3" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="glow-strong">
      <feGaussianBlur stdDeviation="5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <pattern id="wave" x="0" y="0" width="40" height="20" patternUnits="userSpaceOnUse">
      <path d="M0,10 Q10,0 20,10 Q30,20 40,10" stroke="rgba(100,140,180,0.06)" stroke-width="1" fill="none"/>
    </pattern>
  `;
  svg.appendChild(defs);

  // Sea background
  const seaBg = document.createElementNS(svgNS, "rect");
  seaBg.setAttribute("width", "1000"); seaBg.setAttribute("height", "700");
  seaBg.setAttribute("fill", "url(#sea-grad)");
  svg.appendChild(seaBg);

  const waveOverlay = document.createElementNS(svgNS, "rect");
  waveOverlay.setAttribute("width", "1000"); waveOverlay.setAttribute("height", "700");
  waveOverlay.setAttribute("fill", "url(#wave)");
  svg.appendChild(waveOverlay);

  // Continent base
  const continent = document.createElementNS(svgNS, "polygon");
  continent.setAttribute("points", "165,58 938,58 958,202 968,408 888,602 708,682 358,682 158,602 92,442 82,282 165,58");
  continent.setAttribute("fill", "#0d0d1a");
  continent.setAttribute("stroke", "#1e1e35");
  continent.setAttribute("stroke-width", "2");
  svg.appendChild(continent);

  // Tension lines
  const tensionG = document.createElementNS(svgNS, "g");
  (state.active_tensions || []).forEach(t => {
    const parts = t.factions.split(/\s+vs\s+/i);
    if (parts.length < 2) return;
    const findRegion = name => {
      const n = name.toLowerCase().replace(/[^a-z]/g,"");
      return Object.entries(REGION_FACTION).find(([id, faction]) => faction && faction.toLowerCase().replace(/[^a-z]/g,"").includes(n));
    };
    const aEntry = findRegion(parts[0]);
    const bEntry = findRegion(parts[1]);
    if (!aEntry || !bEntry) return;
    const a = REGION_CENTROIDS[aEntry[0]];
    const b = REGION_CENTROIDS[bEntry[0]];
    if (!a || !b) return;
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y);
    line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("stroke", "#b83030"); line.setAttribute("stroke-width", "1.5");
    line.setAttribute("stroke-dasharray", "6,4"); line.setAttribute("opacity", "0.5");
    line.innerHTML = `<animate attributeName="stroke-dashoffset" from="0" to="-20" dur="1.5s" repeatCount="indefinite"/>`;
    tensionG.appendChild(line);
  });
  svg.appendChild(tensionG);

  // Region polygons
  const tooltip = document.getElementById("map-tooltip");
  REGIONS.forEach(region => {
    const factionName = REGION_FACTION[region.id];
    const morale = factionName ? moraleMap[factionName] : null;
    const style = morale ? (MORALE_FILL[morale.status] || MORALE_FILL.default) : MORALE_FILL.default;

    const poly = document.createElementNS(svgNS, "polygon");
    poly.setAttribute("points", region.points);
    poly.setAttribute("fill", style.fill);
    poly.setAttribute("stroke", style.stroke);
    poly.setAttribute("stroke-width", region.small ? "0.5" : "1");
    poly.setAttribute("opacity", region.sinking ? "0.6" : "1");
    poly.style.cursor = "pointer";
    poly.style.transition = "fill 0.3s, filter 0.3s";

    if (region.sinking) {
      poly.setAttribute("transform", "translate(0, 12)");
    }

    poly.addEventListener("mouseenter", () => {
      poly.setAttribute("filter", "url(#glow)");
      poly.setAttribute("fill", style.stroke.replace(")", ",0.35)").replace("rgb", "rgba"));
      if (tooltip) {
        tooltip.style.display = "block";
        const eventText = (state.recent_events || []).find(e => {
          const r = e.region.toLowerCase();
          return r.includes(region.label.toLowerCase().split(" ")[0].toLowerCase()) ||
                 (factionName && r.includes(factionName.toLowerCase().split(" ")[0].toLowerCase()));
        });
        const tensions = (state.active_tensions || []).filter(t => factionName && t.factions.includes(factionName.split(" ")[0]));
        tooltip.innerHTML = `
          <div style="font-family:Cinzel,serif;color:var(--gold);margin-bottom:6px;font-size:13px;">${region.label}</div>
          ${factionName ? `<div style="color:${style.stroke};font-size:9px;letter-spacing:2px;margin-bottom:8px;">${morale ? morale.status.toUpperCase() : 'NEUTRAL'}</div>` : ""}
          ${eventText ? `<div style="font-family:'Crimson Text',serif;font-size:14px;color:var(--text);margin-bottom:6px;">${eventText.text}</div>` : ""}
          ${morale ? `<div style="font-size:11px;color:var(--text-dim);">${morale.reason}</div>` : ""}
          ${tensions.length ? `<div style="margin-top:8px;font-size:10px;color:var(--declining);">⚔ ${tensions[0].factions}</div>` : ""}
        `;
      }
    });
    poly.addEventListener("mouseleave", () => {
      poly.removeAttribute("filter");
      poly.setAttribute("fill", style.fill);
      if (tooltip) tooltip.style.display = "none";
    });

    svg.appendChild(poly);

    // Region label
    if (!region.small) {
      const words = region.label.split(" ");
      const text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", region.cx);
      text.setAttribute("y", region.sinking ? region.cy + 12 : region.cy);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-family", "Cinzel, serif");
      text.setAttribute("font-size", region.island ? "8" : "9");
      text.setAttribute("fill", style.stroke);
      text.setAttribute("opacity", "0.8");
      text.style.pointerEvents = "none";

      if (words.length <= 2) {
        text.textContent = region.label;
      } else {
        words.forEach((w, i) => {
          const tspan = document.createElementNS(svgNS, "tspan");
          tspan.setAttribute("x", region.cx);
          tspan.setAttribute("dy", i === 0 ? "0" : "1.1em");
          tspan.textContent = w;
          text.appendChild(tspan);
        });
      }
      svg.appendChild(text);
    } else {
      const text = document.createElementNS(svgNS, "text");
      text.setAttribute("x", region.cx); text.setAttribute("y", region.cy + 4);
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("font-family", "Cinzel, serif"); text.setAttribute("font-size", "8");
      text.setAttribute("fill", "#3a3a5a"); text.setAttribute("letter-spacing", "4");
      text.style.pointerEvents = "none";
      text.textContent = "— NORTHERN WATCHTOWERS —";
      svg.appendChild(text);
    }
  });

  // Compass rose
  const compassG = document.createElementNS(svgNS, "g");
  compassG.setAttribute("transform", "translate(940, 620)");
  compassG.innerHTML = `
    <circle r="22" fill="none" stroke="#2a2a45" stroke-width="1"/>
    <line x1="0" y1="-18" x2="0" y2="18" stroke="#3a3a5a" stroke-width="1"/>
    <line x1="-18" y1="0" x2="18" y2="0" stroke="#3a3a5a" stroke-width="1"/>
    <text x="0" y="-22" text-anchor="middle" font-family="Cinzel,serif" font-size="8" fill="#7a6232">N</text>
  `;
  svg.appendChild(compassG);

  container.innerHTML = "";
  container.appendChild(svg);
}

function updateMap(state) {
  buildMap(state);
}
