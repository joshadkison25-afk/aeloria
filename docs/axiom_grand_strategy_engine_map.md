# Axiom Grand Strategy Engine Map

## North Star

Axiom is a deterministic grand-strategy simulation engine for living worlds.

Its advantage over traditional grand-strategy engines is not more modifiers, more buttons, or more scripted events. Its advantage is causality:

```text
pressure -> belief -> decision -> outcome -> record -> knowledge -> surfacing
```

The player should feel like they are watching history happen in real time, with enough tools to pause, inspect, intervene, and understand why the world is moving.

## Studio Thesis

Paradox-style games usually simulate large states through rules, modifiers, event scripts, and opaque AI choices.

Axiom should simulate:

- cause chains
- character motives
- faction incentives
- hidden knowledge
- political memory
- economic pressure
- military logistics
- cultural legitimacy
- narrative interpretation

The engine decides truth. AI adds flavor, voice, chronicles, rumors, and reports.

## Correct Engine Pipeline

The Axiom core loop is now structured around explicit ownership:

```text
pressure
  engine.pressure owns pressure_report

belief
  engine.beliefs owns faction_beliefs

decision
  engine events/decision code chooses actions from situational scores,
  traits, and belief-derived bias

outcome
  engine systems mutate world truth

record
  engine.causality owns causality_ledger

knowledge
  engine.knowledge owns faction_knowledge

surfacing
  engine.event_surfacer owns primary_event, supporting_events,
  recent_events, active_events, and faction_actions
```

The surfacer must not decide truth and must not update knowledge. It presents
already-recorded truth. Knowledge distribution belongs to `engine.knowledge`.

## Core Pillars

### 1. Causal Simulation

Every major event should have a structured reason trail.

Example:

```json
{
  "id": "cause_004218",
  "tick": 218,
  "domain": "rebellion",
  "actor": "House Verlorn",
  "pressure": "food_shortage",
  "belief": "Glenwood is too weak to retaliate",
  "decision": "fund_border_raid",
  "visible_outcome": "A raid strikes Glenwood caravans",
  "hidden_outcome": "The Shadow Court denies involvement",
  "affected": ["Glenwood", "Faerwood", "Twin Cities"],
  "confidence": 0.82
}
```

This gives the game explainable depth. The player can ask why something happened and get an answer the engine actually used.

### 2. Character-Causal Politics

Characters are not flavor. They are political engines.

Characters need:

- ambitions
- loyalties
- fears
- grudges
- promises
- debts
- legitimacy
- health
- family interests
- religious/cultural constraints
- knowledge state

Political action should emerge from character pressure plus faction pressure.

### 3. Real Material Economy

Economy should be a source of politics, not a background stat.

Systems to grow:

- food supply
- labor
- taxation
- debt
- military upkeep
- trade routes
- shortages
- inflation
- black markets
- infrastructure
- migration/refugees

Economic failure should create political consequences. War should damage the economy. Rebellions should affect trade. Trade should affect diplomacy.

### 4. Logistics-First War

War should be decided by more than army numbers.

Systems to grow:

- supply lines
- terrain
- morale
- command skill
- attrition
- weather
- disease
- siege pressure
- blockade pressure
- war exhaustion
- deserters
- occupation
- local collaboration/resistance

The player should see fronts, pressure, and collapse risk.

### 5. Information Asymmetry

No faction should know the whole truth by default.

Axiom should track:

- facts
- rumors
- suspicions
- lies
- spy reports
- propaganda
- public knowledge
- private faction knowledge

The same event can have different meanings to different factions.

### 6. Memory and Consequence

The world should remember.

Memory types:

- personal betrayal
- battle trauma
- diplomatic debt
- ancestral feud
- religious offense
- public humiliation
- military victory
- famine
- broken promise
- rescue/protection

Memory should decay, mutate, or harden into culture depending on severity.

### 7. Narrative Surfacing

Axiom should not dump logs on the player. It should surface what matters.

The event surfacer ranks mechanical results and promotes them into:

- primary event
- supporting events
- recent events
- faction actions
- council reports
- map alerts
- chronicle prompts

AI narration receives structured truth and writes flavor only.

### 8. Reusable Game SDK

Aeloria is the flagship game, but Axiom should become reusable.

Target split:

