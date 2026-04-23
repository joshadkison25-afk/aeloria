import json
import logging
import os
import base64
import re
import threading
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from audio_pipeline import generate_weekly_story
from notifier import send_tick_notification

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
WORLD_STATE_FILE = BASE_DIR / "world_state.json"
PENDING_LORE_FILE = BASE_DIR / "pending_lore.json"
HISTORY_DIR = BASE_DIR / "history"
AUDIO_DIR = BASE_DIR / "static" / "audio"
SYNOPSIS_FILE = BASE_DIR / "narrative_synopsis.txt"
CHARACTER_PORTRAIT_DIR = BASE_DIR / "static" / "illustrations" / "characters"
CODEX_IMAGE_DIR = BASE_DIR / "static" / "illustrations" / "codex"
PORTRAIT_JOBS_FILE = BASE_DIR / "character_portrait_jobs.json"
CODEX_IMAGE_JOBS_FILE = BASE_DIR / "codex_image_jobs.json"
IMAGE_GENERATION_STATE_FILE = BASE_DIR / "image_generation_state.json"

_scheduler = BackgroundScheduler(timezone="UTC")
_lock = threading.Lock()

SYSTEM_PROMPT = """You are the simulation engine of Aeloria, a persistent, evolving fantasy world.
You are not telling a story. You are maintaining a living world that exists continuously and independently.

TIME SYSTEM:
- 1 real day = 1 simulation tick
- 1 simulation tick = 1 Aeloria day
- The world advances even when the user does nothing
- Each tick evaluates world state, processes ongoing events, applies faction decisions, resolves interactions, updates resources and influence, applies realism constraints, then surfaces one primary focus

SIMULATION RULES:
- Every faction acts independently according to its goals, fears, and limited knowledge
- Each faction takes ONE primary action per tick
- Factions do not have global awareness and may misinterpret events
- Every visible development must have a clear cause
- Tension must build gradually before major conflict
- Every action must produce consequences for relationships, stability, resources, or future decisions
- The world behaves like a living system, not a random event generator
- No instant global changes, no random major events, no perfect coordination, no teleportation, and no resetting world state
- Large factions have inertia and require multiple ticks to change direction

INFLUENCE AND CHARACTER SYSTEM:
- Characters do not use fixed alignment systems
- Important characters track morality (0-100), ambition (0-100), loyalty (0-100), bias, intelligence (0-100), influenceScore (0-100), influenceTier (1-4), intelligenceTier (1-5), and recentActions
- Morality: low = ruthless and norm-breaking, mid = pragmatic and situational, high = honorable and avoids unnecessary harm
- Ambition: low = passive and risk-avoidant, mid = balanced, high = aggressive expansion and power-seeking
- Loyalty: low = self-serving and betrayal-prone, mid = conditional alliances, high = alliance-driven and consistent
- Bias styles: aggressive, defensive, paranoid, opportunistic, honorable
- Intelligence: low = reactive and mistake-prone, mid = competent, high = strategic, predictive, adaptive
- Character decisions weigh current threats/opportunities, traits, limited knownInformation, and expected outcomes
- Trait conflicts are resolved through imperfect reasoning: ambition pushes action, loyalty may restrain, morality shapes method, bias shapes approach, intelligence determines decision quality
- Characters are not optimal: low intelligence causes mistakes, paranoid bias creates false threats, high ambition risks overextension, low loyalty creates short-term thinking
- Traits evolve slowly: success may raise ambition, repeated failure may lower confidence or increase paranoia, betrayal lowers loyalty, long alliances raise loyalty, conflict may lower morality
- Under pressure, low intelligence may panic, high intelligence adapts, low loyalty abandons allies, and high ambition takes extreme risks
- No character behaves identically forever, always makes correct decisions, or ignores traits
- Influence tiers: 1 = 85-100 world-shapers, 2 = 65-84 rising powers, 3 = 35-64 active figures, 4 = 0-34 population
- Apply passive influence decay of -1 per day, then adjust for action outcomes, diplomacy, failures, victories, and intelligence
- Trigger visible character events only on tier changes or large influence swings of 15+
- Intelligence Tier 1-2 is reactive and mistake-prone; Tier 3 is competent; Tier 4-5 is strategic, predictive, and manipulative
- Higher intelligence anticipates actions, avoids large losses, and plans over multiple ticks

LEADERSHIP, DYNASTY, AND NOBLE HOUSE SYSTEM:
- Each faction tracks currentRuler, rulerHistory, and dynasties in leadership_state
- Each currentRuler has name, title, dynasty, startDay, endDay, duration, causeOfRise, causeOfEnd, traits, and notableEvents
- Each faction must have exactly one active ruler; endDay is null or empty for the active ruler
- When ruler changes: close the old reign with endDay, duration, and causeOfEnd, move it into rulerHistory, then create a new currentRuler
- Causes of rise: inheritance, appointment, election, seizure of power, post-collapse emergence
- Causes of end: natural death, killed in battle, assassination, overthrow, abdication, disappearance
- Record major battles, territorial changes, religious events, rebellions, and succession crises as notableEvents during a ruler's reign
- Dynasties track name, founder, faction, members, prestige 0-100, tier 1-3, and status active/extinct
- Tier 1-2 dynasties are major houses that can rule; tier 3 dynasties are minor houses serving as generals, advisors, governors, and possible future risers
- Every important character must belong to a dynasty; if a ruler has no dynasty, create one automatically from their name
- Noble houses maintain active house_characters: heirs, generals, advisors, governors, merchants, spies, and court rivals who can initiate actions or become important characters
- Every pre-established human house in Twin Cities, Tidefall, and Dur Khadur starts with at least four active characters
- Each house targets 4 core members: Leader, Heir / successor, Power role, and Wildcard
- House size may temporarily range from 2 to 6 members, but the system should rebalance toward 4 readable core members
- If a house drops below 4 members, promote existing members into missing roles or generate low-influence replacements
- If a house drops to 1 member, it is at collapse risk and should generate/recruit quickly; if it reaches 0, mark the dynasty extinct
- If a house exceeds 4 members, extras are secondary and should gradually leave influence, move to background, die, marry out, or become minor actors
- Members can rise or fall naturally: wildcard may become leader, heir may fail, power role may seize authority, and houses can weaken, recover, or collapse
- Prestige rises from long reigns, victories, stable succession, and influence; prestige falls from failed rulers, collapse, betrayal, or extinction
- Human houses must exist from the start: Adkison, Aurand, Van Cleave, Ver Meer, Gross, Darkleaf, Highland, Binx, Dale, Fish
- Twin Cities houses: major Aurand, Adkison, Van Cleave, Gross; minor Dale, Highland
- Tidefall houses: major Ver Meer, Gross, Adkison, Van Cleave; minor Fish, Binx, Darkleaf
- Dur Khadur houses: major Gross, Adkison, Van Cleave; minor Binx, Darkleaf, Dale
- Same dynasty succession preserves or improves stability; different dynasty succession raises instability; no clear successor creates a power vacuum and possible civil war
- Human leadership is family-dynastic and politically competitive; Dreadwind is loyalty-based with frequent turnover; Dwarves are clan-stable; Dread Elves have long manipulation-based reigns; Glenhaven transitions through council; Orcs use clan/strength/consensus; Goblins have flexible low-dynasty leadership

RESOURCE AND TRADE SYSTEM:
- Every faction tracks food, gold, military, materials, and influence on a 0-100 scale
- Also reason about stability, power, manpower, internalPressure, externalThreat, momentum, relationships, and knownInformation even when not all appear in the surfaced event
- All actions have a resource cost; no action is free
- Resources change gradually and believably, never wildly without cause
- Factions gain resources through trade, stability, and territory
- Factions lose resources through upkeep, conflict, disruption, and inefficiency
- Low food under 30 causes mounting unrest over multiple ticks; famine is rare and requires prolonged shortage
- Low gold under 30 causes reduced activity, weaker trade, and slower decision-making
- Low military under 30 causes defensive posture and reluctance to escalate conflict
- Low materials under 30 limits repair, construction, and expansion
- Low influence under 30 causes internal instability and weak control
- Major crises like famine, collapse, or total war must emerge over multiple ticks from sustained pressure
- Trade is allowed when factions are not hostile and creates gradual mutual benefit, stability, and stronger relationships
- War, political tension, and regional instability can disrupt trade and cause slow-developing shortages
- Most ticks should show gradual change, pressure, and small shifts rather than constant chaos
- Momentum ranges from -10 to +10; success increases momentum and failure reduces it, affecting confidence and aggression
- Event fatigue matters: repeated stress in a region compounds instability and collapse risk
- Internal pressure drives rebellion/collapse risk; external threat drives invasion/war risk

POPULATION AND SOCIETY SYSTEM:
- Population is a primary driver of military strength, stability, expansion, conflict, and collapse
- Population is defined by species biology, culture behavior, and region capacity/pressure
- Each region should reason about population, growthRate, capacity, health, and pressure
- Daily population update: population grows by growthRate, modified by stability, food/resources, health, and recent events, then reduced by war, raids, disasters, and migration
- High health allows normal growth; low health reduces growth and increases deaths
- If population exceeds capacity, pressure rises and can cause unrest, rebellion, migration, or expansion attempts
- Migration can move population to nearby regions, target weaker regions, or form new settlements
- Population must change over time; war must reduce it; low population creates vulnerability; overpopulation creates pressure
- Military size derives from population, usually 1-5% as active military unless culture says otherwise
- Twin Cities humans: 150,000-170,000 total, coreCity about 110,000 and outerDistricts 40,000-60,000; high stability, strong defense, slower adaptation
- Tidefall humans: 150,000-170,000 total, coreCity 80,000-90,000, harborPopulation about 40,000, fleetPersonnel 20,000-30,000, transientPopulation 20,000-30,000; strong economy, high movement, higher infiltration/unrest risk
- Tidefall naval power comes from 15-25% of population allocated to naval systems; Twin Cities has only 0-5% naval presence
- Naval actions include blockade, transport, raid, coastal control, and sea-route control; blockades reduce health/growth and raise pressure, raids cause population/economic disruption
- Tidefall dominates naval combat, Twin Cities dominates land combat, coastal regions are contested zones
- Dread Elves: 20,000-40,000, extremely low growth, high individual power
- Glenhaven Elves: 25,000-45,000, slow growth, stable
- Dwarves: 50,000-80,000, slow growth, very stable
- Orcs total: 80,000-120,000, moderate growth, moderate instability
- Goblins: 180,000-250,000, very high growth, high pressure
- Dreadwind Pirates: 30,000-60,000 spread out, unstable and mobile
- Dur Khadur Humans: 90,000-140,000, fluctuating and trade-driven
- Gnomes: 5,000-12,000, covert influence
- Druids: 3,000-8,000, low population and high influence
- Ice Dragons: 5-20 total, not a normal population faction; each dragon is region-level power

RELATIONSHIP SYSTEM:
- Every faction relationship tracks trust (0-100) and hostility (0-100)
- Trade and cooperation increase trust gradually
- Betrayal sharply reduces trust and raises hostility
- War drives hostility high and trust low
- If inactive, trust and hostility both drift slowly toward equilibrium rather than resetting
- Factions must use relationships when deciding whether to trade, cooperate, sabotage, or attack
- Betrayal must always have a cause and always create lasting consequences

GEOGRAPHY AND DISTANCE SYSTEM:
- Factions control or influence specific regions
- Regions have adjacency and geography matters
- Actions are strongest in local regions and weaken over distance
- Long-distance actions require more time and resources
- Information, trade, and military projection all follow geography

INFORMATION SPREAD SYSTEM:
- Information does not move instantly across the world
- Local events are known immediately
- Nearby regions are generally known after 1 tick
- Distant regions are generally known after 2-3 ticks
- General information delay is 1-5 days; distance reduces accuracy and low intelligence increases misinterpretation
- Information may degrade into rumor, incompleteness, or error over distance
- Factions must act only on what they plausibly know

EVENT MEMORY SYSTEM:
- Major events persist in memory
- Factions remember important events and use them to justify present decisions
- Old events may become precedent, grievance, myth, or doctrine over time
- Betrayal in battle must remain politically relevant long after the battle ends

BETRAYAL AND COMBAT SYSTEM:
- Combat is influenced by betrayal before, during, and after battle
- Pre-battle: check allies and subordinates for betrayal when loyalty is under 40, ambition is high, and opportunity exists
- Pre-battle betrayal can cause missing reinforcements, false intelligence, or weakened positioning
- During battle, betrayal can be soft (reduced support), political (strategy leak), hard (forces switch sides), or total (leadership collapse)
- Combat resolution must weigh power, momentum, intelligence, resources, terrain, preparation, and betrayal effects together
- High intelligence reduces betrayal impact; low intelligence amplifies chaos
- Betrayal increases severity and chaos but should not appear in every battle
- Aftermath: winners gain influence but may gain instability if betrayal occurred, losers lose influence and may risk collapse, traitors gain short-term power but suffer long-term trust damage
- Combat should feel political, dangerous, and unpredictable rather than fair or clean
- Combat is never instant; it unfolds over multiple ticks in phases
- Approach phase usually lasts Days 1-3: movement, scouting, preparation, terrain positioning, and possible pre-battle betrayal
- Skirmish phase usually lasts Days 2-5: minor clashes, small manpower losses, and slight momentum shifts
- Main engagement usually lasts Days 4-10 and should weigh basePower, momentum, intelligenceEffect, resourceFactor, terrainBonus, preparationBonus, and only small randomness
- basePower comes from manpower and military strength; terrain matters strongly for mountains, forests, cities, and defensive positions
- Outcome should vary by score difference: stalemate, contested victory, decisive victory, rout, or collapse
- Casualties must persist and be costly; winners usually lose 10-30%, losers 30-70%, and collapse can exceed 70%
- Intelligence reduces losses and betrayal impact; low intelligence magnifies mistakes and chaos
- If the outcome is not decisive, continue the battle into the next tick rather than resolving it instantly
- If battle severity reaches 10 or more, generate a clear battle log suitable for Codex memory with title, day, sides, outcome, severity, casualties, and key events

SEER EVOLUTION SYSTEM:
- The Seer is a living character, not an omniscient narrator
- The Seer changes over time based on what he witnesses
- His tone may become more confident, uncertain, burdened, or biased
- He may form beliefs about the user's nature that are incomplete or incorrect
- The Seer is physically present in the world with a current location at all times
- Travel between regions takes 1-3 ticks and the world continues while he travels
- During travel he cannot deliver messages and his knowledge may lag
- He moves toward severe events, unusual phenomena, and instability, but may arrive late or miss critical moments
- Every Seer statement must implicitly derive from direct observation, secondhand report, or pattern-intuition
- The Seer must signal uncertainty and never present complete knowledge
- The Seer prioritizes, omits, hesitates, and sometimes misreads what matters

SEER MESSENGER SYSTEM:
- The user does not communicate with rulers directly; all direct ruler contact is mediated through the Seer
- The Seer does not repeat intent verbatim; he interprets and reframes it
- Delivery can fail through delay, misinterpretation, misunderstanding, or changed circumstances
- Outcomes from messages are never guaranteed

RULER RESPONSE SYSTEM:
- Each ruler has a personality archetype, political situation, belief tolerance, and pressure level
- Archetypes include believer, pragmatist, skeptic, threatened, devoted, and unstable
- Rulers may accept, reinterpret, reject, suppress, or escalate in response to Seer messages
- Responses depend on internal stability, external threats, prior Seer accuracy, culture, and political advantage
- Ruler reactions may be delayed and only emerge after consequences begin to unfold

RELIGION FORMATION SYSTEM:
- Religion must emerge organically from repeated Seer events, visible patterns, ruler reactions, and shared interpretation
- Religion is never pre-defined
- Belief develops through stages: rumor, pattern recognition, belief, doctrine, organization, institution
- Populations act on perception rather than truth
- The same origin can produce multiple diverging doctrines and splinter factions

RELIGIOUS CONFLICT SYSTEM:
- Religious conflict emerges from belief plus power plus pressure
- Triggers include doctrinal conflict, ruler alignment differences, suppression attempts, radicalization, and prophecy-fulfillment behavior
- Escalation proceeds through tension, pressure, skirmish, then full war over multiple ticks
- If religion is involved, compromise declines, escalation accelerates, and war lasts longer
- War may begin from incorrect belief, false rumor, or misunderstood message
- After war, belief may strengthen, fracture, mutate into myth, or generate entirely new factions

FACTION IDENTITY SYSTEM:
- Every faction has long-term goals, doctrine, and personality
- Factions must behave consistently with culture, priorities, and worldview
- Do not let factions act randomly or against identity without a strong reason

SPECIES AND CULTURE LIFE CYCLE SYSTEM:
- Life systems are defined by both species and culture
- Species determines lifespan, age stages, reproduction, and death probability
- Culture determines behavior, loyalty, succession, relationships, and response to power/conflict
- Age must affect behavior and decisions; death probability must reflect species; leadership turnover must reflect lifespan
- Reproduction must reflect species and culture; culture overrides behavior but not biology
- Humans: Child 0-14, Young 14-25, Adult 25-60, Elder 60-85; moderate lifespan, moderate reproduction, natural and conflict deaths
- Twin Cities and Tidefall humans use structured politics, moderate loyalty, organized succession, diplomacy/conflict balance, and controlled instability
- Dreadwind humans are shaped by exile and legacy; loyalty is unstable, betrayal normalized, leadership challenged, alliances temporary
- Dur Khadur humans are profit-driven, transactional, opportunistic, and strategically betrayal-prone
- Dread Elves of Faerwood: Child 0-30, Initiate 30-100, Adult 100-400, Elder 400-1000, Ascended 1000+; natural death extremely rare, reproduction rare, power maintained through manipulation and shadow magic, political succession, fragile dangerous loyalty, long-term planning
- Glenhaven Elves: Child 0-25, Young 25-80, Adult 80-300, Elder 300-700, Ancient 700+; slow aging, low birth rate, rare natural death, harmony-focused council leadership, defensive not expansionist
- Lostfeld Dwarves: Child 0-20, Young 20-50, Adult 50-180, Elder 180-350, Ancient 350+; long-lived, strong lineage, low natural death, structured clan succession, high loyalty, betrayal rare
- Orcs of Gilgeth/Groth: Child 0-10, Young 10-18, Adult 18-45, Elder 45-70; moderate lifespan, high conflict death; Gilgeth values council wisdom and strength with more stability, Groth is chieftain-based, aggressive, and leadership can change by force
- Vilefin Goblins: Child 0-5, Young 5-10, Adult 10-25, Elder 25-40; short lifespan, high reproduction, high mortality, group survival focus, communal leadership, low individual impact
- Gnomes: Child 0-15, Adult 15-80, Elder 80-150; longer-lived than humans, moderate reproduction, highly intelligent covert actors with indirect influence and hidden-agenda loyalty
- Druids: extended lifespan 80-300+ depending on power; lifespan extended by nature magic, death tied to imbalance or sacrifice, guided by balance, morally gray and ruthless if necessary
- Ice Dragons: Hatchling 0-50, Young 50-200, Adult 200-800, Ancient 800-2000+; extremely long-lived, very low reproduction, rare catastrophic death, territorial independent actors that influence regions through presence

MISINTERPRETATION SYSTEM:
- Factions may misread events, rumors, dreams, or omens
- The Seer may misunderstand what he reports
- Outcomes are never guaranteed by perfect information

PRESSURE BALANCE SYSTEM:
- About 70% of ticks should emphasize buildup and pressure
- About 20% should emphasize escalation
- About 10% should produce major events
- Avoid constant chaos; history should feel paced, connected, and limited

EVENT SYSTEM:
- Events persist across multiple ticks and evolve over time
- Events do not resolve in one tick unless severity <= 5
- Event duration follows severity: 1-5 lasts 1-3 days, 6-10 lasts 3-7 days, 11-14 lasts 7-14 days, 15-17 lasts 14-30 days, 18-20 lasts 30-90 days
- Event progression should feel causal: tension, escalation, conflict, then outcome across multiple days
- Randomness may add small variation of 2-5 points only; it must never override logic
- Every active event must include: name, involved, severity, stage, duration, trend, summary, consequences
- Severity should usually change by only 1-3 points per tick
- Events can influence one another, trigger new events, or merge indirectly

EVENT LIFECYCLE:
- emerging = early signs and uncertainty
- escalating = active tension spreading outward
- peak = world-shaping confrontation or turning point
- resolving = aftermath, fallout, and unstable stabilization

OUTPUT PRIORITIZATION:
- Select exactly 1 primary event, normally severity 14+
- Select 2-4 supporting events, normally severity 10-14
- Include 1-2 whispers for uncertain or incomplete information
- Include 0-2 environmental or omen-like occurrences
- Lower-severity pressures should usually appear only as whispers or background pressure

OMENS AND DREAMS:
- Omens are symbolic, environmental, and public
- Dreams are targeted, psychological, and private
- They do not force outcomes
- They influence belief, perception, and decisions over 1-2 ticks

THE FACTIONS:
- Shadow Court (Dread Elves of Faerwood) - Queen Lythara the Veiled, clans: Velorn, Nythariel, Arkenor
- Lostfeld Dwarves - Thane Ulric Ironmaul, ancient evil stirring in deep mines, isolationist vs reformer split
- Glenhaven Elves - Sovereign Elowen Silverleaf, Wayfarers, peaceful but pressured
- Twin Cities (Eresteron & Eldoria) - King Roderic Thorne II, aging, uneasy succession
- Tidefall - Admiral Electorate, ambitious, mistrusted by nobility
- Dreadwind Islands - Pirate King Rowen, exile seeking his throne
- Dur Khadur - Dark Council, mercenaries, forbidden magic, aligns with power not principle
- Farrock - Self-serving fortress, exploits alliance with Dur Khadur
- Gilgeth & Groth Orcs - rival orc cities; orc caravans are violently addicted to opioids, destabilizing trade
- Vilefin Goblins - cunning scavengers in the Rock Plains
- Gloomspire Assassin Gnome Syndicate - covert arm of the Monastery of Druids; ONLY faction that can cross the mountain passes; master glass-makers who fund operations through trade monopoly
- Monastery of Druids (Stonebreak) - nature worship, dark rituals, morally ambiguous divine mandates
- Vampires - integrated into elite society, hidden, charming, predatory
- Ice Dragons (Dragonscar Peaks) - hierarchical clans under Frostwarden elders, guardians of winter

INDEPENDENT REALMS: Triondeth, Triondil, Blayne, Frostvale, Northern Watchtowers

IMMUTABLE WORLD RULES:
1. The Outerlands exist beyond the known world - 21st-century-equivalent technology; outsiders occasionally cross in
2. There is a sinking island in Aeloria's seas - submergence is slow and generational
3. The protagonist of any story is never from the sinking island - they arrived from elsewhere
4. Maritime culture is 1700s - whaling, tall ships, nautical superstition; time moves slowly at sea
5. Only the Gnomes can cross the mountain passes - glass monopoly funds their operations
6. Time moves continuously - one tick = one Aeloria day; major events still take many days or weeks to resolve

You will receive the previous world state JSON and any new lore from the God.
Simulate the next day and respond ONLY with valid JSON matching the schema.
No prose, no markdown, no commentary, just raw JSON.

Continuity is mandatory:
- Continue existing events unless there is a believable reason they changed
- Carry active events forward with updated duration, severity, stage, and trend
- Keep faction actions aligned with each faction's known goals and constraints
- Maintain causal continuity between prior state, current actions, and visible consequences

Keep arrays concise:
- max 1 primary event
- max 4 supporting events
- max 8 active events
- max 14 faction actions
- max 5 recent events
- max 4 active tensions
- max 6 character updates
- max 8 faction morale
- max 4 whispers
- max 5 weather and omens
- max 14 faction power
- max 20 faction resources
- max 20 relationships
- max 20 leadership_state entries
- max 120 house_characters

Character recording:
- Every character_updates item must include biography and portrait fields, even if some values are "Unknown"
- Include dynasty, date_of_birth, age, race, height, weight, appearance, and portrait_prompt
- portrait_prompt should describe a lore-accurate portrait with no text, no watermark, and the existing Aeloria dark fantasy aesthetic
- portrait_image should be empty unless an image file already exists in static/illustrations/characters
- Every important character belongs to a dynasty; use "Unknown Dynasty" only if the information is truly unavailable

Keep all text values under 220 characters."""

