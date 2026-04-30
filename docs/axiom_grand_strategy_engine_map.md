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

Status: started.

Goals:

- pausable realtime clock
- speed controls
- step control
- no overlapping ticks
- SSE clock events
- persisted local clock state

Next hardening:

- add backend unit tests for pause/resume/speed/due behavior
- skip or defer heavy narration/images at high speed
- expose tick ETA and processing state in all status surfaces

### Phase 2: Causality Ledger

Create `engine/causality.py`.

Minimum interface:

```python
def record_cause(world_state, *, domain, actor, pressure, decision, outcome, affected=None, hidden=None, severity=1):
    ...

def get_tick_causes(world_state, tick=None):
    ...
```

Storage target in world state:

```json
"causality_ledger": [
  {
    "id": "cause_000001",
    "tick": 21,
    "domain": "economy",
    "actor": "Groth Clans",
    "pressure": "food shortage",
    "decision": "raise raids",
    "outcome": "border violence increases",
    "severity": 3
  }
]
```

First integrations:

- faction decisions
- economic pressure decisions
- military decisions
- rebellions
- intrigue outcomes

### Phase 3: Event Surfacer

Create `engine/event_surfacer.py`.

Purpose:

- read causality ledger and subsystem outputs
- rank severity
- populate `primary_event`, `supporting_events`, `recent_events`, `faction_actions`
- stop relying on LLM world-state event creation

This is the bridge toward AI-flavor-only.

### Phase 4: Knowledge Model

Create faction knowledge state:

```json
"faction_knowledge": {
  "Glenwood": {
    "known_facts": [],
    "suspicions": [],
    "rumors": [],
    "false_beliefs": []
  }
}
```

Integrate with:

- intrigue
- diplomacy
- war declarations
- propaganda
- council reports

### Phase 5: Pressure Model

Create shared pressure scoring:

```text
economic pressure
military pressure
legitimacy pressure
succession pressure
religious pressure
relationship pressure
external threat pressure
```

Actors choose actions from pressure, traits, knowledge, and goals.

### Phase 5.5: Belief Model

Create faction belief state:

```json
"faction_beliefs": [
  {
    "faction": "Glenwood",
    "dominant_pressure": "diplomatic",
    "overall_pressure": 42,
    "beliefs": [
      {
        "id": "belief_glenwood_001",
        "subject": "Shadow Court",
        "claim": "Shadow Court may be funding border unrest",
        "confidence": 0.58,
        "source": "suspicion",
        "bias": "uncertain"
      }
    ]
  }
]
```

Belief is the bridge between objective world state and actor decisions.
Decision scoring consumes belief-derived bias conservatively; beliefs nudge
action weights but do not override hard viability rules.

### Phase 6: Council/Intel UI

Add map and dashboard panels:

Engine-owned report:

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

`engine.council` owns `council_report`. It reads pressure, beliefs,
causality, knowledge, relationships, and surfaced events. It does not decide
truth or mutate mechanics.

- why this happened
- upcoming risks
- faction intent
- supply crisis
- rebellion likelihood
- diplomatic flashpoints

This is where Axiom becomes readable and not just complex.

### Phase 7: Data-Driven Game SDK

Move Aeloria-specific setup into `games/aeloria`.

Add:

- scenario loader
- rule packs
- content schema validation
- mod loading
- new-game creation

### Phase 8: AI Flavor-Only

Remove LLM authority over world truth.

AI receives:

- canonical world state
- causality ledger
- surfaced events
- faction knowledge perspectives

AI outputs:

- chronicle prose
- seer text
- character voice lines
- council report language
- rumor phrasing

## Immediate Next Build Slice

The next concrete implementation should be Phase 2: the causality ledger.

Smallest safe version:

1. Add `engine/causality.py`.
2. Add helpers for appending/querying cause records.
3. Integrate one or two low-risk systems first:
   - `_run_decision_engine`
   - `_advance_war_attrition`
4. Add tests for ledger shape and bounded history size.
5. Show recent cause records in a debug/API endpoint.

This gives Axiom its defining foundation: the engine can explain itself.