```text
axiom/
  clock/
  engine/
  causality/
  surfacing/
  world_state/
  ai/
  sdk/

games/
  aeloria/
    factions.json
    houses.json
    cultures.json
    religions.json
    resources.json
    map.json
    scenarios/
    rules/
```

The same engine should support fantasy dynasties, sci-fi empires, modern geopolitics, survival colonies, or crime families.

## The Paradox One-Up List

### Explainable World AI

Every major decision can answer:

- Why did this happen?
- Who caused it?
- Who benefited?
- Who was harmed?
- Who knows the truth?
- Who believes a false version?
- What will happen if nobody intervenes?

### Actor Knowledge Model

Factions should act on what they know, not what the player/dev knows.

### Deep Consequence Chains

War affects harvests, harvests affect legitimacy, legitimacy affects rebellion risk, rebellions affect diplomacy, diplomacy affects trade, trade affects war capacity.

### Living Council Interface

The UI should eventually include advisor/council views:

- Chancellor: diplomacy and legitimacy
- Marshal: war and logistics
- Steward: economy and supply
- Spymaster: intrigue and hidden knowledge
- Seer/Chronicler: prophecy, myth, and public meaning

Each council view is generated from engine truth.

### AI as Historian, Not God

AI should not decide outcomes. It should write:

- chronicles
- rumors
- speeches
- letters
- council reports
- faction propaganda
- character dialogue

This creates rich narrative without corrupting deterministic simulation.

## Target Runtime Loop

```text
clock heartbeat
  -> if paused: broadcast clock
  -> if due and not processing:
       load world
       run deterministic engine tick
       write causality records
       surface major events
       save world
       broadcast world update
       generate optional narration/assets async or throttled
```

## Major Engine Domains

```text
characters
  aging, death, health, traits, motives, memories, relationships

factions
  power, legitimacy, stability, goals, leadership, vassals, dominance

economy
  food, wealth, labor, production, trade, debt, shortages, taxation

military
  armies, fronts, supply, battles, sieges, attrition, occupation

diplomacy
  treaties, claims, alliances, tribute, threats, negotiations

intrigue
  plots, spies, secrets, assassinations, blackmail, misinformation

culture/religion
  laws, norms, legitimacy, conversion, heresy, identity conflict

population
  migration, refugees, unrest, class pressure, disease, settlement growth

causality
  decision records, pressure records, outcomes, memories, explanations

surfacing
  event ranking, alerts, reports, narrative prompts
```

## Implementation Roadmap

### Phase 1: Clock and Engine Control

Status: **complete**.

- pausable realtime clock with speed controls
- step control, no overlapping ticks
- SSE clock events
- persisted local clock state
- APScheduler tick loop, Flask SSE broadcast

### Phase 2: Causality Ledger

Status: **complete**.

`engine/causality.py` — `record_cause`, `get_tick_causes`.

Integrated into: faction decisions, economic pressure, military decisions, intrigue, player actions, all vertical slice actions.

Storage: `world_state["causality_ledger"]` — bounded list of structured cause records with id, tick, domain, actor, pressure, belief, decision, outcome, affected, severity, confidence, source.

### Phase 3: Event Surfacer

Status: **complete**.

`engine/event_surfacer.py` — reads causality ledger, ranks severity, populates `primary_event`, `supporting_events`, `recent_events`, `active_events`, `faction_actions`.

AI narration receives surfaced truth and writes flavor only.

### Phase 4: Knowledge Model

Status: **complete**.

`engine/knowledge.py` — `record_fact`, `record_rumor`, `record_suspicion`.

Per-faction knowledge state in `world_state["faction_knowledge"]`:

```json
{
  "Glenwood": {
    "known_facts": [],
    "suspicions": [],
    "rumors": [],
    "false_beliefs": []
  }
}
```

Knowledge distributes automatically on player actions and faction events.

### Phase 5: Pressure Model

Status: **complete**.

`engine/pressure.py` — `compute_pressure_report`, `compute_faction_pressure`, `pressure_summary`.

Domains: economic, military, legitimacy, succession, diplomacy, religious, external threat.

Pressure feeds directly into decision scoring via `evaluateActions`.

### Phase 5.5: Belief Model

Status: **complete**.

`engine/beliefs.py` — `build_faction_beliefs`, `update_beliefs`, `dominant_belief`, `belief_summary`, `decision_bias_from_beliefs`, `generate_belief_currents`.