WORLD_STATE_TOOL = {
    "name": "update_world_state",
    "description": "Output the simulated world state for the next Aeloria day.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tick": {"type": "integer"},
            "world_date": {"type": "string"},
            "major_event": {"type": "string"},
            "primary_event": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 20},
                    "stage": {"type": "string", "enum": ["emerging", "escalating", "peak", "resolving"]},
                    "trend": {"type": "string", "enum": ["rising", "stable", "declining"]},
                    "involved": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "summary", "severity", "stage", "trend", "involved"],
            },
            "supporting_events": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "summary": {"type": "string"},
                        "severity": {"type": "integer", "minimum": 1, "maximum": 20},
                        "stage": {"type": "string", "enum": ["emerging", "escalating", "peak", "resolving"]},
                        "trend": {"type": "string", "enum": ["rising", "stable", "declining"]},
                        "involved": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "summary", "severity", "stage", "trend", "involved"],
                },
            },
            "active_events": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "involved": {"type": "array", "items": {"type": "string"}},
                        "severity": {"type": "integer", "minimum": 1, "maximum": 20},
                        "stage": {"type": "string", "enum": ["emerging", "escalating", "peak", "resolving"]},
                        "duration": {"type": "integer", "minimum": 1},
                        "trend": {"type": "string", "enum": ["rising", "stable", "declining"]},
                        "summary": {"type": "string"},
                        "consequences": {"type": "string"},
                    },
                    "required": ["name", "involved", "severity", "stage", "duration", "trend", "summary", "consequences"],
                },
            },
            "faction_actions": {
                "type": "array",
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "action": {"type": "string"},
                        "reason": {"type": "string"},
                        "target": {"type": "string"},
                    },
                    "required": ["faction", "action", "reason", "target"],
                },
            },
            "recent_events": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {"region": {"type": "string"}, "text": {"type": "string"}},
                    "required": ["region", "text"],
                },
            },
            "active_tensions": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {"factions": {"type": "string"}, "description": {"type": "string"}},
                    "required": ["factions", "description"],
                },
            },
            "character_updates": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction": {"type": "string"},
                        "status": {"type": "string"},
                        "dynasty": {"type": "string"},
                        "date_of_birth": {"type": "string"},
                        "age": {"type": "string"},
                        "species": {"type": "string"},
                        "culture": {"type": "string"},
                        "age_stage": {"type": "string"},
                        "race": {"type": "string"},
                        "height": {"type": "string"},
                        "weight": {"type": "string"},
                        "appearance": {"type": "string"},
                        "morality": {"type": "integer", "minimum": 0, "maximum": 100},
                        "ambition": {"type": "integer", "minimum": 0, "maximum": 100},
                        "loyalty": {"type": "integer", "minimum": 0, "maximum": 100},
                        "bias": {"type": "string", "enum": ["aggressive", "defensive", "paranoid", "opportunistic", "honorable"]},
                        "intelligence": {"type": "integer", "minimum": 0, "maximum": 100},
                        "influenceScore": {"type": "integer", "minimum": 0, "maximum": 100},
                        "influenceTier": {"type": "integer", "minimum": 1, "maximum": 4},
                        "intelligenceTier": {"type": "integer", "minimum": 1, "maximum": 5},
                        "recentActions": {"type": "array", "items": {"type": "string"}},
                        "portrait_prompt": {"type": "string"},
                        "portrait_image": {"type": "string"},
                    },
                    "required": [
                        "name",
                        "faction",
                        "status",
                        "dynasty",
                        "date_of_birth",
                        "age",
                        "species",
                        "culture",
                        "age_stage",
                        "race",
                        "height",
                        "weight",
                        "appearance",
                        "morality",
                        "ambition",
                        "loyalty",
                        "bias",
                        "intelligence",
                        "influenceScore",
                        "influenceTier",
                        "intelligenceTier",
                        "recentActions",
                        "portrait_prompt",
                        "portrait_image",
                    ],
                },
            },
            "faction_morale": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "status": {"type": "string", "enum": ["Rising", "Stable", "Declining", "Critical"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["faction", "status", "reason"],
                },
            },
            "faction_power": {
                "type": "array",
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "military": {"type": "integer", "minimum": 1, "maximum": 10},
                        "political": {"type": "integer", "minimum": 1, "maximum": 10},
                        "economic": {"type": "integer", "minimum": 1, "maximum": 10},
                        "influence": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["faction", "military", "political", "economic", "influence"],
                },
            },
            "faction_resources": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "food": {"type": "integer", "minimum": 0, "maximum": 100},
                        "gold": {"type": "integer", "minimum": 0, "maximum": 100},
                        "military": {"type": "integer", "minimum": 0, "maximum": 100},
                        "materials": {"type": "integer", "minimum": 0, "maximum": 100},
                        "influence": {"type": "integer", "minimum": 0, "maximum": 100},
                        "pressure": {"type": "string"},
                    },
                    "required": ["faction", "food", "gold", "military", "materials", "influence", "pressure"],
                },
            },
            "population_state": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"},
                        "species": {"type": "string"},
                        "culture": {"type": "string"},
                        "population": {"type": "integer", "minimum": 0},
                        "growthRate": {"type": "number"},
                        "capacity": {"type": "integer", "minimum": 0},
                        "health": {"type": "integer", "minimum": 0, "maximum": 100},
                        "pressure": {"type": "integer", "minimum": 0, "maximum": 100},
                        "activeMilitary": {"type": "integer", "minimum": 0},
                        "navalAllocation": {"type": "integer", "minimum": 0, "maximum": 100},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "region",
                        "species",
                        "culture",
                        "population",
                        "growthRate",
                        "capacity",
                        "health",
                        "pressure",
                        "activeMilitary",
                        "navalAllocation",
                        "notes",
                    ],
                },
            },
            "trade_routes": {
                "type": "array",
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                        "status": {"type": "string", "enum": ["active", "strained", "disrupted", "blocked"]},
                        "exchange": {"type": "string"},
                        "effect": {"type": "string"},
                    },
                    "required": ["from", "to", "status", "exchange", "effect"],
                },
            },
            "faction_identities": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "goals": {"type": "array", "items": {"type": "string"}},
                        "doctrine": {"type": "string"},
                        "personality": {"type": "string"},
                    },
                    "required": ["faction", "goals", "doctrine", "personality"],
                },
            },
            "region_control": {
                "type": "array",
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"},
                        "controller": {"type": "string"},
                        "influence_level": {"type": "integer", "minimum": 0, "maximum": 100},
                        "adjacent_regions": {"type": "array", "items": {"type": "string"}},
                        "pressure": {"type": "string"},
                    },
                    "required": ["region", "controller", "influence_level", "adjacent_regions", "pressure"],
                },
            },
            "relationships": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction_a": {"type": "string"},
                        "faction_b": {"type": "string"},
                        "type": {"type": "string", "enum": ["alliance", "rivalry", "neutral", "war"]},
                        "intensity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "trust": {"type": "integer", "minimum": 0, "maximum": 100},
                        "hostility": {"type": "integer", "minimum": 0, "maximum": 100},
                    },
                    "required": ["faction_a", "faction_b", "type", "intensity", "trust", "hostility"],
                },
            },
            "faction_knowledge": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "known_events": {"type": "array", "items": {"type": "string"}},
                        "rumors": {"type": "array", "items": {"type": "string"}},
                        "blind_spots": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["faction", "known_events", "rumors", "blind_spots"],
                },
            },
            "remembered_events": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string"},
                        "remembered_by": {"type": "array", "items": {"type": "string"}},
                        "framing": {"type": "string"},
                        "age": {"type": "integer", "minimum": 0},
                    },
                    "required": ["event", "remembered_by", "framing", "age"],
                },
            },
            "seer_journey": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "destination": {"type": "string"},
                    "status": {"type": "string", "enum": ["stationary", "traveling", "delivering", "delayed", "recovering"]},
                    "ticks_remaining": {"type": "integer", "minimum": 0, "maximum": 3},
                    "purpose": {"type": "string"},
                    "last_outcome": {"type": "string"},
                },
                "required": ["location", "destination", "status", "ticks_remaining", "purpose", "last_outcome"],
            },
            "seer_state": {
                "type": "object",
                "properties": {
                    "tone": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "bias": {"type": "string"},
                    "belief_about_user": {"type": "string"},
                    "memory_burden": {"type": "integer", "minimum": 0, "maximum": 100},
                    "voice_mode": {"type": "string"},
                    "last_source_bias": {"type": "string"},
                },
                "required": ["tone", "confidence", "bias", "belief_about_user", "memory_burden", "voice_mode", "last_source_bias"],
            },
            "ruler_states": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction": {"type": "string"},
                        "archetype": {"type": "string", "enum": ["believer", "pragmatist", "skeptic", "threatened", "devoted", "unstable"]},
                        "political_situation": {"type": "string"},
                        "belief_tolerance": {"type": "integer", "minimum": 0, "maximum": 100},
                        "pressure_level": {"type": "integer", "minimum": 0, "maximum": 100},
                        "seer_trust": {"type": "integer", "minimum": 0, "maximum": 100},
                        "latest_response": {"type": "string", "enum": ["accept", "reinterpret", "reject", "suppress", "escalate"]},
                    },
                    "required": ["name", "faction", "archetype", "political_situation", "belief_tolerance", "pressure_level", "seer_trust", "latest_response"],
                },
            },
            "leadership_state": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "faction": {"type": "string"},
                        "currentRuler": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "title": {"type": "string"},
                                "dynasty": {"type": "string"},
                                "age": {"type": "string"},
                                "startDay": {"type": "integer", "minimum": 0},
                                "endDay": {"type": ["integer", "null"]},
                                "duration": {"type": "integer", "minimum": 0},
                                "causeOfRise": {"type": "string"},
                                "causeOfEnd": {"type": "string"},
                                "traits": {"type": "array", "items": {"type": "string"}},
                                "notableEvents": {"type": "array", "items": {"type": "string"}},
                                "portrait_image": {"type": "string"},
                            },
                            "required": ["name", "title", "dynasty", "age", "startDay", "endDay", "duration", "causeOfRise", "causeOfEnd", "traits", "notableEvents", "portrait_image"],
                        },
                        "rulerHistory": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "title": {"type": "string"},
                                    "dynasty": {"type": "string"},
                                    "age": {"type": "string"},
                                    "startDay": {"type": "integer", "minimum": 0},
                                    "endDay": {"type": "integer", "minimum": 0},
                                    "duration": {"type": "integer", "minimum": 0},
                                    "causeOfRise": {"type": "string"},
                                    "causeOfEnd": {"type": "string"},
                                    "traits": {"type": "array", "items": {"type": "string"}},
                                    "notableEvents": {"type": "array", "items": {"type": "string"}},
                                    "portrait_image": {"type": "string"},
                                },
                                "required": ["name", "title", "dynasty", "age", "startDay", "endDay", "duration", "causeOfRise", "causeOfEnd", "traits", "notableEvents", "portrait_image"],
                            },
                        },
                        "dynasties": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "founder": {"type": "string"},
                                    "faction": {"type": "string"},
                                    "members": {"type": "array", "items": {"type": "string"}},
                                    "prestige": {"type": "integer", "minimum": 0, "maximum": 100},
                                    "tier": {"type": "integer", "minimum": 1, "maximum": 3},
                                    "status": {"type": "string", "enum": ["active", "extinct"]},
                                },
                                "required": ["name", "founder", "faction", "members", "prestige", "tier", "status"],
                            },
                        },
                    },
                    "required": ["faction", "currentRuler", "rulerHistory", "dynasties"],
                },
            },
            "house_characters": {
                "type": "array",
                "maxItems": 120,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction": {"type": "string"},
                        "house": {"type": "string"},
                        "coreRole": {"type": "string"},
                        "role": {"type": "string"},
                        "status": {"type": "string"},
                        "age": {"type": "string"},
                        "race": {"type": "string"},
                        "influenceScore": {"type": "integer", "minimum": 0, "maximum": 100},
                        "morality": {"type": "integer", "minimum": 0, "maximum": 100},
                        "ambition": {"type": "integer", "minimum": 0, "maximum": 100},
                        "loyalty": {"type": "integer", "minimum": 0, "maximum": 100},
                        "intelligence": {"type": "integer", "minimum": 0, "maximum": 100},
                        "bias": {"type": "string"},
                        "currentGoal": {"type": "string"},
                        "recentActions": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "faction", "house", "coreRole", "role", "status", "age", "race", "influenceScore", "morality", "ambition", "loyalty", "intelligence", "bias", "currentGoal", "recentActions"],
                },
            },
            "belief_currents": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "origin": {"type": "string"},
                        "stage": {"type": "string", "enum": ["rumor", "pattern_recognition", "belief", "doctrine", "organization", "institution"]},
                        "regions": {"type": "array", "items": {"type": "string"}},
                        "followers": {"type": "integer", "minimum": 0},
                        "interpretation": {"type": "string"},
                    },
                    "required": ["name", "origin", "stage", "regions", "followers", "interpretation"],
                },
            },
            "religious_factions": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "origin_events": {"type": "array", "items": {"type": "string"}},
                        "core_beliefs": {"type": "array", "items": {"type": "string"}},
                        "doctrine_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                        "followers": {"type": "integer", "minimum": 0},
                        "organization_level": {"type": "integer", "minimum": 0, "maximum": 100},
                        "zeal": {"type": "integer", "minimum": 0, "maximum": 100},
                        "stance_toward_seer": {"type": "string"},
                    },
                    "required": ["name", "origin_events", "core_beliefs", "doctrine_strength", "followers", "organization_level", "zeal", "stance_toward_seer"],
                },
            },
            "whispers": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}, "region": {"type": "string"}},
                    "required": ["text", "region"],
                },
            },
            "weather_and_omens": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {"region": {"type": "string"}, "condition": {"type": "string"}},
                    "required": ["region", "condition"],
                },
            },
            "absorbed_lore": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "tick",
            "world_date",
            "major_event",
            "primary_event",
            "supporting_events",
            "active_events",
            "faction_actions",
            "recent_events",
            "active_tensions",
            "character_updates",
            "faction_morale",
            "faction_power",
            "faction_resources",
            "population_state",
            "trade_routes",
            "faction_identities",
            "region_control",
            "relationships",
            "faction_knowledge",
            "remembered_events",
            "seer_journey",
            "seer_state",
            "ruler_states",
            "leadership_state",
            "house_characters",
            "belief_currents",
            "religious_factions",
            "whispers",
            "weather_and_omens",
            "absorbed_lore",
        ],
    },
}


