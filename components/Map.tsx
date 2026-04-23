'use client';

const recentEvents = [
  { region: 'Lostfeld', text: 'Ironmaul sealed the outer gate. Varek status unknown.', tone: 'gold' },
  { region: 'Twin Cities', text: 'Caeris holds the signed proclamation.', tone: 'blue' },
  { region: 'Dur Khadur', text: 'Forward unit is four miles from the harbor approach.', tone: 'red' },
  { region: 'Tidefall', text: 'Council convened without the Admiral.', tone: 'blue' },
  { region: 'Dreadwind Islands', text: 'Rowen returned with a bronze tube and stone tablet.', tone: 'purple' },
];

const mapLayers = [
  { label: 'Succession Pressure', tone: 'blue' },
  { label: 'Military Presence', tone: 'red' },
  { label: 'Shadow Court Influence', tone: 'purple' },
  { label: 'Monastery Authority', tone: 'gold' },
  { label: 'Intelligence Trade', tone: 'green' },
];

const legendItems = [
  ['Capital / Major City', 'star'],
  ['Druid / Monastery Pressure', 'eye'],
  ['Diplomatic Route', 'dash'],
  ['Military Crisis', 'cross'],
  ['Sea Expedition', 'wave'],
  ['Intelligence Market', 'diamond'],
];

const factionColumns = [
  {
    title: 'Civil Realms',
    text: 'Twin Cities, Eresteron, Glenhaven, Tidefall, Farrock',
  },
  {
    title: 'Contested Powers',
    text: 'Lostfeld Dwarves, Monastery of Druids, Shadow Court, Gloomspire Gnomes, Vampires, Vilefin Goblins',
  },
  {
    title: 'Far Frontier',
    text: 'Dur Khadur, Gilgeth Orcs, Groth Stronghold, Dragonscar Peaks, Dreadwind Islands',
  },
];

function CompassRose() {
  return (
    <div className="static-atlas-compass" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
    </div>
  );
}

function IconMark({ type }: { type: string }) {
  return <span className={`atlas-legend-icon atlas-legend-icon--${type}`} aria-hidden="true" />;
}

export default function FantasyMap() {
  return (
    <div className="static-atlas-shell">
      <div className="static-atlas-vignette" />

      <aside className="atlas-left-panel static-atlas-panel-stack">
        <div className="atlas-title-card">
          <CompassRose />
          <div>
            <h1>Aeloria</h1>
            <p>Day 16</p>
            <span>Month of the Ashen Dreaming</span>
          </div>
        </div>

        <section className="atlas-panel">
          <p className="atlas-panel__label">Seer Location</p>
          <div className="atlas-seer-row">
            <span className="atlas-seer-mark atlas-seer-mark--eye" aria-hidden="true" />
            <div>
              <strong>Lostfeld Outer Gate</strong>
              <span>Monastery rider locked out</span>
              <small>Varek status unknown</small>
            </div>
          </div>
        </section>

        <section className="atlas-panel atlas-panel--grow">
          <p className="atlas-panel__label">Recent Events</p>
          <div className="atlas-event-list">
            {recentEvents.map((event) => (
              <div className="atlas-event static-atlas-event" key={event.region}>
                <span className={`atlas-event__badge atlas-event__badge--${event.tone}`} aria-hidden="true" />
                <span>
                  <strong>{event.region}</strong>
                  <small>{event.text}</small>
                </span>
              </div>
            ))}
          </div>
          <div className="atlas-view-all">View All</div>
        </section>
      </aside>

      <main className="static-atlas-map-area" aria-label="Static map interface of Aeloria">
        <div className="static-map-board">
          <img src="/aeloria-lore-map-labeled.png" alt="Lore-labeled fantasy strategy map of Aeloria" className="static-map-art static-map-art--labeled" />
          <div className="static-map-ink" />
        </div>

        <div className="atlas-timeline static-atlas-timeline">
          <span>Day 1</span>
          <div className="atlas-timeline__track">
            {Array.from({ length: 14 }).map((_, index) => (
              <span className={index === 6 ? 'is-active' : ''} key={index} />
            ))}
          </div>
          <span>Day 24</span>
        </div>

        <div className="static-atlas-controls" aria-hidden="true">
          <span className="static-control static-control--back" />
          <span className="static-control static-control--play" />
          <span className="static-control static-control--forward" />
          <span className="static-speed">1x</span>
          <span className="static-control static-control--gear" />
        </div>
      </main>

      <aside className="atlas-right-panel static-atlas-panel-stack">
        <section className="atlas-panel">
          <p className="atlas-panel__label">Faction Layout</p>
          <div className="static-faction-list">
            {factionColumns.map((column) => (
              <article className="static-faction-card" key={column.title}>
                <h2>{column.title}</h2>
                <p>{column.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="atlas-panel">
          <p className="atlas-panel__label">Map Layers</p>
          <div className="atlas-layer-list">
            {mapLayers.map((layer) => (
              <div className="atlas-layer static-atlas-layer" key={layer.label}>
                <span className={`atlas-layer__icon atlas-layer__icon--${layer.tone}`} />
                {layer.label}
              </div>
            ))}
          </div>
        </section>

        <section className="atlas-panel">
          <p className="atlas-panel__label">Legend</p>
          <div className="atlas-legend-list">
            {legendItems.map(([label, type]) => (
              <div className="atlas-legend-item" key={label}>
                <IconMark type={type} />
                <span>{label}</span>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