Belief generators: legitimacy collapse, treaty distrust, military collapse.

Belief currents: high-pressure beliefs promote into spreading cultural movements tracked in `world_state["belief_currents"]` with follower counts, stage (rumor → doctrine → institution), and decay.

Belief bias nudges action weights in `evaluateActions` without overriding hard viability rules.

### Phase 5.75: World Seeding + Player Actions

Status: **complete**.

`engine/world_seed.py` — deterministic relationship seeding (78 pairs from geographic adjacency + active tensions) and faction identity seeding (13 factions with personality, goals, traits). Uses stable RNG seeded from MD5 hash of faction names. Auto-runs at start of tick pipeline.

`engine/player_actions.py` — player intervention layer. 6 actions: `send_aid`, `spread_rumor`, `fund_faction`, `reveal_secret`, `support_claimant`, `impose_embargo`. Each mutates world state, records causality, distributes knowledge. Queue: `world_state["pending_player_actions"]`. HTTP: POST `/api/player-action`, GET `/api/player-actions/pending`.

### Phase 5.8: Vertical Slices

Status: **complete**.

Four end-to-end causal chains verified firing and producing causality records across multi-tick runs:

- `back_claimant` — legitimacy collapse → noble rebellion (domain: legitimacy)
- `tactical_retreat` — military attrition → front collapse (domain: military)
- `denounce_treaty` — broken trust → diplomatic isolation (domain: diplomacy)
- `press_succession_claim` — succession weakness → dynastic instability (domain: legitimacy)

Each has scoring in `evaluateActions`, target selection in `chooseAction`, mechanical mutation in `applyDecision`, secondary effects in `executeEvent`, and a causality record.

### Phase 6: Council/Intel UI

Status: partial.

Engine outputs pressure, beliefs, causality, knowledge, and surfaced events. Frontend reads these. Formal `council_report` structure and advisor views not yet built.

Target:

```json
"council_report": {
  "tick": 22,
  "top_risks": [],
  "watchlist": [],
  "advisor_reports": {
    "chancellor": [],
    "marshal": [],
    "steward": [],
    "spymaster": [],
    "chronicler": []
  }
}
```

`engine.council` will own `council_report`. It reads pressure, beliefs, causality, knowledge, relationships, and surfaced events. It does not decide truth or mutate mechanics.

### Phase 7: Data-Driven Game SDK

Status: **not started**.

Move Aeloria-specific setup out of Python into `games/aeloria/`.

Add:

- scenario loader
- rule packs
- content schema validation
- mod loading
- new-game creation

Target directory split:

```text
axiom/        (engine, reusable)
games/
  aeloria/
    factions.json
    locations.json
    cultures.json
    religions.json
    resources.json
    starting_relationships.json
    scenarios/
```

### Phase 8: AI Flavor-Only

Status: partial.

AI narration is separated from mechanics in the tick pipeline. Some coupling remains. Target is full separation where AI receives only structured truth and outputs only prose.

AI receives: canonical world state, causality ledger, surfaced events, faction knowledge perspectives.

AI outputs: chronicle prose, seer text, character voice lines, council report language, rumor phrasing.

## Current Engine File Map

```text
engine/
  _core.py          — tick pipeline, decision engine, all faction systems
  pressure.py       — pressure scoring per faction per domain
  beliefs.py        — belief state, belief currents, decision bias
  causality.py      — causality ledger record/query
  knowledge.py      — faction knowledge distribution
  event_surfacer.py — event ranking and surfacing
  world_seed.py     — deterministic world initialization
  player_actions.py — player intervention queue and handlers
  autopsy.py        — tick autopsy and diff reporting
  memory.py         — faction memory persistence
```

## Next Build Target

Phase 7: Data-Driven Game SDK.

Load Aeloria factions, locations, relationships, and starting conditions from JSON config files instead of hardcoded Python. The engine should be able to start a new game from a `games/aeloria/` folder without touching engine code.

Minimum:

1. `games/aeloria/factions.json` — faction list with names, personalities, starting power
2. `games/aeloria/locations.json` — location list with adjacency, controllers, terrain
3. `games/aeloria/starting_relationships.json` — initial relationship graph (overrides seed)
4. `engine/loader.py` — reads game config and populates world state
5. `app.py` new-game endpoint uses loader, not hardcoded defaults