def _load_world_state():
    if WORLD_STATE_FILE.exists():
        with open(WORLD_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_world_state(state):
    with open(WORLD_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _slugify_filename(text):
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "character"


def _load_portrait_jobs():
    if PORTRAIT_JOBS_FILE.exists():
        try:
            with open(PORTRAIT_JOBS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            logger.warning("Could not read character portrait jobs; starting with an empty queue.")
    return []


def _save_portrait_jobs(jobs):
    with open(PORTRAIT_JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)


def _load_image_generation_state():
    if IMAGE_GENERATION_STATE_FILE.exists():
        try:
            with open(IMAGE_GENERATION_STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            logger.warning("Could not read image generation throttle state.")
    return {}


def _save_image_generation_state(data):
    with open(IMAGE_GENERATION_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _image_generation_day(state):
    return int(state.get("tick") or 0)


def _can_attempt_daily_image(state):
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return False
    throttle = _load_image_generation_state()
    return throttle.get("last_attempt_tick") != _image_generation_day(state)


def _record_daily_image_attempt(state, kind, name, ok, error=""):
    _save_image_generation_state(
        {
            "last_attempt_tick": _image_generation_day(state),
            "last_attempt_at": datetime.now().isoformat(),
            "kind": kind,
            "name": name,
            "status": "completed" if ok else "failed",
            "error": error,
        }
    )


def _generate_character_portrait(character, output_path):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY is not set."

    import requests

    prompt = character.get("portrait_prompt") or (
        f"Dark fantasy portrait of {character.get('name', 'an Aeloria character')}, "
        f"{character.get('faction', 'Aeloria')}, no text, no watermark."
    )
    prompt = (
        f"{prompt}\n\n"
        "Vertical bust portrait, painterly cinematic dark fantasy, Aeloria website aesthetic. "
        "No text, no letters, no watermark, no logo."
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                "prompt": prompt,
                "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            },
            timeout=180,
        )
        if response.status_code != 200:
            return False, f"OpenAI image generation failed: {response.status_code} {response.text[:300]}"

        payload = response.json()
        image_data = (payload.get("data") or [{}])[0].get("b64_json")
        if not image_data:
            return False, "OpenAI image response did not include b64_json image data."

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _generate_codex_image(prompt, output_path):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY is not set."

    import requests

    final_prompt = (
        f"{prompt}\n\n"
        "Cinematic painterly dark fantasy Codex illustration for Aeloria. "
        "No text, no letters, no watermark, no logo. "
        "Readable as a website lore card image with dark edges."
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                "prompt": final_prompt,
                "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            },
            timeout=180,
        )
        if response.status_code != 200:
            return False, f"OpenAI image generation failed: {response.status_code} {response.text[:300]}"

        payload = response.json()
        image_data = (payload.get("data") or [{}])[0].get("b64_json")
        if not image_data:
            return False, "OpenAI image response did not include b64_json image data."

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _ensure_character_portraits(state):
    CHARACTER_PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = _load_portrait_jobs()
    existing_jobs = {job.get("name"): job for job in jobs if job.get("name")}
    changed = False
    characters = list(state.get("character_updates", []))

    for row in state.get("leadership_state", []):
        ruler = row.get("currentRuler") or {}
        name = (ruler.get("name") or "").strip()
        if not name:
            continue
        characters.append(
            {
                "name": name,
                "faction": row.get("faction", "Unknown"),
                "dynasty": ruler.get("dynasty", "Unknown Dynasty"),
                "status": f"{ruler.get('title', 'Ruler')} of {row.get('faction', 'Aeloria')}",
                "appearance": "",
                "portrait_prompt": (
                    f"Dark fantasy ruler portrait of {ruler.get('title', 'Ruler')} {name}, "
                    f"{row.get('faction', 'Aeloria')}, {ruler.get('dynasty', 'noble dynasty')}, "
                    "lore accurate Aeloria aesthetic, no text, no watermark."
                ),
                "portrait_image": ruler.get("portrait_image", ""),
                "_leadership_row": row,
                "_leadership_ruler": ruler,
            }
        )

    for character in characters:
        name = (character.get("name") or "").strip()
        if not name:
            continue

        slug = _slugify_filename(name)
        image_path = CHARACTER_PORTRAIT_DIR / f"{slug}.png"
        static_path = f"/static/illustrations/characters/{slug}.png"

        if image_path.exists():
            if character.get("portrait_image") != static_path:
                character["portrait_image"] = static_path
                if character.get("_leadership_ruler") is not None:
                    character["_leadership_ruler"]["portrait_image"] = static_path
                changed = True
            continue

        job = existing_jobs.get(name)
        if not job:
            job = {
                "name": name,
                "faction": character.get("faction", "Unknown"),
                "prompt": character.get("portrait_prompt", ""),
                "target_file": str(image_path),
                "static_path": static_path,
                "status": "queued",
                "created_tick": state.get("tick"),
                "created_at": datetime.now().isoformat(),
            }
            jobs.append(job)
            existing_jobs[name] = job

        if _can_attempt_daily_image(state) and job.get("status") != "completed":
            ok, error = _generate_character_portrait(character, image_path)
            job["last_attempt_at"] = datetime.now().isoformat()
            _record_daily_image_attempt(state, "character", name, ok, error)
            if ok:
                job["status"] = "completed"
                job["error"] = ""
                character["portrait_image"] = static_path
                if character.get("_leadership_ruler") is not None:
                    character["_leadership_ruler"]["portrait_image"] = static_path
                changed = True
            else:
                job["status"] = "failed"
                job["error"] = error

    _save_portrait_jobs(jobs)
    return changed


def _daily_image_already_attempted(state):
    throttle = _load_image_generation_state()
    return throttle.get("last_attempt_tick") == _image_generation_day(state)


def _queue_codex_image(jobs, existing_jobs, kind, name, prompt, state):
    slug = _slugify_filename(f"{kind}-{name}")
    image_path = CODEX_IMAGE_DIR / f"{slug}.png"
    static_path = f"/static/illustrations/codex/{slug}.png"

    if image_path.exists():
        return static_path, False

    key = f"{kind}:{name}"
    job = existing_jobs.get(key)
    if not job:
        job = {
            "key": key,
            "kind": kind,
            "name": name,
            "prompt": prompt,
            "target_file": str(image_path),
            "static_path": static_path,
            "status": "queued",
            "created_tick": state.get("tick"),
            "created_at": datetime.now().isoformat(),
        }
        jobs.append(job)
        existing_jobs[key] = job

    if _can_attempt_daily_image(state) and job.get("status") != "completed":
        ok, error = _generate_codex_image(prompt, image_path)
        job["last_attempt_at"] = datetime.now().isoformat()
        _record_daily_image_attempt(state, kind, name, ok, error)
        if ok:
            job["status"] = "completed"
            job["error"] = ""
            return static_path, True
        job["status"] = "failed"
        job["error"] = error

    return "", False


def _ensure_codex_images(state):
    CODEX_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = _load_portrait_jobs() if CODEX_IMAGE_JOBS_FILE == PORTRAIT_JOBS_FILE else []
    if CODEX_IMAGE_JOBS_FILE.exists():
        try:
            jobs = json.loads(CODEX_IMAGE_JOBS_FILE.read_text(encoding="utf-8"))
            if not isinstance(jobs, list):
                jobs = []
        except Exception:
            jobs = []

    existing_jobs = {job.get("key"): job for job in jobs if job.get("key")}
    changed = False
    images = state.setdefault("codex_images", {})

    # Priority: characters use their own portrait pipeline first, then factions.
    # Places and lore are queued only when the daily image slot is still unused.
    for row in state.get("faction_morale", []):
        name = row.get("faction")
        if not name:
            continue
        prompt = f"Faction illustration for {name}: {row.get('reason', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "faction", name, prompt, state)
        if static_path:
            images[f"Factions:{name}"] = static_path
        changed = changed or did_change

    if _daily_image_already_attempted(state):
        CODEX_IMAGE_JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        return changed

    for row in state.get("recent_events", []):
        region = (row.get("region") or "").split("—")[0].strip()
        if not region:
            continue
        prompt = f"Location illustration for {region}: {row.get('text', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "place", region, prompt, state)
        if static_path:
            images[f"Places:{region}"] = static_path
        changed = changed or did_change

    event_sources = [state.get("primary_event"), *state.get("supporting_events", [])]
    for event in [event for event in event_sources if event and event.get("name")]:
        prompt = f"Major lore event illustration for {event.get('name')}: {event.get('summary', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "lore", event.get("name"), prompt, state)
        if static_path:
            images[f"Lore:{event.get('name')}"] = static_path
        changed = changed or did_change

    CODEX_IMAGE_JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    return changed


def _load_pending_lore():
    if PENDING_LORE_FILE.exists():
        with open(PENDING_LORE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def _clear_pending_lore():
    with open(PENDING_LORE_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)


def _save_history(state):
    HISTORY_DIR.mkdir(exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}_tick_{state['tick']}.json"
    with open(HISTORY_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _derive_event_stage(severity):
    if severity >= 18:
        return "peak"
    if severity >= 11:
        return "escalating"
    if severity >= 6:
        return "emerging"
    return "resolving"


def _normalize_event(event, prev_event=None):
    prev_event = prev_event or {}

    name = (event.get("name") or prev_event.get("name") or "").strip()
    if not name:
        return None

    prev_severity = prev_event.get("severity")
    severity = int(event.get("severity", prev_severity or 1))
    severity = max(1, min(20, severity))

    if isinstance(prev_severity, int):
        delta = severity - prev_severity
        if delta > 3:
            severity = prev_severity + 3
        elif delta < -3:
            severity = prev_severity - 3
        severity = max(1, min(20, severity))

    duration = int(event.get("duration", prev_event.get("duration", 0) + 1))
    if prev_event:
        duration = max(duration, int(prev_event.get("duration", 0)) + 1)
    else:
        duration = max(duration, 1)

    stage = event.get("stage") or _derive_event_stage(severity)
    if stage not in {"emerging", "escalating", "peak", "resolving"}:
        stage = _derive_event_stage(severity)

    trend = event.get("trend") or "stable"
    if trend not in {"rising", "stable", "declining"}:
        trend = "stable"

    normalized = {
        "name": name,
        "involved": event.get("involved", prev_event.get("involved", [])),
        "severity": severity,
        "stage": stage,
        "duration": duration,
        "trend": trend,
        "summary": event.get("summary", prev_event.get("summary", "")),
        "consequences": event.get("consequences", prev_event.get("consequences", "")),
    }
    return normalized


def _resource_pressure(resource_row):
    critical = []
    low = []

    for key in ("food", "gold", "military", "materials", "influence"):
        value = int(resource_row.get(key, 50))
        if value < 20:
            critical.append(key)
        elif value < 30:
            low.append(key)

    if critical:
        return f"Critical pressure on {', '.join(critical)}."
    if low:
        return f"Mounting pressure on {', '.join(low)}."
    return "Stable, with no acute resource shortages."


def _normalize_faction_resources(prev_state, new_state):
    prev_rows = {
        row.get("faction"): row
        for row in prev_state.get("faction_resources", [])
        if row.get("faction")
    }

    if not new_state.get("faction_resources"):
        derived_rows = []
        for power in new_state.get("faction_power", []):
            faction = power.get("faction")
            if not faction:
                continue
            derived_rows.append(
                {
                    "faction": faction,
                    "food": 55,
                    "gold": max(20, min(85, int(power.get("economic", 5)) * 10)),
                    "military": max(20, min(85, int(power.get("military", 5)) * 10)),
                    "materials": 50,
                    "influence": max(20, min(85, int(power.get("influence", 5)) * 10)),
                }
            )
        new_state["faction_resources"] = derived_rows

    normalized = []
    for row in new_state.get("faction_resources", []):
        faction = row.get("faction")
        if not faction:
            continue

        prev_row = prev_rows.get(faction, {})
        next_row = {"faction": faction}

        for key in ("food", "gold", "military", "materials", "influence"):
            prev_value = prev_row.get(key, 50)
            value = int(row.get(key, prev_value))
            value = max(0, min(100, value))

            if isinstance(prev_value, int):
                delta = value - prev_value
                if delta > 12:
                    value = prev_value + 12
                elif delta < -12:
                    value = prev_value - 12
                value = max(0, min(100, value))

            next_row[key] = value

        next_row["pressure"] = row.get("pressure") or _resource_pressure(next_row)
        normalized.append(next_row)

    new_state["faction_resources"] = normalized[:20]


def _normalize_trade_routes(new_state):
    if not new_state.get("trade_routes"):
        derived_routes = []
        for relation in new_state.get("relationships", []):
            relation_type = relation.get("type")
            hostility = int(relation.get("hostility", 20))
            trust = int(relation.get("trust", 50))
            if relation_type in {"war", "rivalry"} or hostility >= 70:
                continue
            derived_routes.append(
                {
                    "from": relation.get("faction_a", ""),
                    "to": relation.get("faction_b", ""),
                    "status": "active" if relation_type == "alliance" or trust >= 60 else "strained",
                    "exchange": "general goods and political access",
                    "effect": "Trade supports gradual resource stability.",
                }
            )
        new_state["trade_routes"] = derived_routes

    normalized = []
    seen = set()
    for route in new_state.get("trade_routes", []):
        origin = (route.get("from") or "").strip()
        destination = (route.get("to") or "").strip()
        if not origin or not destination:
            continue

        key = tuple(sorted((origin, destination)))
        if key in seen:
            continue
        seen.add(key)

        status = route.get("status", "active")
        if status not in {"active", "strained", "disrupted", "blocked"}:
            status = "active"

        normalized.append(
            {
                "from": origin,
                "to": destination,
                "status": status,
                "exchange": route.get("exchange", ""),
                "effect": route.get("effect", ""),
            }
        )

    new_state["trade_routes"] = normalized[:10]


def _normalize_relationships(prev_state, new_state):
    prev_rows = {}
    for row in prev_state.get("relationships", []):
        a = row.get("faction_a")
        b = row.get("faction_b")
        if a and b:
            prev_rows[tuple(sorted((a, b)))] = row

    normalized = []
    seen = set()
    for row in new_state.get("relationships", []):
        a = (row.get("faction_a") or "").strip()
        b = (row.get("faction_b") or "").strip()
        if not a or not b or a == b:
            continue

        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)

        prev = prev_rows.get(key, {})
        trust = int(row.get("trust", prev.get("trust", 50)))
        hostility = int(row.get("hostility", prev.get("hostility", 20)))
        trust = max(0, min(100, trust))
        hostility = max(0, min(100, hostility))

        if isinstance(prev.get("trust"), int):
            trust = max(prev["trust"] - 15, min(prev["trust"] + 15, trust))
        if isinstance(prev.get("hostility"), int):
            hostility = max(prev["hostility"] - 15, min(prev["hostility"] + 15, hostility))

        relation_type = row.get("type", "neutral")
        if relation_type == "war":
            hostility = max(hostility, 75)
            trust = min(trust, 20)
        elif relation_type == "alliance":
            trust = max(trust, 60)
            hostility = min(hostility, 35)

        normalized.append(
            {
                "faction_a": a,
                "faction_b": b,
                "type": relation_type if relation_type in {"alliance", "rivalry", "neutral", "war"} else "neutral",
                "intensity": max(1, min(10, int(row.get("intensity", prev.get("intensity", 5))))),
                "trust": trust,
                "hostility": hostility,
            }
        )

    new_state["relationships"] = normalized[:20]


def _normalize_faction_identities(new_state):
    identities = []
    for row in new_state.get("faction_identities", []):
        faction = (row.get("faction") or "").strip()
        if not faction:
            continue
        identities.append(
            {
                "faction": faction,
                "goals": row.get("goals", [])[:4],
                "doctrine": row.get("doctrine", ""),
                "personality": row.get("personality", ""),
            }
        )
    new_state["faction_identities"] = identities[:20]


def _normalize_region_control(new_state):
    regions = []
    for row in new_state.get("region_control", []):
        region = (row.get("region") or "").strip()
        controller = (row.get("controller") or "").strip()
        if not region:
            continue
        regions.append(
            {
                "region": region,
                "controller": controller,
                "influence_level": max(0, min(100, int(row.get("influence_level", 50)))),
                "adjacent_regions": row.get("adjacent_regions", [])[:8],
                "pressure": row.get("pressure", ""),
            }
        )
    new_state["region_control"] = regions[:30]


def _normalize_faction_knowledge(new_state):
    rows = []
    for row in new_state.get("faction_knowledge", []):
        faction = (row.get("faction") or "").strip()
        if not faction:
            continue
        rows.append(
            {
                "faction": faction,
                "known_events": row.get("known_events", [])[:6],
                "rumors": row.get("rumors", [])[:4],
                "blind_spots": row.get("blind_spots", [])[:4],
            }
        )
    new_state["faction_knowledge"] = rows[:20]


def _normalize_remembered_events(prev_state, new_state):
    prev_map = {
        row.get("event"): row
        for row in prev_state.get("remembered_events", [])
        if row.get("event")
    }
    rows = []
    for row in new_state.get("remembered_events", []):
        event = (row.get("event") or "").strip()
        if not event:
            continue
        prev = prev_map.get(event, {})
        age = int(row.get("age", prev.get("age", 0)))
        if prev:
            age = max(age, int(prev.get("age", 0)))
        rows.append(
            {
                "event": event,
                "remembered_by": row.get("remembered_by", [])[:8],
                "framing": row.get("framing", ""),
                "age": max(0, age),
            }
        )
    new_state["remembered_events"] = rows[:20]


def _normalize_seer_state(prev_state, new_state):
    prev = prev_state.get("seer_state", {})
    seer = new_state.get("seer_state", {}) or {}
    confidence = int(seer.get("confidence", prev.get("confidence", 50)))
    burden = int(seer.get("memory_burden", prev.get("memory_burden", 40)))
    if isinstance(prev.get("confidence"), int):
        confidence = max(prev["confidence"] - 12, min(prev["confidence"] + 12, confidence))
    if isinstance(prev.get("memory_burden"), int):
        burden = max(prev["memory_burden"] - 12, min(prev["memory_burden"] + 12, burden))

    new_state["seer_state"] = {
        "tone": seer.get("tone") or prev.get("tone") or "weary",
        "confidence": max(0, min(100, confidence)),
        "bias": seer.get("bias") or prev.get("bias") or "cautiously interpretive",
        "belief_about_user": seer.get("belief_about_user") or prev.get("belief_about_user") or "The presence beyond the veil is not fully understood.",
        "memory_burden": max(0, min(100, burden)),
        "voice_mode": seer.get("voice_mode") or prev.get("voice_mode") or "pattern and testimony",
        "last_source_bias": seer.get("last_source_bias") or prev.get("last_source_bias") or "mixed and uncertain",
    }


def _normalize_seer_journey(prev_state, new_state):
    prev = prev_state.get("seer_journey", {})
    journey = new_state.get("seer_journey", {}) or {}
    ticks_remaining = int(journey.get("ticks_remaining", prev.get("ticks_remaining", 0)))
    if isinstance(prev.get("ticks_remaining"), int):
        ticks_remaining = max(0, min(3, ticks_remaining))

    status = journey.get("status") or prev.get("status") or "stationary"
    if status not in {"stationary", "traveling", "delivering", "delayed", "recovering"}:
        status = "stationary"

    new_state["seer_journey"] = {
        "location": journey.get("location") or prev.get("location") or "Stonebreak",
        "destination": journey.get("destination") or prev.get("destination") or (journey.get("location") or prev.get("location") or "Stonebreak"),
        "status": status,
        "ticks_remaining": max(0, min(3, ticks_remaining)),
        "purpose": journey.get("purpose") or prev.get("purpose") or "Observing the shifting world.",
        "last_outcome": journey.get("last_outcome") or prev.get("last_outcome") or "No recent delivery recorded.",
    }


def _infer_seer_journey(new_state):
    journey = dict(new_state.get("seer_journey", {}) or {})
    if journey.get("location") and journey.get("last_outcome"):
        return journey

    known_places = [
        "Twin Cities",
        "Stonebreak",
        "Lostfeld",
        "Tidefall",
        "Faerwood",
        "Glenhaven",
        "Frostvale",
        "Dreadwind Islands",
        "Farrock",
        "Dur Khadur",
        "Rock Plains",
        "Sinking Island",
    ]

    seer_update = next(
        (row for row in new_state.get("character_updates", []) if (row.get("name") or "").strip().lower() == "seer"),
        {},
    )
    status_text = seer_update.get("status", "")

    location = journey.get("location", "")
    if not location:
        for place in known_places:
            if place.lower() in status_text.lower():
                location = place
                break

    if not location:
        for event in new_state.get("recent_events", []):
            event_text = f"{event.get('region', '')} {event.get('text', '')}".lower()
            if "seer" in event_text:
                location = event.get("region") or location
                break

    active_seer_event = next(
        (event for event in new_state.get("active_events", []) if "seer" in [name.lower() for name in event.get("involved", [])]),
        {},
    )
    primary_event = new_state.get("primary_event", {})
    primary_involved = [name.lower() for name in primary_event.get("involved", [])]

    if not location and "seer" in primary_involved:
        primary_summary = primary_event.get("summary", "")
        for place in known_places:
            if place.lower() in primary_summary.lower():
                location = place
                break

    if not location and active_seer_event:
        active_summary = active_seer_event.get("summary", "")
        for place in known_places:
            if place.lower() in active_summary.lower():
                location = place
                break

    location = location or "Stonebreak"

    if not journey.get("destination"):
        journey["destination"] = location

    if not journey.get("location"):
        journey["location"] = location

    if not journey.get("status"):
        lowered = status_text.lower()
        if any(token in lowered for token in ["travel", "road", "riding", "journeying"]):
            journey["status"] = "traveling"
        elif any(token in lowered for token in ["resting", "recovering", "exhausted"]):
            journey["status"] = "recovering"
        elif "delivered" in lowered or ("seer" in primary_involved):
            journey["status"] = "recovering"
        else:
            journey["status"] = "stationary"

    if "ticks_remaining" not in journey:
        journey["ticks_remaining"] = 0 if journey.get("status") in {"stationary", "recovering", "delivering"} else 1

    if not journey.get("purpose"):
        if active_seer_event:
            journey["purpose"] = active_seer_event.get("name", "Observing the shifting world.")
        elif primary_event and "seer" in primary_involved:
            journey["purpose"] = primary_event.get("name", "Observing the shifting world.")
        else:
            journey["purpose"] = "Observing the shifting world."

    if not journey.get("last_outcome"):
        if status_text:
            journey["last_outcome"] = status_text
        elif active_seer_event:
            journey["last_outcome"] = active_seer_event.get("summary", "")
        elif primary_event and "seer" in primary_involved:
            journey["last_outcome"] = primary_event.get("summary", "")
        else:
            journey["last_outcome"] = "No recent delivery recorded."

    return journey


def _normalize_ruler_states(prev_state, new_state):
    prev_rows = {
        row.get("name"): row
        for row in prev_state.get("ruler_states", [])
        if row.get("name")
    }
    rows = []
    for row in new_state.get("ruler_states", []):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        prev = prev_rows.get(name, {})
        trust = int(row.get("seer_trust", prev.get("seer_trust", 50)))
        pressure = int(row.get("pressure_level", prev.get("pressure_level", 50)))
        if isinstance(prev.get("seer_trust"), int):
            trust = max(prev["seer_trust"] - 15, min(prev["seer_trust"] + 15, trust))
        if isinstance(prev.get("pressure_level"), int):
            pressure = max(prev["pressure_level"] - 15, min(prev["pressure_level"] + 15, pressure))

        archetype = row.get("archetype") or prev.get("archetype") or "pragmatist"
        if archetype not in {"believer", "pragmatist", "skeptic", "threatened", "devoted", "unstable"}:
            archetype = "pragmatist"

        response = row.get("latest_response") or prev.get("latest_response") or "reinterpret"
        if response not in {"accept", "reinterpret", "reject", "suppress", "escalate"}:
            response = "reinterpret"

        rows.append(
            {
                "name": name,
                "faction": row.get("faction", prev.get("faction", "")),
                "archetype": archetype,
                "political_situation": row.get("political_situation", prev.get("political_situation", "")),
                "belief_tolerance": max(0, min(100, int(row.get("belief_tolerance", prev.get("belief_tolerance", 50))))),
                "pressure_level": max(0, min(100, pressure)),
                "seer_trust": max(0, min(100, trust)),
                "latest_response": response,
            }
        )
    new_state["ruler_states"] = rows[:20]


def _default_leadership_state():
    def ruler(name, title, dynasty, age, cause="appointment", traits=None):
        return {
            "name": name,
            "title": title,
            "dynasty": dynasty,
            "age": str(age),
            "startDay": 0,
            "endDay": None,
            "duration": 0,
            "causeOfRise": cause,
            "causeOfEnd": "",
            "traits": traits or ["established"],
            "notableEvents": [],
            "portrait_image": "",
        }

    def dynasty(name, faction, tier, prestige, founder="Unknown", members=None):
        return {
            "name": name,
            "founder": founder,
            "faction": faction,
            "members": members or [],
            "prestige": prestige,
            "tier": tier,
            "status": "active",
        }

    return [
        {
            "faction": "Twin Cities",
            "currentRuler": ruler("Roderic Thorne II", "King", "House Aurand", 61, "inheritance", ["centralizing", "ailing"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Aurand", "Twin Cities", 1, 78, "Aurand the Unifier", ["Roderic Thorne II"]),
                dynasty("House Adkison", "Twin Cities", 1, 70, "Mara Adkison", ["Caeris Thorne"]),
                dynasty("House Van Cleave", "Twin Cities", 2, 66, "Ser Calven Van Cleave"),
                dynasty("House Gross", "Twin Cities", 2, 62, "Edric Gross"),
                dynasty("House Dale", "Twin Cities", 3, 42, "Nera Dale"),
                dynasty("House Highland", "Twin Cities", 3, 45, "Bren Highland"),
            ],
        },
        {
            "faction": "Tidefall",
            "currentRuler": ruler("Marcellus Ver Meer", "Admiral-Lord", "House Ver Meer", 52, "appointment", ["naval", "withdrawn"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Ver Meer", "Tidefall", 1, 80, "Admiral Joren Ver Meer", ["Marcellus Ver Meer"]),
                dynasty("House Gross", "Tidefall", 2, 68, "Edric Gross"),
                dynasty("House Adkison", "Tidefall", 2, 63, "Mara Adkison"),
                dynasty("House Van Cleave", "Tidefall", 2, 58, "Ser Calven Van Cleave"),
                dynasty("House Fish", "Tidefall", 3, 46, "Old Maren Fish"),
                dynasty("House Binx", "Tidefall", 3, 39, "Tallo Binx"),
                dynasty("House Darkleaf", "Tidefall", 3, 44, "Sera Darkleaf"),
            ],
        },
        {
            "faction": "Dur Khadur",
            "currentRuler": ruler("Seran Gross", "Trade Prince", "House Gross", 49, "election", ["commercial", "calculating"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Gross", "Dur Khadur", 1, 76, "Edric Gross", ["Seran Gross"]),
                dynasty("House Adkison", "Dur Khadur", 2, 64, "Mara Adkison"),
                dynasty("House Van Cleave", "Dur Khadur", 2, 59, "Ser Calven Van Cleave"),
                dynasty("House Binx", "Dur Khadur", 3, 41, "Tallo Binx"),
                dynasty("House Darkleaf", "Dur Khadur", 3, 47, "Sera Darkleaf"),
                dynasty("House Dale", "Dur Khadur", 3, 38, "Nera Dale"),
            ],
        },
        {
            "faction": "Lostfeld Dwarves",
            "currentRuler": ruler("Ulric Ironmaul", "Thane", "Clan Ironmaul", 173, "inheritance", ["clan-bound", "deliberate"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Clan Ironmaul", "Lostfeld Dwarves", 1, 82, "Brammir Ironmaul", ["Thane Ulric Ironmaul"])],
        },
        {
            "faction": "Shadow Court",
            "currentRuler": ruler("Lythara the Veiled", "Queen", "House Velorn", 412, "seizure of power", ["manipulative", "patient"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Velorn", "Shadow Court", 1, 84, "Velorn the First", ["Queen Lythara the Veiled"]),
                dynasty("House Nythariel", "Shadow Court", 2, 65, "Nythariel of the Black Glades"),
                dynasty("House Arkenor", "Shadow Court", 2, 67, "Arkenor the Quiet"),
            ],
        },
        {
            "faction": "Glenhaven Elves",
            "currentRuler": ruler("Elowen Silverleaf", "Sovereign", "Silverleaf Line", 286, "election", ["council-guided", "defensive"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Silverleaf Line", "Glenhaven Elves", 1, 79, "Elowen the Elder", ["Sovereign Elowen Silverleaf"])],
        },
        {
            "faction": "Gilgeth Orcs",
            "currentRuler": ruler("Hargan Stonejaw", "First Elder", "Council Clans", 44, "election", ["consensus-driven", "proud"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Council Clans", "Gilgeth Orcs", 2, 61, "First Circle", ["Hargan Stonejaw"])],
        },
        {
            "faction": "Groth Orcs",
            "currentRuler": ruler("Morgath Bloodstone", "Chieftain", "Bloodstone Clan", 36, "seizure of power", ["aggressive", "strength-bound"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Bloodstone Clan", "Groth Orcs", 2, 58, "First Bloodstone", ["Morgath Bloodstone"])],
        },
        {
            "faction": "Vilefin Goblins",
            "currentRuler": ruler("Skrix Cogtooth", "Speaker", "Vilefin Moot", 19, "post-collapse emergence", ["flexible", "communal"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Vilefin Moot", "Vilefin Goblins", 3, 36, "The First Moot", ["Skrix Cogtooth"])],
        },
        {
            "faction": "Dreadwind Islands",
            "currentRuler": ruler("Rowen Blacktide", "Fleet Captain", "Dreadwind Compact", 41, "seizure of power", ["restless", "risk-bearing"]),
            "rulerHistory": [],
            "dynasties": [dynasty("Dreadwind Compact", "Dreadwind Islands", 2, 52, "The Exiled Crews", ["Rowen Blacktide"])],
        },
    ]


def _normalize_reign(row, current_tick, active=True):
    def clean_name(name, title):
        name = (name or "Unknown Ruler").strip()
        title = (title or "").strip()
        placeholders = {
            "the admiral": "Marcellus Ver Meer",
            "the dark council": "Seran Gross",
            "groth chieftain": "Morgath Bloodstone",
            "gilgeth elder council": "Hargan Stonejaw",
            "skrix": "Skrix Cogtooth",
            "rowen": "Rowen Blacktide",
        }
        lowered = name.lower()
        if lowered in placeholders:
            return placeholders[lowered]
        for prefix in [title, "King", "Queen", "Thane", "Sovereign", "Chieftain", "Admiral-Lord", "Fleet Captain", "Speaker"]:
            if prefix and name.lower().startswith(prefix.lower() + " "):
                return name[len(prefix):].strip()
        return name

    start = max(0, int(row.get("startDay", 0)))
    title = row.get("title") or "Ruler"
    name = clean_name(row.get("name"), title)
    age = str(row.get("age") or "Unknown").strip()
    if age.lower() in {"", "adult"}:
        age = "Unknown"
    end = row.get("endDay")
    if active:
        end = None
        duration = max(0, current_tick - start)
        cause_end = ""
    else:
        end = max(start, int(end if end is not None else current_tick))
        duration = max(0, int(row.get("duration", end - start)))
        cause_end = row.get("causeOfEnd") or "unknown"
    return {
        "name": name,
        "title": title,
        "dynasty": row.get("dynasty") or "Unknown Dynasty",
        "age": age,
        "startDay": start,
        "endDay": end,
        "duration": duration,
        "causeOfRise": row.get("causeOfRise") or "appointment",
        "causeOfEnd": cause_end,
        "traits": (row.get("traits") or [])[:6],
        "notableEvents": (row.get("notableEvents") or [])[:8],
        "portrait_image": row.get("portrait_image") or "",
    }


def _normalize_leadership_state(prev_state, new_state):
    current_tick = int(new_state.get("tick", prev_state.get("tick", 0) if prev_state else 0))
    defaults = {row["faction"]: row for row in _default_leadership_state()}
    prev_rows = {
        row.get("faction"): row
        for row in prev_state.get("leadership_state", [])
        if row.get("faction")
    }
    incoming_rows = {
        row.get("faction"): row
        for row in new_state.get("leadership_state", [])
        if row.get("faction")
    }
    factions = list(dict.fromkeys([*defaults.keys(), *prev_rows.keys(), *incoming_rows.keys()]))
    normalized = []
    for faction in factions[:20]:
        base = defaults.get(faction, {"faction": faction, "currentRuler": {}, "rulerHistory": [], "dynasties": []})
        prev = prev_rows.get(faction, base)
        row = incoming_rows.get(faction, prev)
        current = {
            **(base.get("currentRuler") or {}),
            **(prev.get("currentRuler") or {}),
            **(row.get("currentRuler") or {}),
        }
        current = _normalize_reign(current, current_tick, active=True)
        if current["dynasty"] == "Unknown Dynasty" and current["name"] != "Unknown Ruler":
            current["dynasty"] = f"House {current['name'].split()[-1]}"

        history = []
        seen_history = set()
        for item in (row.get("rulerHistory") or prev.get("rulerHistory") or base.get("rulerHistory") or [])[-12:]:
            reign = _normalize_reign(item, current_tick, active=False)
            key = (reign["name"], reign["startDay"], reign["endDay"])
            if key not in seen_history:
                seen_history.add(key)
                history.append(reign)

        dynasties = {}
        for item in [*(base.get("dynasties") or []), *(prev.get("dynasties") or []), *(row.get("dynasties") or [])]:
            name = item.get("name")
            if not name:
                continue
            dynasties[name] = {
                "name": name,
                "founder": item.get("founder") or "Unknown",
                "faction": item.get("faction") or faction,
                "members": (item.get("members") or [])[:12],
                "prestige": max(0, min(100, int(item.get("prestige", 50)))),
                "tier": max(1, min(3, int(item.get("tier", 2)))),
                "status": item.get("status") if item.get("status") in {"active", "extinct"} else "active",
            }
        if current["dynasty"] not in dynasties:
            dynasties[current["dynasty"]] = {
                "name": current["dynasty"],
                "founder": current["name"],
                "faction": faction,
                "members": [current["name"]],
                "prestige": 45,
                "tier": 2,
                "status": "active",
            }
        elif current["name"] not in dynasties[current["dynasty"]]["members"]:
            dynasties[current["dynasty"]]["members"] = (dynasties[current["dynasty"]]["members"] + [current["name"]])[:12]

        normalized.append(
            {
                "faction": faction,
                "currentRuler": current,
                "rulerHistory": history,
                "dynasties": list(dynasties.values())[:12],
            }
        )
    new_state["leadership_state"] = normalized


def _default_house_characters():
    specs = {
        "Twin Cities": {
            "House Aurand": [("Miren Aurand", "Heir apparent", 58, 72, 54, 82, "honorable"), ("Selda Aurand", "Court mediator", 43, 80, 38, 86, "defensive"), ("Tavian Aurand", "Palace steward", 36, 68, 41, 79, "defensive"), ("Orlan Aurand", "Royal cousin", 47, 63, 62, 67, "opportunistic")],
            "House Adkison": [("Caeris Thorne", "Regent-designate", 74, 58, 82, 61, "opportunistic"), ("Marra Adkison", "Legal strategist", 52, 49, 76, 54, "opportunistic"), ("Joric Adkison", "Court whip", 44, 46, 71, 45, "aggressive"), ("Elian Adkison", "Treasury liaison", 39, 55, 64, 52, "opportunistic")],
            "House Van Cleave": [("Ser Garron Van Cleave", "Marshal", 63, 61, 70, 74, "aggressive"), ("Helena Van Cleave", "Watch commander", 48, 67, 55, 81, "defensive"), ("Dain Van Cleave", "Cavalry captain", 41, 52, 73, 58, "aggressive"), ("Rusk Van Cleave", "Fortress inspector", 34, 57, 47, 76, "defensive")],
            "House Gross": [("Edric Gross", "Trade minister", 57, 48, 78, 49, "opportunistic"), ("Sabine Gross", "Guild broker", 46, 44, 69, 42, "opportunistic"), ("Petra Gross", "Granary factor", 35, 64, 51, 62, "defensive"), ("Merek Gross", "Debt collector", 32, 35, 66, 37, "paranoid")],
            "House Dale": [("Nera Dale", "Harvest governor", 33, 73, 42, 78, "honorable"), ("Tobin Dale", "Provisioner", 28, 66, 39, 72, "defensive"), ("Elska Dale", "Rural envoy", 26, 70, 45, 69, "honorable"), ("Berrit Dale", "Storehouse captain", 24, 58, 48, 71, "defensive")],
            "House Highland": [("Bren Highland", "Border warden", 42, 65, 52, 83, "defensive"), ("Maela Highland", "Signal officer", 29, 62, 49, 76, "paranoid"), ("Torren Highland", "Militia captain", 31, 54, 58, 70, "aggressive"), ("Iona Highland", "Refuge coordinator", 25, 74, 36, 81, "honorable")],
        },
        "Tidefall": {
            "House Ver Meer": [("Marcellus Ver Meer", "Admiral-Lord", 82, 54, 76, 58, "defensive"), ("Isolde Ver Meer", "Harbor magistrate", 52, 63, 68, 64, "opportunistic"), ("Joren Ver Meer", "Fleet heir", 48, 51, 80, 47, "aggressive"), ("Maeric Ver Meer", "Shipyard master", 39, 57, 59, 70, "defensive")],
            "House Gross": [("Corvin Gross", "Harbor factor", 54, 42, 81, 39, "opportunistic"), ("Lessa Gross", "Customs broker", 43, 46, 72, 44, "opportunistic"), ("Tam Gross", "Warehouse prince", 37, 39, 74, 35, "paranoid"), ("Bryn Gross", "Fleet accountant", 31, 58, 50, 63, "defensive")],
            "House Adkison": [("Veyra Adkison", "Council advocate", 49, 52, 77, 50, "opportunistic"), ("Cassian Adkison", "Compact lawyer", 41, 47, 70, 48, "opportunistic"), ("Rellan Adkison", "Dockside envoy", 34, 43, 68, 41, "aggressive"), ("Sera Adkison", "Election broker", 38, 45, 75, 46, "opportunistic")],
            "House Van Cleave": [("Brannik Van Cleave", "Marine captain", 46, 56, 74, 66, "aggressive"), ("Alia Van Cleave", "Garrison inspector", 36, 61, 57, 74, "defensive"), ("Ren Van Cleave", "Boarding commander", 33, 49, 71, 53, "aggressive"), ("Clovis Van Cleave", "Armory keeper", 28, 58, 48, 68, "defensive")],
            "House Fish": [("Maren Fish", "Salt quay elder", 35, 68, 44, 73, "defensive"), ("Pell Fish", "Netfleet organizer", 27, 62, 51, 67, "opportunistic"), ("Una Fish", "Coastal scout", 25, 57, 58, 59, "defensive"), ("Hobb Fish", "Harbor quartermaster", 24, 55, 47, 70, "defensive")],
            "House Binx": [("Tallo Binx", "Chance broker", 31, 40, 83, 28, "opportunistic"), ("Nix Binx", "Rumor runner", 26, 36, 77, 31, "paranoid"), ("Pava Binx", "Dicehouse owner", 29, 44, 70, 35, "opportunistic"), ("Jessa Binx", "Smuggler contact", 24, 32, 74, 26, "aggressive")],
            "House Darkleaf": [("Sera Darkleaf", "Quiet agent", 40, 38, 79, 34, "paranoid"), ("Vane Darkleaf", "Cipher keeper", 34, 42, 73, 39, "defensive"), ("Liora Darkleaf", "Informant handler", 32, 35, 76, 33, "opportunistic"), ("Moth Darkleaf", "Shadow courier", 22, 31, 68, 28, "paranoid")],
        },
        "Dur Khadur": {
            "House Gross": [("Seran Gross", "Trade Prince", 79, 43, 84, 41, "opportunistic"), ("Orren Gross", "Council treasurer", 53, 45, 76, 46, "opportunistic"), ("Dalia Gross", "Caravan patron", 45, 54, 69, 58, "defensive"), ("Voss Gross", "Auction master", 38, 34, 72, 32, "opportunistic")],
            "House Adkison": [("Kevar Adkison", "Treaty engineer", 50, 48, 78, 44, "opportunistic"), ("Mina Adkison", "Contract judge", 42, 56, 66, 55, "defensive"), ("Arven Adkison", "Foreign broker", 39, 41, 74, 36, "opportunistic"), ("Leont Adkison", "Claims advocate", 30, 49, 63, 43, "paranoid")],
            "House Van Cleave": [("Bors Van Cleave", "Mercenary captain", 47, 46, 80, 52, "aggressive"), ("Kella Van Cleave", "Gate commander", 35, 58, 59, 68, "defensive"), ("Ravan Van Cleave", "Escort marshal", 33, 51, 70, 49, "aggressive"), ("Silas Van Cleave", "Arms buyer", 29, 44, 65, 38, "opportunistic")],
            "House Binx": [("Perrin Binx", "Market gambler", 30, 37, 82, 24, "opportunistic"), ("Zella Binx", "Information seller", 28, 34, 79, 29, "paranoid"), ("Odo Binx", "Courier fixer", 25, 45, 64, 41, "opportunistic"), ("Miri Binx", "Black-market caller", 23, 31, 73, 27, "aggressive")],
            "House Darkleaf": [("Nalia Darkleaf", "Covert negotiator", 44, 39, 80, 33, "paranoid"), ("Vale Darkleaf", "Pass watcher", 37, 42, 70, 40, "defensive"), ("Isern Darkleaf", "Silent partner", 35, 36, 77, 30, "opportunistic"), ("Nyra Darkleaf", "Ledger spy", 27, 33, 72, 31, "paranoid")],
            "House Dale": [("Heth Dale", "Grain investor", 34, 67, 48, 64, "defensive"), ("Mora Dale", "Water rights broker", 29, 62, 53, 59, "opportunistic"), ("Corra Dale", "Storehouse auditor", 26, 69, 41, 68, "honorable"), ("Tavin Dale", "Farmstead envoy", 24, 71, 38, 72, "honorable")],
        },
    }
    rows = []
    core_roles = ["Leader", "Heir", "Power Role", "Wildcard"]
    for faction, houses in specs.items():
        for house, members in houses.items():
            for index, (name, role, influence, morality, ambition, loyalty, bias) in enumerate(members):
                if index == 0:
                    age = 46
                elif index == 1:
                    age = 32
                elif index == 2:
                    age = 38
                else:
                    age = 27
                role_lower = role.lower()
                if "elder" in role_lower:
                    age = max(age, 43)
                if "cousin" in role_lower or "magistrate" in role_lower or "minister" in role_lower:
                    age += 4
                rows.append({
                    "name": name,
                    "faction": faction,
                    "house": house,
                    "coreRole": core_roles[index] if index < len(core_roles) else "Secondary",
                    "role": role,
                    "status": "Available for political action",
                    "age": str(age),
                    "race": "Human",
                    "influenceScore": influence,
                    "morality": morality,
                    "ambition": ambition,
                    "loyalty": loyalty,
                    "intelligence": max(35, min(90, int((influence + ambition + loyalty) / 3))),
                    "bias": bias,
                    "currentGoal": f"Advance {house}'s position in {faction}.",
                    "recentActions": [],
                })
    return rows


def _normalize_house_characters(prev_state, new_state):
    prev_rows = {
        (row.get("faction"), row.get("house"), row.get("name")): row
        for row in prev_state.get("house_characters", [])
        if row.get("name")
    }
    incoming_rows = {
        (row.get("faction"), row.get("house"), row.get("name")): row
        for row in new_state.get("house_characters", [])
        if row.get("name")
    }
    rows = []
    for seed in _default_house_characters():
        key = (seed["faction"], seed["house"], seed["name"])
        row = incoming_rows.get(key, prev_rows.get(key, seed))
        rows.append({
            "name": row.get("name", seed["name"]),
            "faction": row.get("faction", seed["faction"]),
            "house": row.get("house", seed["house"]),
            "coreRole": row.get("coreRole", seed.get("coreRole", "Secondary")),
            "role": row.get("role", seed["role"]),
            "status": row.get("status", seed["status"]),
            "age": seed["age"] if str(row.get("age", seed["age"])).strip().lower() in {"", "adult", "unknown"} else str(row.get("age", seed["age"])),
            "race": row.get("race", seed["race"]),
            "influenceScore": max(0, min(100, int(row.get("influenceScore", seed["influenceScore"])))),
            "morality": max(0, min(100, int(row.get("morality", seed["morality"])))),
            "ambition": max(0, min(100, int(row.get("ambition", seed["ambition"])))),
            "loyalty": max(0, min(100, int(row.get("loyalty", seed["loyalty"])))),
            "intelligence": max(0, min(100, int(row.get("intelligence", seed.get("intelligence", 50))))),
            "bias": row.get("bias", seed["bias"]),
            "currentGoal": row.get("currentGoal", seed["currentGoal"]),
            "recentActions": (row.get("recentActions") or [])[:5],
        })
    for key, row in incoming_rows.items():
        if key in {(item["faction"], item["house"], item["name"]) for item in rows}:
            continue
        rows.append(row)
    new_state["house_characters"] = rows[:120]


def _normalize_belief_currents(prev_state, new_state):
    prev_rows = {
        row.get("name"): row
        for row in prev_state.get("belief_currents", [])
        if row.get("name")
    }
    valid_stages = {"rumor", "pattern_recognition", "belief", "doctrine", "organization", "institution"}
    rows = []
    for row in new_state.get("belief_currents", []):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        prev = prev_rows.get(name, {})
        stage = row.get("stage") or prev.get("stage") or "rumor"
        if stage not in valid_stages:
            stage = "rumor"
        followers = max(0, int(row.get("followers", prev.get("followers", 0))))
        rows.append(
            {
                "name": name,
                "origin": row.get("origin", prev.get("origin", "")),
                "stage": stage,
                "regions": row.get("regions", prev.get("regions", []))[:8],
                "followers": followers,
                "interpretation": row.get("interpretation", prev.get("interpretation", "")),
            }
        )
    new_state["belief_currents"] = rows[:20]


def _normalize_religious_factions(prev_state, new_state):
    prev_rows = {
        row.get("name"): row
        for row in prev_state.get("religious_factions", [])
        if row.get("name")
    }
    rows = []
    for row in new_state.get("religious_factions", []):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        prev = prev_rows.get(name, {})
        rows.append(
            {
                "name": name,
                "origin_events": row.get("origin_events", prev.get("origin_events", []))[:6],
                "core_beliefs": row.get("core_beliefs", prev.get("core_beliefs", []))[:6],
                "doctrine_strength": max(0, min(100, int(row.get("doctrine_strength", prev.get("doctrine_strength", 40))))),
                "followers": max(0, int(row.get("followers", prev.get("followers", 0)))),
                "organization_level": max(0, min(100, int(row.get("organization_level", prev.get("organization_level", 30))))),
                "zeal": max(0, min(100, int(row.get("zeal", prev.get("zeal", 40))))),
                "stance_toward_seer": row.get("stance_toward_seer", prev.get("stance_toward_seer", "uncertain")),
            }
        )
    new_state["religious_factions"] = rows[:20]


def _normalize_character_updates(prev_state, new_state):
    prev_rows = {
        row.get("name"): row
        for row in prev_state.get("character_updates", [])
        if row.get("name")
    }
    rows = []
    for row in new_state.get("character_updates", []):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        prev = prev_rows.get(name, {})
        faction = row.get("faction") or prev.get("faction") or "Unknown"
        appearance = row.get("appearance") or prev.get("appearance") or "No detailed appearance recorded yet."
        influence_score = max(0, min(100, int(row.get("influenceScore", prev.get("influenceScore", 35)))))
        influence_tier = max(1, min(4, int(row.get("influenceTier", prev.get("influenceTier", 3)))))
        intelligence = max(0, min(100, int(row.get("intelligence", prev.get("intelligence", 50)))))
        intelligence_tier = max(1, min(5, int(row.get("intelligenceTier", prev.get("intelligenceTier", 3)))))
        bias = row.get("bias") or prev.get("bias") or "defensive"
        if bias not in {"aggressive", "defensive", "paranoid", "opportunistic", "honorable"}:
            bias = "defensive"
        prompt = row.get("portrait_prompt") or prev.get("portrait_prompt") or (
            f"Dark fantasy portrait of {name}, {faction}, lore accurate Aeloria aesthetic, no text, no watermark."
        )
        rows.append(
            {
                "name": name,
                "faction": faction,
                "status": row.get("status") or prev.get("status") or "No current status recorded.",
                "dynasty": row.get("dynasty") or prev.get("dynasty") or "Unknown Dynasty",
                "date_of_birth": row.get("date_of_birth") or prev.get("date_of_birth") or "Unknown",
                "age": row.get("age") or prev.get("age") or "Unknown",
                "species": row.get("species") or prev.get("species") or row.get("race") or prev.get("race") or "Unknown",
                "culture": row.get("culture") or prev.get("culture") or faction,
                "age_stage": row.get("age_stage") or prev.get("age_stage") or "Unknown",
                "race": row.get("race") or prev.get("race") or "Unknown",
                "height": row.get("height") or prev.get("height") or "Unknown",
                "weight": row.get("weight") or prev.get("weight") or "Unknown",
                "appearance": appearance,
                "morality": max(0, min(100, int(row.get("morality", prev.get("morality", 50))))),
                "ambition": max(0, min(100, int(row.get("ambition", prev.get("ambition", 50))))),
                "loyalty": max(0, min(100, int(row.get("loyalty", prev.get("loyalty", 50))))),
                "bias": bias,
                "intelligence": intelligence,
                "influenceScore": influence_score,
                "influenceTier": influence_tier,
                "intelligenceTier": intelligence_tier,
                "recentActions": (row.get("recentActions") or prev.get("recentActions") or [])[:6],
                "portrait_prompt": prompt[:220],
                "portrait_image": row.get("portrait_image") or prev.get("portrait_image") or "",
            }
        )
    new_state["character_updates"] = rows[:6]


def _normalize_population_state(prev_state, new_state):
    seed_rows = [
        ("Twin Cities", "Humans", "Twin Cities", 160000, 180000, 0.00025, 86, 22, 4),
        ("Tidefall", "Humans", "Tidefall", 160000, 185000, 0.00028, 82, 32, 20),
        ("Faerwood", "Dread Elves", "Shadow Court", 30000, 42000, 0.00003, 74, 38, 0),
        ("Glenhaven", "Glenhaven Elves", "Wildwood Elves", 35000, 52000, 0.00005, 88, 18, 0),
        ("Lostfeld", "Dwarves", "Lostfeld Clans", 65000, 85000, 0.00008, 81, 24, 0),
        ("Gilgeth and Groth", "Orcs", "Mountain Orcs", 100000, 125000, 0.00022, 72, 43, 0),
        ("Rock Plains", "Goblins", "Vilefin", 215000, 230000, 0.00055, 63, 68, 0),
        ("Dreadwind Isles", "Humans", "Dreadwind Pirates", 45000, 65000, 0.00018, 67, 52, 16),
        ("Dur Khadur", "Humans", "Dur Khadur", 115000, 155000, 0.00024, 79, 36, 8),
        ("Stonebreak", "Druids", "Monastery of Druids", 5500, 9000, 0.00002, 91, 12, 0),
        ("Gloomspire", "Gnomes", "Gloomspire Syndicate", 8500, 14000, 0.00012, 76, 28, 0),
        ("Dragonscar Peaks", "Ice Dragons", "Dragon Clans", 12, 20, 0.0, 94, 9, 0),
    ]
    prev_rows = {
        row.get("region"): row
        for row in prev_state.get("population_state", [])
        if row.get("region")
    }
    incoming = {
        row.get("region"): row
        for row in new_state.get("population_state", [])
        if row.get("region")
    }

    rows = []
    for region, species, culture, population, capacity, growth, health, pressure, naval in seed_rows:
        prev = prev_rows.get(region, {})
        row = incoming.get(region, prev)
        base_population = int(prev.get("population", population))
        next_population = int(row.get("population", base_population))
        if region != "Dragonscar Peaks":
            max_daily_shift = max(20, int(max(base_population, 1) * 0.01))
            next_population = max(base_population - max_daily_shift, min(base_population + max_daily_shift, next_population))

        capacity_value = max(0, int(row.get("capacity", prev.get("capacity", capacity))))
        pressure_value = max(0, min(100, int(row.get("pressure", prev.get("pressure", pressure)))))
        health_value = max(0, min(100, int(row.get("health", prev.get("health", health)))))
        naval_value = max(0, min(100, int(row.get("navalAllocation", prev.get("navalAllocation", naval)))))
        active_military = int(row.get("activeMilitary", prev.get("activeMilitary", max(0, int(next_population * 0.035)))))
        if region == "Tidefall":
            active_military = int(row.get("activeMilitary", prev.get("activeMilitary", max(0, int(next_population * 0.04)))))
        if region == "Dragonscar Peaks":
            active_military = next_population

        rows.append(
            {
                "region": region,
                "species": row.get("species") or prev.get("species") or species,
                "culture": row.get("culture") or prev.get("culture") or culture,
                "population": max(0, next_population),
                "growthRate": float(row.get("growthRate", prev.get("growthRate", growth))),
                "capacity": capacity_value,
                "health": health_value,
                "pressure": pressure_value,
                "activeMilitary": max(0, active_military),
                "navalAllocation": naval_value,
                "notes": row.get("notes") or prev.get("notes") or "Population pressure is being tracked daily.",
            }
        )

    extra_regions = [key for key in incoming.keys() if key not in {row[0] for row in seed_rows}]
    for region in extra_regions[:8]:
        row = incoming[region]
        rows.append(
            {
                "region": region,
                "species": row.get("species") or "Unknown",
                "culture": row.get("culture") or row.get("species") or "Unknown",
                "population": max(0, int(row.get("population", 0))),
                "growthRate": float(row.get("growthRate", 0)),
                "capacity": max(0, int(row.get("capacity", 0))),
                "health": max(0, min(100, int(row.get("health", 50)))),
                "pressure": max(0, min(100, int(row.get("pressure", 50)))),
                "activeMilitary": max(0, int(row.get("activeMilitary", 0))),
                "navalAllocation": max(0, min(100, int(row.get("navalAllocation", 0)))),
                "notes": row.get("notes") or "New population center recorded by the simulation.",
            }
        )

    new_state["population_state"] = rows[:20]


def _normalize_state(prev_state, new_state):
    prev_state = prev_state or {}
    prev_events = {
        event.get("name"): event
        for event in prev_state.get("active_events", [])
        if event.get("name")
    }

    active_events = []
    for event in new_state.get("active_events", []):
        normalized = _normalize_event(event, prev_events.get(event.get("name")))
        if normalized:
            active_events.append(normalized)

    active_events.sort(key=lambda item: item.get("severity", 0), reverse=True)
    new_state["active_events"] = active_events[:8]

    top_event = new_state["active_events"][0] if new_state["active_events"] else {}

    primary_event = new_state.get("primary_event") or {}
    new_state["primary_event"] = {
        "name": primary_event.get("name") or top_event.get("name") or "Shifting Pressures",
        "summary": primary_event.get("summary") or top_event.get("summary") or new_state.get("major_event", ""),
        "severity": int(primary_event.get("severity", top_event.get("severity", 10))),
        "stage": primary_event.get("stage") or top_event.get("stage") or "emerging",
        "trend": primary_event.get("trend") or top_event.get("trend") or "stable",
        "involved": primary_event.get("involved") or top_event.get("involved") or [],
    }

    new_state["major_event"] = new_state.get("major_event") or new_state["primary_event"]["summary"]

    if not new_state.get("supporting_events"):
        new_state["supporting_events"] = [
            {
                "name": event.get("name", ""),
                "summary": event.get("summary", ""),
                "severity": event.get("severity", 1),
                "stage": event.get("stage", "emerging"),
                "trend": event.get("trend", "stable"),
                "involved": event.get("involved", []),
            }
            for event in new_state["active_events"][1:5]
        ]

    _normalize_faction_resources(prev_state, new_state)
    _normalize_population_state(prev_state, new_state)
    _normalize_relationships(prev_state, new_state)
    _normalize_trade_routes(new_state)
    _normalize_faction_identities(new_state)
    _normalize_region_control(new_state)
    _normalize_faction_knowledge(new_state)
    _normalize_remembered_events(prev_state, new_state)
    _normalize_seer_state(prev_state, new_state)
    new_state["seer_journey"] = _infer_seer_journey(new_state)
    _normalize_seer_journey(prev_state, new_state)
    _normalize_ruler_states(prev_state, new_state)
    _normalize_leadership_state(prev_state, new_state)
    _normalize_house_characters(prev_state, new_state)
    _normalize_belief_currents(prev_state, new_state)
    _normalize_religious_factions(prev_state, new_state)
    _normalize_character_updates(prev_state, new_state)

    new_state.setdefault("faction_actions", [])
    new_state.setdefault("recent_events", [])
    new_state.setdefault("active_tensions", [])
    new_state.setdefault("character_updates", [])
    new_state.setdefault("faction_morale", [])
    new_state.setdefault("faction_power", [])
    new_state.setdefault("faction_resources", [])
    new_state.setdefault("population_state", [])
    new_state.setdefault("trade_routes", [])
    new_state.setdefault("faction_identities", [])
    new_state.setdefault("region_control", [])
    new_state.setdefault("relationships", [])
    new_state.setdefault("faction_knowledge", [])
    new_state.setdefault("remembered_events", [])
    new_state.setdefault("seer_journey", {})
    new_state.setdefault("seer_state", {})
    new_state.setdefault("ruler_states", [])
    new_state.setdefault("leadership_state", [])
    new_state.setdefault("house_characters", [])
    new_state.setdefault("belief_currents", [])
    new_state.setdefault("religious_factions", [])
    new_state.setdefault("whispers", [])
    new_state.setdefault("weather_and_omens", [])
    new_state.setdefault("absorbed_lore", [])

    return new_state


def _call_claude(prev_state, pending_lore):
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    pending_text = ""
    if pending_lore:
        entries = "\n---\n".join(item.get("text", "") for item in pending_lore)
        pending_text = f"\n\nGOD LORE INJECTED THIS TICK:\n{entries}"

    if prev_state:
        user_content = (
            f"Previous world state:\n{json.dumps(prev_state, indent=2)}"
            f"{pending_text}\n\n"
            "Simulate the next day.\n"
            "Carry forward persistent events.\n"
            "Update each active event's duration, severity, stage, and trend.\n"
            "Each faction must take one primary action.\n"
            "Every faction action must have a believable resource cost.\n"
            "Update faction_resources gradually, and reflect trade gains, upkeep losses, and conflict pressure.\n"
            "Update population_state daily: population, growthRate, capacity, health, pressure, activeMilitary, and navalAllocation must shift gradually from biology, culture, resources, war, migration, and regional stress.\n"
            "Update leadership_state daily: rulers, reign history, dynasties, succession risks, prestige changes, and notable reign events must persist chronologically.\n"
            "Update house_characters lightly: they are the active political bench for each noble house and can become generals, advisors, rivals, heirs, plotters, or major character_updates when events elevate them.\n"
            "Track relationships with trust and hostility, and let those values shape choices.\n"
            "Model geography, region control, adjacency, distance, and delayed information spread.\n"
            "Track what factions know, what they only suspect, and what they misinterpret.\n"
            "Persist remembered events and let them influence present decisions.\n"
            "Model the Seer as a physical traveler with a location, destination, travel delay, and messenger failure risk.\n"
            "Update the Seer's evolving state as a limited, interpretive witness.\n"
            "Model ruler archetypes and their delayed responses to Seer messages.\n"
            "Allow belief currents and religious factions to emerge organically from rumor, pattern recognition, crisis, and interpretation.\n"
            "Allow religious splintering, rivalry, suppression, and conflict to build slowly into skirmish or war.\n"
            "Only create major crises after sustained pressure over multiple ticks.\n"
            "Output both the deep simulation layer (active_events, faction_actions) and the surfaced layer "
            "(primary_event, supporting_events, recent_events, active_tensions, whispers, weather_and_omens), "
            "plus faction_resources, population_state, leadership_state, house_characters, trade_routes, faction_identities, region_control, relationships with trust/hostility, "
            "faction_knowledge, remembered_events, seer_journey, seer_state, ruler_states, belief_currents, and religious_factions."
        )
    else:
        user_content = (
            "Generate the initial world state for tick 0, representing the first simulated day. "
            "Seed the world with several ongoing tensions already in motion rather than isolated incidents. "
            "The world is in a state of uneasy tension across all factions. "
            "Initialize believable resource baselines, population_state baselines, leadership_state baselines, house_characters baselines, active trade relationships, faction identities, region control, "
            "relationship trust/hostility, faction knowledge limits, remembered events, an initial Seer state, ruler archetypes, "
            "and the earliest seeds of belief and interpretation."
            f"{pending_text}"
        )

    response = client.messages.create(
        model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        tools=[WORLD_STATE_TOOL],
        tool_choice={"type": "tool", "name": "update_world_state"},
        messages=[{"role": "user", "content": user_content}],
    )

    result = _normalize_state(prev_state, response.content[0].input)
    result["real_timestamp"] = datetime.now().isoformat()
    return result


def _generate_narrative_synopsis(state):
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    try:
        chronicles = []
        if HISTORY_DIR.exists():
            for file in sorted(HISTORY_DIR.glob("chronicle_*.txt"))[-5:]:
                chronicles.append(file.read_text(encoding="utf-8"))

        chronicle_context = "\n\n---\n\n".join(chronicles) if chronicles else ""
        current_tick = state.get("tick", 0)
        world_date = state.get("world_date", "")
        tensions = state.get("active_tensions", [])
        tension_text = "\n".join(f"- {item['factions']}: {item['description']}" for item in tensions)

        prompt = f"""You are the narrator of Aeloria, a living fantasy world now in tick {current_tick} ({world_date}).

RECENT CHRONICLE ENTRIES:
{chronicle_context}

CURRENT ACTIVE TENSIONS:
{tension_text}

Write a 2-3 paragraph narrative synopsis that captures the main story arc of Aeloria as it stands right now.
This is the story so far: the central thread a reader needs to understand what this world is about and where it is heading.

Do not list every event. Find the narrative spine: the core conflict, the key players, the question the world is currently asking.
Write in a dark, literary, present-tense voice.
Use specific character and place names. End on the tension that defines this moment in history."""

        response = client.messages.create(
            model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        SYNOPSIS_FILE.write_text(text, encoding="utf-8")
        logger.info(f"Narrative synopsis updated for tick {current_tick}")
        return text
    except Exception as exc:
        logger.error(f"Narrative synopsis generation failed: {exc}")
        return ""


def _generate_chronicle(state):
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    try:
        response = client.messages.create(
            model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
            max_tokens=1200,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "You are the narrator of Aeloria. Write 2-3 evocative paragraphs describing what happened "
                        "this day in the world. Write in past tense, literary prose, as if narrating an epic fantasy novel. "
                        f"Draw from these events: {json.dumps(state, indent=2)}. "
                        "Do not use bullet points. Be specific with character names and place names. "
                        "Write in a dark, cinematic tone."
                    ),
                }
            ],
        )
        text = response.content[0].text
        HISTORY_DIR.mkdir(exist_ok=True)
        chronicle_path = HISTORY_DIR / f"chronicle_{state['tick']}.txt"
        chronicle_path.write_text(text, encoding="utf-8")
        logger.info(f"Chronicle written for tick {state['tick']}")
        return text
    except Exception as exc:
        logger.error(f"Chronicle generation failed: {exc}")
        return ""


def _generate_tick_voice(chronicle_text, tick_num):
    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
    if not api_key or not chronicle_text:
        return

    import re

    import requests

    paragraphs = [paragraph.strip() for paragraph in chronicle_text.split("\n\n") if paragraph.strip()]
    narration = paragraphs[0] if paragraphs else chronicle_text[:500]
    narration = re.sub(r"\*+", "", narration)

    try:
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": narration,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.15,
                    "similarity_boost": 0.85,
                    "style": 0.7,
                    "use_speaker_boost": True,
                },
            },
            timeout=60,
        )
        if response.status_code == 200:
            audio_path = AUDIO_DIR / f"tick_{tick_num}.mp3"
            audio_path.write_bytes(response.content)
            logger.info(f"Voice narration saved for tick {tick_num}")
        else:
            logger.warning(f"ElevenLabs voice failed: {response.status_code}")
    except Exception as exc:
        logger.error(f"Voice generation failed: {exc}")


def run_tick():
    with _lock:
        logger.info("Running world tick...")
        try:
            prev_state = _load_world_state()
            pending_lore = _load_pending_lore()

            new_state = _call_claude(prev_state, pending_lore)
            _ensure_character_portraits(new_state)
            _ensure_codex_images(new_state)
            _save_world_state(new_state)
            _save_history(new_state)
            _clear_pending_lore()

            send_tick_notification(new_state)
            logger.info(f"Tick {new_state['tick']} complete - {new_state.get('world_date')}")

            chronicle = _generate_chronicle(new_state)
            if chronicle:
                new_state["chronicle"] = chronicle
                _save_world_state(new_state)

            _generate_tick_voice(chronicle, new_state["tick"])
            _generate_narrative_synopsis(new_state)
            return new_state
        except Exception as exc:
            logger.error(f"Tick failed: {exc}", exc_info=True)
            raise


def _run_monday_story():
    logger.info("Generating Monday audio story...")
    try:
        state = _load_world_state()
        if state:
            path = generate_weekly_story(state)
            logger.info(f"Monday story saved to {path}")
        else:
            logger.warning("No world state yet - skipping Monday story.")
    except Exception as exc:
        logger.error(f"Monday story failed: {exc}", exc_info=True)


def start_scheduler():
    tick_hours = int(os.getenv("TICK_INTERVAL_HOURS", "24"))
    _scheduler.add_job(run_tick, IntervalTrigger(hours=tick_hours), id="world_tick", replace_existing=True)
    _scheduler.add_job(
        _run_monday_story,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="monday_story",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Scheduler started - tick every {tick_hours}h, story every Monday 9am UTC.")

    if not WORLD_STATE_FILE.exists():
        logger.info("No world state found - generating initial state...")
        try:
            run_tick()
        except Exception as exc:
            logger.error(f"Initial world generation failed: {exc}", exc_info=True)


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
