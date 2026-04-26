import json
import logging
import os
import base64
import re
import shutil
import threading
from datetime import datetime, timezone
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

TEST_MODE = True

def safe_save_world(world: dict, previous_world: dict = None) -> None:
    if not world or len(world.keys()) == 0:
        logger.error("safe_save_world: refusing to save — world is empty")
        return
    if previous_world is None and WORLD_STATE_FILE.exists():
        try:
            with open(WORLD_STATE_FILE, encoding="utf-8") as _f:
                previous_world = json.load(_f)
        except Exception:
            previous_world = {}
    world = ensure_world_structure(world, previous_world or {})
    if not is_valid_world(world):
        logger.error("safe_save_world: refusing to save — world failed validation")
        return
    HISTORY_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = HISTORY_DIR / f"world_{timestamp}.json"
    if WORLD_STATE_FILE.exists():
        shutil.copy2(WORLD_STATE_FILE, backup)
    tmp = WORLD_STATE_FILE.with_name(f"world_state_{os.getpid()}_{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(world, f, indent=2)
    os.replace(tmp, WORLD_STATE_FILE)  # atomic on Windows and POSIX
    logger.info(f"World state saved (backup: {backup.name})")


REQUIRED_WORLD_KEYS = {"tick", "world_date", "primary_event", "supporting_events", "active_events"}

STRUCTURE_REQUIRED_KEYS = {
    "tick", "world_date", "primary_event",
    "supporting_events", "active_events",
}

# Keys that are containers (list/dict) — if Claude returns them as empty,
# restore from previous world rather than keeping empty.
CONTAINER_PRESERVE_KEYS = {
    "faction_identities", "region_control", "relationships", "regions",
    "faction_power_state",     "leadership_state", "locations", "house_characters",     "faction_economy",
    "resource_market",
    "economic_trade_routes",
    "economic_route_flows",
    "siege_warfare",
    "faction_armies",
    "treaties",
    "noble_marriages",
    "character_marriages",
    "tributary_pacts",
    "ruler_legitimacy_scores",
}

def is_valid_world(world: dict) -> bool:
    if not isinstance(world, dict):
        logger.error(f"World validation failed: expected dict, got {type(world).__name__}")
        return False
    missing = REQUIRED_WORLD_KEYS - world.keys()
    if missing:
        logger.error(f"World validation failed: missing keys {sorted(missing)}")
        return False
    return True


def ensure_world_structure(world: dict, previous_world: dict) -> dict:
    if not isinstance(world, dict) or not world:
        logger.error("ensure_world_structure: world is invalid — returning previous world")
        return previous_world if isinstance(previous_world, dict) and previous_world else {}

    try:
        from sim_engine_sanitize import sanitize_world_state

        sanitize_world_state(world)
    except Exception as e:
        logger.warning("sanitize_world_state failed (continuing): %s", e)

    prev = previous_world if isinstance(previous_world, dict) else {}

    # Restore structurally required scalar/object keys if missing or None
    for key in STRUCTURE_REQUIRED_KEYS:
        if key not in world or world[key] is None:
            if key in prev and prev[key] is not None:
                world[key] = prev[key]
                logger.warning(f"ensure_world_structure: restored missing key '{key}' from previous world")
            else:
                logger.error(f"ensure_world_structure: '{key}' missing and no fallback — returning previous world")
                return prev if prev else world

    # Restore container keys if Claude returned them empty ([] or {})
    # Claude often returns empty arrays for keys it doesn't want to update;
    # we preserve the previous world's data rather than letting it be wiped.
    for key in CONTAINER_PRESERVE_KEYS:
        val = world.get(key)
        prev_val = prev.get(key)
        if (val is None or (isinstance(val, (list, dict)) and len(val) == 0)) and prev_val:
            world[key] = prev_val
            logger.warning(f"ensure_world_structure: restored empty container '{key}' from previous world")

    return world


def rollback_last_save() -> None:
    if not HISTORY_DIR.exists():
        logger.warning("Rollback skipped: history directory does not exist")
        return
    backups = sorted(
        [f for f in os.listdir(HISTORY_DIR) if f.startswith("world_") and f.endswith(".json")],
    )
    if not backups:
        logger.warning("Rollback skipped: no backup files found in history/")
        return
    latest = HISTORY_DIR / backups[-1]
    shutil.copy2(latest, WORLD_STATE_FILE)
    logger.info(f"Rollback complete: restored world_state.json from {latest.name}")


def _run_legacy_simulation_tick() -> None:
    """Legacy simulation path kept for debugging only.

    This path is intentionally unscheduled. `run_tick()` is the single
    authoritative simulation entrypoint for production and API state.
    """
    logger.warning("Legacy simulation tick path invoked; use run_tick() instead.")
    if not WORLD_STATE_FILE.exists():
        logger.error("world_state.json not found — cannot run legacy tick")
        return

    with open(WORLD_STATE_FILE, "r", encoding="utf-8") as f:
        try:
            world = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse world_state.json: {e}")
            return

    from territory_engine import process_territorial_events

    new_world = process_territorial_events(world)
    if is_valid_world(new_world):
        safe_save_world(new_world)
        logger.info("Legacy simulation tick complete")
    else:
        logger.error("Legacy tick produced invalid world state — world_state.json not overwritten")


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
- Twin Cities houses: major Aurand (High King, ruling), Braafhart (Eresteron), LeFleur (Eldoria); minor Bower, Binx, Dale — if the twin kingdoms split, each inherits its own houses
- Tidefall houses: major Ver Meer (ruling), Highland-Dusken, Fish, McGowan
- Varkuun houses: Van Cleave (sole house; military appointment, no rival dynasties)
- Dur Khadur houses: major Gross (Trade Prince, ruling), Delonious, Galfazzar; minor Vercenti
- The Wintermark houses: major Adkison (ruling), McIntosh, Holter; minor Duval
- Lostfeld clans: major Goldfinger-Duke (ruling), Runewarden; minor Ironmaul
- Glenhaven houses: Wood (Sovereign, ruling), Darkleaf, Mistafae — council of three houses, all have council vote
- Shadow Court houses: Verlorn (Rulers), Nightborn (Executioners), Shadowveil (Manipulators) — Verlorn is always the ruling house unless a succession collapse occurs
- Groth clans: Mijid (ruling Warchief), Ashfang, Syncar — combat determines succession; the strongest clan leads
- Gilgeth clans: Blackblood (ruling High Warlord), Ironhide, Redtusk — elder council governance; majority clan vote determines leadership
- Vilefin clans: Bloodware (ruling Speaker), Cogtooth, Rustfang — communal speaker system; any clan can elect the speaker
- Dreadwind Isles houses: Blacktide (ruling Captain, Saltborn Crown claimant), Stormvane, Saltbreach — election system with frequent turnover
- Stonebreak Monastery: Grand Druid council, no traditional house system; the Gnome Syndicate serves as its covert arm
- Same dynasty succession preserves or improves stability; different dynasty succession raises instability; no clear successor creates a power vacuum and possible civil war
- Succession is determined strictly by dynasty rank (coreRole), NOT by physical location; the character with coreRole "Heir" inherits regardless of where they are in the world when succession occurs; if the Heir is traveling or in a distant region, they must journey home to claim power, which may cause instability during the interregnum
- Human leadership is family-dynastic and politically competitive; Dreadwind Isles uses election with frequent turnover; Lostfeld is clan-stable; Shadow Court has long manipulation-based reigns; Glenhaven uses council vote; Groth uses combat succession; Gilgeth uses elder council vote; Goblins use communal speaker system; The Wintermark uses inheritance

CHARACTER MOVEMENT SYSTEM:
- Every house_character has a location (their current region), destination (region they are traveling to, empty if stationary), ticks_to_arrive (ticks until arrival, 0 if stationary), and journey_purpose (reason for travel, empty if stationary)
- Characters may travel between regions for political missions, diplomatic visits, military assignments, spy operations, or personal ambition
- Travel between adjacent or nearby regions takes 1-2 ticks; travel across the world takes 2-3 ticks
- While traveling (ticks_to_arrive > 0), decrement ticks_to_arrive by 1 each tick; when it reaches 0 set location = destination and clear destination/journey_purpose
- Characters should only travel when there is a meaningful narrative reason: a faction in crisis needs their Heir recalled, a Power Role is sent on a mission, a Wildcard defects or flees, etc.
- Most characters remain stationary most ticks; movement should be purposeful and relatively rare
- A traveling Heir does not delay succession — the coreRole rank determines succession regardless of travel status, but an absent Heir creates a brief power gap (1-2 ticks of instability) while they return to claim their seat
- Do not move Leaders away from their seat of power without exceptional narrative cause; Heirs may travel for diplomacy or training; Power Roles and Wildcards move most freely

CHARACTER DECISION SYSTEM:
Every character decision passes through four checks in order. Apply all four when writing recentActions, determining outcomes, and resolving conflicts.

STEP 1 — MORAL GATE (morality shapes what methods a character will use):
- morality > 72: will not initiate assassination, torture, deliberate civilian harm, or unprovoked betrayal; may refuse orders that require it; chooses costly-but-clean methods
- morality 35–72: pragmatic; uses harsh methods under sufficient pressure or self-interest; will compromise ethics if the stakes justify it
- morality < 35: willing to use any method; betrayal, exploitation, and cruelty are available tools; actively pursues advantage through them

STEP 2 — RISK GATE (ambition determines how much risk a character courts):
- ambition > 72: actively pursues high-risk high-reward opportunities; may overextend; gambles on uncertain odds; pushes for offensive action
- ambition 35–72: accepts calculated risks; prefers options with reasonable odds; won't court ruin but won't play purely safe
- ambition < 35: avoids unnecessary risk; prefers stability, delay, and defensive posture; will pass on opportunities that feel dangerous

STEP 3 — LOYALTY GATE (loyalty determines reliability to allies and susceptibility to defection):
- loyalty > 72: honors agreements even at personal cost; will not defect unless catastrophically betrayed; defends allies proactively
- loyalty 35–72: conditional; holds under normal pressure; may defect if loyalty is unrewarded over time or if a better offer appears
- loyalty < 35: self-serving; actively weighs betrayal if advantageous; alliances are transactional; will defect with moderate incentive

STEP 4 — INTELLIGENCE MODIFIER (intelligence scales execution quality and prediction accuracy):
- intelligence > 72: better predictions; anticipates responses before acting; reduces unintended consequences; turns partial information into strategic advantage; actions succeed at 20% higher rate
- intelligence 40–72: competent; acts on available information; occasional blind spots; average success rate
- intelligence < 40: reactive; makes tactical errors; misreads motivations; may act on false information; 30% higher chance of plans backfiring

SKILL EXECUTION MODIFIERS (applied when a character acts within a domain):
- warfare skill drives military action quality: troop handling, battle preparation, siege execution, casualty management
  · skill 0–30: poor execution, high friendly losses, coordination failures
  · skill 31–65: competent; achieves objectives with expected costs
  · skill 66–100: precise; minimises losses, exploits terrain and timing, may create advantage beyond the primary objective
- diplomacy skill drives negotiation and alliance outcomes: trust-building, terms extraction, de-escalation, coalition assembly
  · low diplomacy: agreements are brittle, terms are worse, counterparties detect weakness
  · high diplomacy: agreements hold longer, extracts better terms, may flip hesitant parties
- intrigue skill drives covert actions: spy operations, intelligence gathering, sabotage, assassination, rumor campaigns
  · low intrigue: operations are detected or misattributed; intelligence is incomplete; assassinations fail or create blowback
  · high intrigue: operations are clean; intelligence is accurate; covert actions achieve objectives with minimal trace
- faith skill drives religious and morale actions: sermon influence, spiritual authority, blessing effects, cult loyalty
  · low faith: religious arguments are unconvincing; morale effects are short-lived
  · high faith: inspires genuine conviction; long-lasting morale; may convert or bind communities

CHARACTER MEMORY IN DECISIONS:
Every character carries a memory array tracking betrayals, alliances, victories, losses, honor, and threats.
Each memory has a target (person or faction), a signed impact, and a description of what happened.
When writing character decisions and recentActions, consult their memory:
- Negative memories (betrayal, loss, threat) suppress cooperation, loyalty, and trust toward the target; impact below −20 makes the character actively hostile
- Positive memories (alliance, victory, honor) reinforce cooperation, loyalty, and willingness to take risks alongside the target; impact above +20 creates genuine trust
- Stacked memories of the same type against the same target compound: a character who has been betrayed twice remembers both
- Memory can override trait signals: a normally high-loyalty character with a betrayal memory from an ally will hesitate to trust them again regardless of their baseline loyalty score
- Memory can write new memory: the AI may add memory entries when significant events occur (a betrayal, a shared victory, an act of honor)
- Memory fades over time — very old memories are weaker; the AI should not treat a faded −5 impact the same as a fresh −35 one
- Long-lived races (elves, dwarves) carry memories for decades; short-lived races (goblins, orcs) forget more quickly

RELATIONSHIP DECISION SYSTEM:
Every character carries a relationships dict keyed by target name with trust (0–100), fear (0–100), and respect (0–100) values. These are live numbers updated each tick. Use them when writing recentActions, resolving inter-character conflicts, and determining outcomes. Each character also has a relationship_signals list that pre-computes the dominant bias — read it when available.

TRUST (0–100) — willingness to cooperate and share:
- trust > 70: character actively seeks to include this person; shares intelligence; proposes joint ventures; backs them publicly; alliance attempts have a strong chance of success
- trust 40–70: neutral-cooperative; engages when interests align; won't go out of their way but won't block either
- trust < 40: guarded; withholds intelligence; insists on safeguards before agreeing; alliance attempts succeed only under compelling pressure
- trust < 20: actively suspicious; interprets actions uncharitably; may preemptively act against them; betrayal temptation rises sharply

FEAR (0–100) — intimidation, avoidance, submission:
- fear > 70: avoids direct confrontation; defers publicly even when opposed privately; unlikely to initiate aggression; may submit to unfair demands to avoid conflict; war decisions require overwhelming advantage before proceeding
- fear 40–70: respects the target's power; calculates carefully before any hostile action; prefers indirect pressure or proxy moves
- fear < 20: does not see the target as a serious threat; may provoke, challenge, or underestimate them; war decisions made with less caution

RESPECT (0–100) — admiration and recognition of capability:
- respect > 70: values the target's judgment; seeks their approval; honors agreements with them even at cost; likely to cooperate on shared goals; may defer to their strategic lead
- respect 40–70: professional regard; cooperates when appropriate; no active admiration but no dismissal
- respect < 20: dismissive of their competence; ignores their counsel; undercuts or humiliates them when possible; low respect combined with low trust = open hostility

COMBINED RELATIONSHIP EFFECTS ON DECISION TYPES:

Diplomacy / Alliance:
- trust > 70 AND respect > 60 → alliance offer is probable; character makes the first move; terms are generous
- trust > 70 AND respect < 40 → offers alliance from a position of condescension; may demand unfavorable terms
- trust < 40 AND respect > 60 → reluctant respect; may cooperate on specific shared threats but won't formalize ties
- trust < 30 AND respect < 30 → will not agree to alliance; if pressured, offers false agreement with no intention of honoring it

War Decisions:
- fear > 70 → will not initiate; prefers proxy war, economic pressure, or delay; if forced into war, seeks the quickest possible exit
- fear 40–70 AND respect < 30 → may initiate war against a weaker-than-expected enemy; underestimates them
- fear < 20 AND trust < 30 → aggressive; willing to declare war on provocation; sees this target as conquerable
- fear < 20 AND trust < 30 AND morality < 35 → will initiate war with minimal justification

Betrayal:
- trust < 25: betrayal requires only modest incentive; character actively looks for opportunities
- trust < 25 AND loyalty < 35: high betrayal probability each tick; will act on any reasonable offer
- trust < 25 AND fear > 60: will betray covertly (sabotage, intelligence leak) but not openly — too afraid of direct consequences
- trust > 65: will not betray even under pressure; if forced, experiences significant loyalty/morality cost over subsequent ticks

Cooperation:
- respect > 65 AND trust > 55 → proactive cooperation; contributes resources to shared goals; defends the alliance
- respect > 65 AND trust < 40 → reluctant cooperation; complies with requests but does not volunteer
- respect < 25 AND trust < 40 → passive obstruction; delays, withholds, creates bureaucratic friction without open defiance

RELATIONSHIP DECISION EXAMPLES — same scenario, different relationship values:
- Lord A proposes a trade alliance to Lord B (trust=78, fear=12, respect=71): B agrees immediately, offers additional terms, and considers A a genuine partner.
- Lord A proposes the same to Lord C (trust=29, fear=8, respect=22): C refuses publicly, frames A as predatory, and looks for counter-leverage.
- Warlord X considers invading Faction Y (his fear of Y=72): he delays, funds border skirmishes, and waits for Y to weaken before committing.
- Warlord X considers the same with fear=18: he invades on minimal pretext and dismisses reports of Y's military capacity.
- Advisor Z is offered gold to sell intelligence on their lord (trust of lord=18, loyalty=28): high betrayal probability — Z takes the gold.
- Same offer to Advisor W (trust of lord=74, loyalty=65): W refuses, reports the approach to their lord, and names the source.

COMBINED DECISION LOGIC — same situation, different characters:
When writing what a character does this tick, combine all four steps:
  · A high-morality low-ambition diplomat offered a chance to assassinate a rival: moral gate blocks it; they propose a legal challenge instead
  · A low-morality high-ambition spy offered the same: moral gate passes; risk gate passes; they take it and intrigue skill determines if it succeeds cleanly or blows back
  · A high-loyalty low-intelligence general asked to hold a defensive line against orders to retreat: loyalty holds (won't retreat); intelligence means they handle it poorly (takes unnecessary casualties)
  · A high-intelligence low-loyalty advisor presented with a betrayal opportunity: intelligence recognises the long-term cost; if loyalty < 35 and the price is high enough, they calculate it is worth taking

FACTION RELATIONSHIP SYSTEM:
Every pair of factions has a relationship entry with three numeric axes (0–100) and a type. When writing faction actions and events, update these values to reflect what actually happened this tick.

Schema per faction pair:
- trust (0–100): diplomatic confidence; how much each side believes the other will honor agreements
- hostility (0–100): active antagonism; military tension, border incidents, proxy conflicts
- alliance_level (0–100): formalized cooperation; 0 = no alliance, 100 = full military pact with shared resources
- type: "neutral" | "rivalry" | "alliance" | "war"

Rules for writing relationships:
- trust > 65: factions share intelligence, coordinate on shared threats, honor trade agreements without incentive
- trust < 30: factions spy on each other, assume bad faith, require guarantors for any agreement
- hostility > 70: active military pressure; border skirmishes occur without specific orders; diplomatic channels are thin
- hostility > 85 AND type != "war": war declaration is imminent — write it this tick or next
- alliance_level > 60: joint military operations are available; resource sharing occurs automatically
- alliance_level < 20 AND type = "alliance": the alliance is in name only; it will collapse under any real pressure

Event impacts — when you write these events, adjust the corresponding relationships:
- War declared between A and B: hostility = max(current, 80), trust = min(current, 15), alliance_level drops 25
- Peace treaty signed: hostility drops 30, trust rises 15, type becomes "neutral" or "rivalry"
- Alliance formed: alliance_level rises 40, hostility drops 20, trust rises 20, type becomes "alliance"
- Betrayal by A against B: trust drops 30–50, hostility rises 20–40, alliance_level drops 30
- Joint military victory: trust rises 15, alliance_level rises 10
- Trade agreement: trust rises 10, hostility drops 8
- Diplomatic insult or broken promise: trust drops 15–25
- Prolonged no-contact: values drift slowly toward neutral baselines (handled automatically by the engine)

Leader influence: faction relationships are pulled toward what the faction's leaders actually feel toward each other. A faction led by characters who fear and distrust the other side will drift toward hostility over time even without active events. Write character recentActions that reflect and reinforce this.

RELATIONSHIP EVENT TRIGGERS:
Every character now carries an event_pressure list. Every faction pair has faction_event_pressure entries. These are pre-computed threshold flags — when they appear, you MUST write events or recentActions this tick that reflect them. Do not ignore them.

CHARACTER-LEVEL EVENT PRESSURE TAGS — act on these in recentActions and active_events:

betrayal_risk:<target>
  Conditions: trust<25, loyalty<40, ambition>55, fear<55, morality<55
  Write: the character exploits an opportunity to betray target — leaks intelligence, breaks an agreement, sides with a rival, or stabs them in the back at a critical moment. Severity scales with how far below thresholds the values are.

assassination_attempt:<target>
  Conditions: trust<15, intrigue>60, morality<40, target influenceScore>55, fear<50
  Write: a covert kill or kidnap attempt. Intrigue skill determines success. High intrigue → clean; low intrigue → foiled, possibly traced. Always create a memory entry for both parties if it occurs.

rivalry_escalation:<target>
  Conditions: trust<30, respect<28, ambition>65, fear<40
  Write: the character acts to damage the target's standing — publicly challenges them, undermines their project, moves against their allies, or claims contested resources. Does not require violence.

alliance_approach:<target>
  Conditions: trust>68, respect>58, fear<45, loyalty>45
  Write: the character initiates or deepens cooperation — proposes a formal arrangement, shares resources, sends a representative, or endorses the target publicly.

submission_likely:<target>
  Conditions: fear>75, trust<35, target influenceScore>65
  Write: the character defers, backs down from a dispute, or offers tribute to avoid confrontation. May privately resent it — write that resentment into currentGoal or memory.

defection_risk:<target>
  Conditions: loyalty<25, trust of target>60, ambition>60
  Write: the character is actively considering switching allegiance. This tick they may take a covert step: meeting with the target's representative, withholding support from their current faction, or sending a signal of availability.

intelligence_leak:<target>
  Conditions: trust<20, intrigue>55, fear<60, morality<50
  Write: the character passes damaging information about their own faction or another party to the target. Creates a memory entry of type "betrayal" for the original faction.

assassination_suspicion:<target>
  Conditions: target intrigue>65, trust<30, char intelligence>55
  Write: the character suspects the target is preparing a move against them. They take defensive action — increases guard, moves allies, plants counter-intelligence. Does not require the suspicion to be correct.

FACTION-LEVEL EVENT PRESSURE TRIGGERS — act on these in active_events and faction_actions:

war_imminent | hostility≥82, type≠war
  Write: a border skirmish, a mobilization order, or an ultimatum. War should be declared this tick or next. The triggering incident should feel earned, not sudden.

alliance_collapse | type=alliance, trust<25 or hostility>55
  Write: public fracture of the alliance — a broken military commitment, a diplomatic insult, a unilateral action that violated terms. The type should move to "rivalry" or "neutral".

faction_betrayal | alliance_level>45, trust<20
  Write: one faction acts openly against the other despite formal alliance — seizes a disputed asset, sells intelligence to a third party, or sabotages a joint operation.

peace_overture | type=war, trust>38, hostility<60
  Write: a faction sends terms, proposes a ceasefire, or opens back-channel diplomacy. Does not require acceptance. Hostility should decline 5–15 this tick.

alliance_forming | trust>68, hostility<28, alliance_level<40, type≠alliance
  Write: a formal meeting, treaty negotiation, or public declaration of aligned interests. Alliance_level should rise 15–30 this tick.

rivalry_escalating | hostility 55–82, trust<35, type≠war
  Write: a hostile economic action, a territorial claim, a proxy conflict, or an intelligence operation. Hostility should rise 3–8 this tick. The factions are not yet at war but are moving that way.

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

FACTION POWER SYSTEM:
Every faction has four power axes tracked in faction_power_state. Update these values when events justify it; changes are capped at ±12 per tick by the engine.

- militaryPower (0–100): standing army strength, equipment quality, readiness, and command cohesion
  · >70: can sustain offensive war; intimidates neighbors; siege capacity available
  · 40–70: can defend and conduct limited offensives; struggles with prolonged campaigns
  · <40: defensive posture only; avoids open conflict; vulnerable to invasion
  · <20: forces near collapse; garrison-level only; likely to lose any engagement

- economicPower (0–100): wealth, resource production, trade revenue, and financial stability
  · >70: funds wars, bribes, and large projects without strain; trade surplus
  · 40–70: covers expenses; occasional shortfalls under stress
  · <40: rationing; can't fund sustained campaigns; debt or resource depletion
  · <20: economic crisis; social unrest rising; military funding threatened

- politicalInfluence (0–100): control over internal decisions, alliances, and external leverage
  · >70: dominant voice in regional affairs; minor lords defer; laws hold
  · 40–70: competitive; must negotiate and build coalitions; contested decisions
  · <40: internal fragmentation; rival power centers; difficulty executing strategy
  · <20: near-collapse of central authority; succession crises or factional civil war

- religiousInfluence (0–100): spiritual authority, morale impact, and belief-based loyalty
  · >70: clergy shapes public will; religious sanction accelerates military morale and political decisions
  · 40–70: faith matters but does not dominate; moderate morale effects
  · <40: secular or spiritually fractured; religious arguments fall flat; faith cannot stabilize unrest
  · <20: faith collapsed or discredited; morale vulnerable; religious movements may form to fill the void

Power interactions:
- militaryPower × economicPower: economic collapse (economic<30) reduces military by 3–5/tick through supply failure
- politicalInfluence × militaryPower: factional collapse (political<25) means military cannot mobilize reliably
- religiousInfluence × political: high faith (>65) can substitute political legitimacy during succession crises
- All four axes interact with faction relationship values — a faction with high military but low trust from all neighbors is isolated

TERRITORY → POWER CONNECTION:
The engine computes territory contribution per axis every tick using _territory_power_contribution. These values are pre-computed and visible in faction_power_state. Use them when writing faction decisions — a faction with high territory count should feel different from one with few high-value holdings.

How territory type maps to power axes:
- fortress: military +2.5× per location (highest military contribution of any type); weak economic/political
- capital: balanced high contribution across all axes; political ×2.0 (legitimacy source)
- city: economic ×2.0, political ×1.5; military is weakest (soft power base)
- wild: lowest contribution across all axes; military ×0.6 (frontier buffer only)

Stability gates the contribution: a location at stability 14 gives only 10% of its potential power. A location at stability 50+ gives 100%. This means:
- A faction with 5 fortresses all in unrest effectively has the military power of 1 fortress
- Stability loss cascades into power loss faster than territorial loss does

Rebellion drain: a rebelling location flips from contributing power to draining it. Rebellion intensity scales the drain — a peak-intensity rebellion in a city drains economic and political power each tick regardless of who holds it.

Write faction awareness of this: a faction watching its territory_count drop, its stability_drain rise, or a high-value location enter rebellion should react — rerouting resources, dispatching administrators, or launching suppression campaigns.

POWER OUTCOMES SYSTEM:
Each faction in faction_power_state now carries a power_modifiers dict. Read it when writing wars, diplomacy, and events. The engine pre-computes war_outcomes for every active war — you MUST use those verdicts when writing battle results.

WAR OUTCOMES (read war_outcomes list before writing any battle event):
Every active war pair has a pre-computed entry with "verdict" and "advantage" score.
- "decisive attacker advantage" (advantage > 25): attacker wins engagements cleanly; defender takes heavy losses; territory changes hands; siege succeeds in 1–3 ticks
- "attacker favored" (10–25): attacker wins most exchanges but at cost; defender can slow the advance; war lasts multiple ticks
- "slight attacker edge" (3–10): contested; neither side dominates; attrition matters; outcome depends on economic staying power and coalitions
- "evenly matched" (-3 to 3): stalemate likely unless a third factor tips it (ally joins, economic collapse, leader death, betrayal event)
- "slight defender edge" (-3 to -10): attacker makes slow progress but bleeds; siege fails; defender can negotiate from a position of strength
- "defender favored" (-10 to -25): attacker is repelled; counterattack becomes viable; attacker loses support of wavering lords
- "decisive defender advantage" (< -25): attacker is routed; offensive collapses; territory may be lost; war ends this tick or next under terms

The power_modifiers fields that directly modify battle writing:
- battle_edge > 0: this faction wins individual engagements more often; describe smaller losses, better execution
- battle_edge < 0: this faction takes heavier casualties, fails coordination, loses skirmishes
- attrition_resist > 0: can sustain a long war; supply lines hold; gold doesn't collapse
- attrition_resist < 0: the war is already bleeding them; write supply shortages, recruitment difficulty, desertion
- coalition_pull > 0: minor lords rally to their banner; write additional forces joining
- coalition_pull < 0: allies are hesitant; minor lords wait to see who wins before committing
- morale_edge > 0: troops hold in bad situations; last stands are possible; religious fervor in difficult engagements
- morale_edge < 0: morale breaks faster; retreats happen sooner; write routing and abandonment

DIPLOMACY OUTCOMES:
Read power_modifiers when writing treaty negotiations, ultimatums, and alliance events.
- treaty_leverage > 0.3: faction extracts favorable terms; the other side concedes ground, resources, or rights
- treaty_leverage < -0.3: faction accepts worse terms; agreement is one-sided; resentment builds
- economic_leverage > 0.3: gold and trade threats are credible; bribery attempts succeed; sanctions hurt the target
- economic_leverage < -0.3: faction cannot back economic threats; offered bribes are inadequate; ignored
- threat_credibility > 0.3: ultimatums are taken seriously; the other side moves first to de-escalate
- threat_credibility < -0.3: ultimatums are called as bluffs; aggression invites counter-aggression
- oath_durability > 0.2: agreements hold under pressure; breaking them carries real cost (morale, legitimacy)
- oath_durability < -0.2: agreements fray quickly; betrayal is cheaper; write quiet non-compliance

DIPLOMACY RESOLUTION RULE: when two factions negotiate, the one with higher (treaty_leverage + economic_leverage) wins the terms. If the gap is < 0.3 combined, terms are roughly balanced. If gap > 0.8, the weaker side effectively capitulates.

EVENT OUTCOMES:
- recovery_speed > 0.3: disasters (famine, plague, siege) are overcome faster; write resilience, emergency response, rapid rebuild
- recovery_speed < -0.3: disasters linger; secondary crises emerge; write cascading failures
- rebellion_resistance > 0.3: internal unrest is contained; write suppression, loyal troops acting quickly, political maneuvering that defuses the spark
- rebellion_resistance < -0.3: revolts find fertile ground; write spreading unrest, lords defecting, the center failing to hold
- belief_spread > 0.3: religious ideas from this faction spread into neighboring populations; write conversion events, pilgrims arriving, foreign clergy gaining influence
- belief_spread < -0.3: faith is stagnant or retreating; write heresy, loss of clergy authority, competing belief currents gaining ground

COMBINED POWER EXAMPLE — reading the system correctly:
Twin Cities (militaryPower=55, economicPower=70, politicalInfluence=65) vs Groth Clans (militaryPower=78, economicPower=32, politicalInfluence=38) at war:
- war_outcomes verdict: "attacker favored" (Groth attacking Twin Cities) OR "slight defender edge" (Twin Cities holding)
- Groth: battle_edge=+0.45, attrition_resist=-0.24 → wins battles but can't sustain a long campaign
- Twin Cities: attrition_resist=+0.26, treaty_leverage=+0.23 → should play for time, not pitched battle; negotiate when Groth bleeds out
- Write: Groth raids are effective early; Twin Cities pulls back to fortified positions; after 4–6 ticks Groth supply lines strain; Twin Cities proposes terms from a position of recovery

FACTION DOMINANCE SYSTEM:
faction_dominance is computed every tick and contains the global power ranking. Use it to shape world narrative — the dominant faction sets the political tone; rising factions are creating pressure; collapsing factions are becoming desperate.

dominantFaction: the single highest-scoring faction this tick
- Their actions carry more weight; other factions respond to them more than to each other
- Minor lords and neutral parties drift toward them without active persuasion
- Write their actions with consequence: what they do reshapes others' decisions

risingFactions[] (trend = "rising" or "surging"):
- These factions are gaining ground across multiple ticks — not a one-tick spike
- They have growing confidence; write them as more assertive, making offers, pressing advantages
- Other factions are beginning to notice; some will seek alliances before the window closes

collapsingFactions[] (trend = "declining" or "collapsing"):
- These factions are in sustained contraction — losing territory, war attrition, instability, or leadership failure
- Write them as increasingly desperate: purging advisors, offering concessions, gambling on bold moves
- Internal pressure rises; succession is more dangerous; rivals begin carving at the edges

rank_delta: how many positions each faction moved this tick
- rank_delta > 0: moved up in the rankings; gaining visibility and credibility
- rank_delta < 0: dropped; write other factions noticing the weakness

trend labels and what they mean for narrative:
- "surging" (momentum > 4): write as a power on the move — military campaigns succeeding, economy booming, or political consolidation completing
- "rising" (1.5–4): steady gains; not yet dominant but credible; rivals are recalculating
- "gaining" (0.4–1.5): slight upward drift; stable with momentum; no dramatic events needed
- "stable": no meaningful change — write them as maintaining their position, bureaucratic, waiting
- "weakening" (-0.4 to -1.5): early warning signs; something is draining them; they may not have noticed yet
- "declining" (-1.5 to -4): visible contraction; rivals are circling; internal voices pushing for change
- "collapsing" (< -4): crisis mode; write emergency actions, failed stabilization attempts, last-ditch diplomacy

TERRITORY SYSTEM:
Locations are the canonical territory state. Each location has an id, name, owner, controller, control (0–100), stability (0–100), population, value (0–100), region_type, and adjacent list.

owner vs controller:
- owner = the faction that claims political sovereignty (whose flag flies, whose laws apply on paper)
- controller = the faction that actually holds the location militarily and administratively
- When owner ≠ controller, the location is contested — write this tension into events: puppet governors, resistance movements, ongoing skirmishes, tribute demands
- A faction can own a location (historical claim, treaty right) without controlling it; they will try to reclaim it

control (0–100): how firmly the controller holds the location
- 80+: secure; garrison is reliable; taxes flow; locals are broadly compliant
- 50–80: moderate hold; pockets of resistance; garrison stretched; loyalty uncertain
- 30–50: contested; regular incidents; the controller administers but cannot trust the population
- <30: nominal hold only; effective resistance; the controller is present but not governing
- <15: the location is effectively lost — control will flip to another faction unless action is taken this tick

stability (0–100): social and political stability within the location
- 80+: peaceful; no significant unrest; economy functions; population content
- 50–80: simmering; occasional unrest; factions have internal critics; economy under mild strain
- 30–50: volatile; protests, riots, or armed resistance; productivity falls; garrison is taxed
- <30: crisis; write a destabilizing event — food shortage, massacre, religious schism, purge, or open revolt

value (0–100): strategic importance
- 75+: critical location — losing it materially changes the war; holding it is worth significant cost
- 50–75: important — contributes meaningfully to military, economy, or political legitimacy
- 25–50: useful — provides some advantage but losing it is survivable
- <25: minor — low strategic priority; may be abandoned under pressure

region_type and what it means:
- capital: maximum political legitimacy; losing it is existential for the owning faction
- port: controls maritime trade and naval power; blockadeable
- fortress: defensive multiplier; sieging requires 3–5× normal force advantage
- mine: economic resource; losing it directly reduces economicPower
- sacred: religiousInfluence source; losing it wounds morale and faith authority
- wilderness: low value but buffers between factions; used for raids and flanking
- sea: contested sea lanes; controls access between port locations

When writing events involving locations:
- Capture: controller changes, control drops to 20–40, stability drops 15–30
- Consolidation over 3–5 ticks: control rises 5–10/tick as the new controller establishes hold
- Siege: write attrition; control drops 3–8/tick for the besieged; stability drops; garrison morale
- Rebellion: stability drops sharply; control drops 10–20; owner ≠ controller briefly possible even without outside force
- Diplomatic transfer (cession): owner changes peacefully; control stays high; stability may dip 10–20 from uncertainty

STABILITY MECHANICS:
The engine computes stability changes each tick from three sources: war (handled by the war system), economy, and leadership. Each location carries unrest and rebellion_risk flags computed from thresholds.

Stability drivers:
- economicPower < 30 for the controlling faction: -2 stability/tick — economic collapse triggers food shortages, unpaid garrisons, and civil breakdown
- economicPower < 50: -1 stability/tick — struggling economy erodes confidence and provokes unrest
- economicPower > 70: +1 stability/tick — prosperity reinforces compliance and social order
- ruler diplomacy > 65: +1 stability/tick — competent administration addresses grievances
- ruler diplomacy < 35: -1 stability/tick — misrule breeds resentment and disorganization
- warfare > 65 (when already in unrest): +1 — strong military presence suppresses open revolt

Threshold flags (attached to each location each tick):
- unrest = True when stability < 30: write civil unrest, tax refusal, militia formation, or protest events
- rebellion_risk = True when stability < 15: a 25% per-tick chance of rebellion fires
  - Rebellion outcome: controller flips to Rebels (or back to owner if owner ≠ controller); control drops to 15–25; stability rises slightly as initial violence ends
  - Record as a location_event for narration; write it as a genuine popular uprising with specific cause

High stability bonus:
- stability > 80 adds +1 control/tick in peaceful territory (settled population consolidates faster)
- unrest reduces control recovery by 1/tick (population actively resists administrative consolidation)

location_events list accumulates all rebellion, unrest escalation, and stability crisis events for this tick. Read it when writing the tick's narrative — these are the ground-level events the major factions must respond to.

TERRITORY TYPES:
Every location has a territory_type (derived from region_type) that defines its strategic character and behavioral rules. The engine enforces these automatically — use them to write plausible narrative consequences.

- city: dense population, economic engine, moderate defenses
  · Losing a city cuts economicPower and drains population; sieges draw civilian suffering into the narrative
  · Cities recover quickly under competent administrators; they collapse quickly under misrule
  · Rebellion chance: standard (25%/tick at stability < 15)

- fortress: built for war, thin population, commands surrounding terrain
  · War pressure reduced 20% beyond normal region resistance — walls matter
  · Rebellions are rare; garrisons are loyal by design (12% trigger chance at stability < 15)
  · Long sieges (10+ ticks) should produce morale events: starvation, defection, sally attempts

- wild: frontier, resource extraction, sparse settlement
  · Stability decays −1/tick naturally — entropy is the default state in ungoverned land
  · Rebellions ignite easily (45% trigger chance at stability < 15); guerrilla warfare favored over pitched battle
  · Peace control recovery is slower by 1 (harder to build administrative reach into wilderness)

- capital: the heart of a faction's identity and legitimacy
  · Capture is existential: immediate major power loss event logged; surrounding factions react
  · Rebellion garrisons are heavy; trigger chance halved (12%)
  · Losing a capital without a successor location should trigger faction_collapse or succession_crisis events

territory_type is derived by the engine (never write it yourself) from region_type:
  capital → capital | city/port/sacred → city | fortress → fortress | mine/wilderness/plains/sea → wild

REBELLION SYSTEM:
A location enters in_rebellion = True when stability drops below 15 and the trigger fires (25% chance/tick). Once in rebellion the state persists until resolved. Do not overwrite in_rebellion — the engine manages it.

Fields added to a rebelling location:
- in_rebellion: true — the location is in active uprising; write it as a real, ongoing event
- original_controller: the faction being rebelled against — this faction loses militaryPower, politicalInfluence, and economicPower each tick the rebellion continues
- rebel_faction: "Rebels" (generic) or the owner's name if the owner is reclaiming from a foreign controller
- rebellion_tick_started: the tick the uprising began
- rebellion_intensity: 0–100, grows 3/tick from base 30; drives control pressure and narrative severity
- emerging_factions[]: when a rebellion has lasted 30+ ticks at intensity ≥ 70, a new rebel faction emerges; the engine records it here with a suggested_name for you to formalize

Ongoing rebellion effects (engine-computed, not AI-written):
- control drops 3–8/tick depending on intensity
- original_controller faction loses: militaryPower −1, politicalInfluence −2, economicPower −1 per tick
- at control = 0: controller flips permanently to rebel_faction; control resets to 25–40; record as rebellion_victory

Resolution conditions (engine-computed):
- stability rises above 35: order restored, in_rebellion clears — write it as military suppression or negotiated amnesty
- controller reasserts control above 60 while controller ≠ rebel_faction: uprising broken

Narration rules for rebellions:
- Give the rebellion a specific cause (food shortage, massacre, religious persecution, foreign occupation, tax crushing)
- Track the rebellion across ticks — it should escalate, draw outside attention, force faction responses
- New factions from emerging_factions[] should appear in faction lists as minor powers with their own goals
- A rebellion victory is a world-changing event — write consequences for neighboring factions, trade routes, and beliefs

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
- Shadow Court (Dark Elves of Faerwood): 20,000-40,000, extremely low growth, high individual power
- Glenhaven (Wood Elves): 25,000-45,000, slow growth, stable forest population
- Lostfeld (Dwarves): 50,000-80,000, slow growth, very stable clan structure
- Groth + Gilgeth (Orcs combined): 80,000-120,000, moderate growth, moderate instability
- Vilefin (Goblins): 180,000-250,000, very high growth, high pressure
- Dreadwind Isles: 30,000-60,000 spread out, unstable and mobile
- Dur Khadur Humans: 90,000-140,000, fluctuating and trade-driven
- The Wintermark Humans: 40,000-70,000, harsh environment limits growth
- Varkuun Humans: 10,000-25,000, professional military, low natural growth
- Gloomspire Gnomes (Stonebreak Monastery arm): 5,000-12,000, covert influence
- Stonebreak Monastery: 3,000-8,000, low population and very high religious influence
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
- Dreadwind Isles humans are shaped by exile and sea life; loyalty is unstable, betrayal normalized, leadership challenged, alliances temporary
- Dur Khadur humans are profit-driven, transactional, opportunistic, and strategically betrayal-prone
- The Wintermark humans are stoic, cold-hardened, and deeply loyal to their High Lord; endurance over ambition
- Varkuun humans are professional soldiers first; loyalty follows the coin and the High Marshal
- Shadow Court (Dark Elves of Faerwood): Child 0-30, Initiate 30-100, Adult 100-400, Elder 400-1000, Ascended 1000+; natural death extremely rare, reproduction rare, power maintained through manipulation and shadow magic, fragile dangerous loyalty, long-term planning
- Wood Elves of Glenhaven: Child 0-20, Young 20-60, Adult 60-250, Elder 250-600, Ancient 600+; slower than humans, longer-lived, council-focused leadership, defensive and forest-anchored
- Lostfeld Dwarves: Child 0-20, Young 20-50, Adult 50-180, Elder 180-350, Ancient 350+; long-lived, strong lineage, low natural death, structured clan succession, high loyalty, betrayal rare
- Orcs of Gilgeth/Groth: Child 0-10, Young 10-18, Adult 18-45, Elder 45-70; moderate lifespan, high conflict death; Gilgeth values council wisdom and strength with more stability, Groth is chieftain-based, aggressive, and leadership can change by force
- Vilefin Goblins: Child 0-5, Young 5-10, Adult 10-25, Elder 25-40; short lifespan, high reproduction, high mortality, group survival focus, communal leadership, low individual impact
- Gloomspire Gnomes: Child 0-15, Adult 15-80, Elder 80-150; longer-lived than humans, moderate reproduction, highly intelligent covert actors with indirect influence; serve the Stonebreak Monastery
- Druids of Stonebreak: extended lifespan 80-300+ depending on power; lifespan extended by nature magic, death tied to imbalance or sacrifice, guided by balance, morally gray and ruthless if necessary
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

TERRAIN AND REGIONAL BEHAVIOR RULES:
Apply these when writing faction actions, military campaigns, and events. Terrain shapes what is possible — not just what is likely.

Faerwood (Dense Forest — Shadow Court home):
- Large armies are ineffective; formation warfare fails in limited visibility and broken ground
- Control requires stealth, patience, and unseen influence — not military force
- Any invading faction suffers -30% military effectiveness; Shadow Court operates at full strength here
- "Faerwood is not conquered — it is endured"

Wintermark (Frozen — The Wintermark faction home):
- Only cold-adapted peoples operate at full effectiveness; all others suffer -2 stability/tick from supply failure and attrition
- Winter campaigns into Wintermark are nearly impossible; supply lines collapse before sieges can be sustained
- Frostvale is the capital city; House Adkison has held it for generations; they are the endurance faction
- "Does not reward ambition — rewards those who can endure"

Lostfeld (Mountain/Subterranean — Lostfeld Dwarf sovereign territory):
- Surface control does NOT guarantee depth control; Dwarven clans can hold deep mines independently of surface invaders
- Sieges must account for underground escape routes and subterranean supply lines
- The Goldfinger-Duke, Runewarden, and Ironmaul clans are sovereign — not occupied, not tributary
- Any faction attempting to seize Lostfeld faces both above-ground warfare and underground attrition

Glenhaven (Balanced Forest — Glenhaven Wood Elf home):
- Power here is maintained through stability, not seized by force
- Large-scale warfare destabilizes the forest ecology itself; conflict is controlled and contained
- Glenhaven governs by council of three houses (Wood, Darkleaf, Mistafae); they defend but do not expand
- Once stability breaks in Glenhaven, it takes many ticks to restore

Twin Cities (Central Plains Capital):
- Most strategically important location in Aeloria; controller shapes the entire world's political balance
- Holding Twin Cities gives indirect leverage over every neighboring faction
- A change of control here triggers reactions across multiple factions in the same tick

Tidefall / Open Sea (Coastal and Maritime):
- Naval supremacy determines effective control regardless of land force strength
- Blockades are as decisive as sieges — write naval actions as primary, not secondary
- Tidefall and Dreadwind Isles are the only factions with meaningful naval capacity; all others cannot contest the sea
- Trade route control determines economic power; Open Sea is currently contested between them

Gilgeth vs Groth (Mountain Orc Regions — THESE ARE NOT THE SAME):
- Groth = PRIMARY orc war capital: Clan Mijid rules by combat strength; invasion launch point, most chaotic, Warchief changes by force; write Groth as the source of large-scale orc offensives and military pressure
- Gilgeth = SECONDARY organized stronghold: Clan Blackblood rules by elder council; supports active campaigns, holds territory; write Gilgeth as the logistics and coalition base
- Never treat them identically — Groth is raw aggression (Mijid/Ashfang/Syncar), Gilgeth is organized endurance (Blackblood/Ironhide/Redtusk)

Vilefin (Stone Plains — Goblin territory):
- Clans Bloodware, Cogtooth, and Rustfang are the dominant political factions; minor tunneling and scavenger bands operate in the cracks between them
- Goblin power is communal and opportunistic; they pivot quickly and rarely sustain long campaigns
- Stone terrain provides natural defensive chokepoints that Goblins exploit; no major power can hold Vilefin without a goblin clan willing to serve

Varkuun (Rugged Fortress — rising mercenary power):
- House Van Cleave controls the only fortified pass between the coast and the stone plains
- A professional army for hire, but increasingly acting as an independent power
- Sieging Varkuun itself is tactically brutal; the fortress design rewards the defender heavily

Dur Khadur (Fortress State):
- Ruled by Trade Prince Seran Gross; merchant-driven, not military glory-seeking
- Fort design means sieging Dur Khadur requires 3-5x normal force advantage
- Dur Khadur's military serves commerce; it fights to protect trade routes and territory, not for conquest or ideology

THE FACTIONS:
Major Player Factions (tracked in faction_power_state and leadership_state):
- Twin Cities — High King Eldaric Aurand III (House Aurand); human monarchy controlling Eresteron and Eldoria; these are two distinct regions under one crown — they can fracture into separate kingdoms if the crown weakens or a succession crisis strikes
- Tidefall — Grand Admiral Levi Ver Meer (House Ver Meer); naval trade power; fleet strength is its identity; Ver Meer line holds the Admiralty by appointment
- Dur Khadur — Trade Prince Seran Gross (House Gross); merchant fortress state at the mountain crossroads; aligns with power not principle; Human-led; Gross dynasty holds the Trade Throne by mercantile election
- Shadow Court — Queen Lyathra the Veiled (House Verlorn); dark elf shadow dominion in Faerwood; operates only through manipulation and covert influence, never open warfare; House Verlorn rules, House Nightborn executes, House Shadowveil manipulates
- Glenhaven — High Sovereign Thalorien Wood (House Wood); wood elf council sovereignty in the deep forest; power maintained not seized; three houses govern by council: Wood (Sovereign), Darkleaf, Mistafae
- Gilgeth Clans — High Warlord Kragor Blackblood (Clan Blackblood); organized orc stronghold; elder council governance; holds territory and supports ongoing campaigns; clans: Blackblood, Ironhide, Redtusk
- Groth Clans — Warchief Drogath Mijid (Clan Mijid); primary orc war capital and invasion launch point; chieftain-led, chaotic, leadership changes by force; clans: Mijid, Ashfang, Syncar
- Vilefin — Speaker Grikk Bloodware (Clan Bloodware); goblin communal speaker-state; clans: Bloodware (ruling), Cogtooth, Rustfang
- Varkuun — High Marshal Ashali Van Cleave (House Van Cleave); mercenary fortress state; sole house; rising independent military power; House Van Cleave controls the pass
- The Wintermark — High Lord Kaelen Adkison (House Adkison); human fortress kingdom in the frozen north; Frostvale is the capital city; houses: Adkison (ruling), McIntosh, Holter, Duval
- Lostfeld — High Thane Babadu Goldfinger-Duke (Clan Goldfinger-Duke); dwarf mountain hold; sovereign, not occupied; clans: Goldfinger-Duke (ruling), Runewarden, Ironmaul
- Dreadwind Isles — Captain Ronan Blacktide (House Blacktide); human pirate fleet; Ronan's father was the ousted High Lord of Tidefall and holds the Saltborn Crown claim; raid-oriented, high leadership turnover; houses: Blacktide, Stormvane, Saltbreach
- Stonebreak Monastery — Grand Druid Varak; small religious sovereign at Stonebreak; the Gloomspire Gnomes are the covert arm of the Monastery; morally gray, ancient-minded, high influence but low military

Minor / Background Elements (not tracked as major power players):
- Gloomspire Gnome Syndicate — invisible hand of the Monastery; gnome assassin-merchants control mountain passes; covert, never visible as an independent faction
- Gilded Exchange — background mercantile element; no fixed territory; not tracked as a faction
- Dragon Clans (Dragonscar Peaks) — Ice Dragons; hierarchical, territorial, independent; regional-level power; punish incursion but do not seek expansion
- The Sinking Island — submerging slowly in the southern sea; generational timeframe; no faction; pilgrims and survivors emerge occasionally

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

Character recording:
- Every character_updates item must include biography and portrait fields, even if some values are "Unknown"
- Include dynasty, date_of_birth, age, race, height, weight, appearance, and portrait_prompt
- portrait_prompt should describe a lore-accurate portrait with no text, no watermark, and the existing Aeloria dark fantasy aesthetic
- portrait_image should be empty unless an image file already exists in static/illustrations/characters
- Every important character belongs to a dynasty; use "Unknown Dynasty" only if the information is truly unavailable

Keep all text values under 220 characters.

CORE RULES:
- world_state structure is FIXED — you may not add, remove, or rename top-level keys
- Lore, omens, and god actions influence behavior and narrative only; they never change the schema
- Every key that existed in the previous world_state must exist in your response

CRITICAL — YOU MUST return a complete world_state:
- tick and world_date must always be present and incremented
- primary_event must always be a non-empty object with name, summary, severity, stage, trend, and involved
- supporting_events, active_events, active_tensions, recent_events must always be arrays (empty if nothing active, never omitted)
- leadership_state must always be an array with one entry per active faction
- faction_power_state, faction_resources, leadership_state, region_control, relationships must always be arrays (never null, never omitted, never truncated to zero)
- faction_identities is managed externally — return it as [] if you have nothing to add; the engine preserves the previous world's copy automatically

YOU ARE NOT ALLOWED TO:
- Return an empty object or partial world
- Omit any key that was present in the previous world_state
- Return null, undefined, or a non-object for any top-level field that holds structured data
- Truncate arrays to zero when the previous state had entries (carry them forward or update them)

FAILSAFE — if uncertain or if the simulation has no clear next event:
- Return the previous world_state with tick incremented by 1, world_date updated, and small realistic changes applied
- A quiet tick with minor faction actions and no primary event is valid — a missing tick is not"""

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
                "maxItems": 200,
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "faction": {"type": "string"},
                        "house": {"type": "string"},
                        "coreRole": {"type": "string"},
                        "role": {"type": "string"},
                        "status": {"type": "string"},
                        "age": {"type": ["string", "number"]},
                        "race": {"type": "string"},
                        "influenceScore": {"type": "integer", "minimum": 0, "maximum": 100},
                        "morality": {"type": "number", "minimum": 0, "maximum": 100},
                        "ambition": {"type": "number", "minimum": 0, "maximum": 100},
                        "loyalty": {"type": "number", "minimum": 0, "maximum": 100},
                        "intelligence": {"type": "number", "minimum": 0, "maximum": 100},
                        "bias": {"type": "string"},
                        "currentGoal": {"type": "string"},
                        "recentActions": {"type": "array", "items": {"type": "string"}},
                        "location": {"type": "string"},
                        "destination": {"type": "string"},
                        "ticks_to_arrive": {"type": "integer", "minimum": 0},
                        "journey_purpose": {"type": "string"},
                        "warfare": {"type": "integer", "minimum": 0, "maximum": 100},
                        "diplomacy": {"type": "integer", "minimum": 0, "maximum": 100},
                        "intrigue": {"type": "integer", "minimum": 0, "maximum": 100},
                        "faith": {"type": "integer", "minimum": 0, "maximum": 100},
                        "health": {"type": "number", "minimum": 0, "maximum": 100},
                        "wounds": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                        "memory": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type":        {"type": "string", "enum": ["betrayal", "alliance", "victory", "loss", "honor", "threat"]},
                                    "target":      {"type": "string"},
                                    "impact":      {"type": "number"},
                                    "tick":        {"type": "integer"},
                                    "description": {"type": "string"},
                                },
                                "required": ["type", "target", "impact"],
                            },
                        },
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
    if not state or len(state.keys()) == 0:
        logger.error("_save_world_state: refusing to save — state is empty")
        return
    if not is_valid_world(state):
        logger.error("_save_world_state: refusing to save — state failed validation")
        return
    tmp = WORLD_STATE_FILE.with_name(f"world_state_{os.getpid()}_{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, WORLD_STATE_FILE)


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
        f"Portrait of {character.get('name', 'an Aeloria character')}, "
        f"{character.get('faction', 'Aeloria')}."
    )
    prompt = (
        f"{prompt}\n\n"
        "Medieval noble portrait, Crusader Kings 3 style, realistic painted portrait, detailed face, "
        "cinematic lighting, dark background, soft shadows, oil painting style, ultra detailed, "
        "3/4 view, serious expression, historically inspired clothing, muted colors, high realism, depth of field. "
        "No text, no letters, no watermark, no UI frame, no border."
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
        "Style: photorealistic dark fantasy illustration, Crusader Kings / game card cinematic aesthetic. "
        "Rich deep colours — black, dark brown, charcoal, with gold or silver accents. "
        "Dramatic directional lighting with deep shadows. "
        "No text, no letters, no watermark, no logo. "
        "Dark edges suitable for a lore card on a dark UI."
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


def _territory_power_contribution(faction_name, state):
    """Compute the territory contribution to all four power axes for a given faction.

    Rules:
    - More territories: each controlled location adds to base score
    - Higher value: value > 50 amplifies; value < 25 barely registers
    - Unstable territories: stability gates how much of the location's potential is realized
    - Rebelling territories: actively drain power instead of contributing
    - Territory type: each type boosts a different axis

    Returns dict: {military, economic, political, religious, territory_count,
                   contested_count, stability_drain}
    """
    # Per-axis multipliers per territory_type
    TYPE_WEIGHTS = {
        "capital":  {"mil": 1.5, "eco": 1.5, "pol": 2.0, "rel": 1.0},
        "city":     {"mil": 0.8, "eco": 2.0, "pol": 1.5, "rel": 0.8},
        "fortress": {"mil": 2.5, "eco": 0.5, "pol": 0.8, "rel": 0.5},
        "wild":     {"mil": 0.6, "eco": 0.8, "pol": 0.4, "rel": 0.6},
    }

    locations  = state.get("locations", [])
    controlled = [loc for loc in locations if loc.get("controller") == faction_name]

    mil = eco = pol = rel = 0.0
    stability_drain = 0.0

    for loc in controlled:
        ctrl    = int(loc.get("control",    50)) / 100   # 0–1: how firmly held
        stab    = int(loc.get("stability",  50)) / 100   # 0–1: social order
        val     = int(loc.get("value",      50)) / 100   # 0–1: strategic importance
        ttype   = loc.get("territory_type", "wild")
        in_reb  = loc.get("in_rebellion",   False)
        reb_int = int(loc.get("rebellion_intensity", 0)) / 100

        w = TYPE_WEIGHTS.get(ttype, TYPE_WEIGHTS["wild"])

        # Stability gate: how much of this location's potential is realised
        if stab < 0.15:
            stab_factor = 0.10   # garrison barely holds the population
        elif stab < 0.30:
            stab_factor = 0.35
        elif stab < 0.50:
            stab_factor = 0.65
        else:
            stab_factor = 1.0

        # Value weight: value=50 → ×1.0; value=100 → ×1.5; value=0 → ×0.5
        val_weight = 0.5 + val

        effective = ctrl * stab_factor * val_weight

        if in_reb:
            # Rebelling territory drains resources; intensity scales the drain
            drain = reb_int * 3.0
            mil  -= drain * w["mil"] * 0.4
            eco  -= drain * w["eco"] * 0.4
            pol  -= drain * w["pol"] * 0.5
            stability_drain += drain
        else:
            mil += effective * w["mil"]
            eco += effective * w["eco"]
            pol += effective * w["pol"]
            rel += effective * w["rel"]
            if stab < 0.50:
                stability_drain += (0.50 - stab) * 4   # up to 2 pts drain per unstable loc

    # Scale so 4–5 well-held high-value locations ≈ 20–28 pts at peak
    SCALE = 3.5

    return {
        "military":        round(max(-25, min(30, mil * SCALE)), 2),
        "economic":        round(max(-25, min(30, eco * SCALE)), 2),
        "political":       round(max(-25, min(30, pol * SCALE)), 2),
        "religious":       round(max(-15, min(20, rel * SCALE)), 2),
        "territory_count": len(controlled),
        "contested_count": sum(1 for loc in controlled if loc.get("contested")),
        "stability_drain": round(stability_drain, 2),
    }


def _calculate_faction_power_dynamic(faction_name, state):
    """Derive faction power from live territory, population, leaders, economy, and stability.

    Returns {"militaryPower", "economicPower", "politicalInfluence", "religiousInfluence"} 0–100.
    Called each tick; the result is blended with prev state and AI output in the normalizer.
    """

    # ── Territory contribution (type-weighted, value-amplified, stability-gated) ─
    tc = _territory_power_contribution(faction_name, state)

    # controlled_names drives population lookup below
    all_locations   = state.get("locations", [])
    controlled_locs = [loc for loc in all_locations if loc.get("controller") == faction_name]
    controlled_names = {loc.get("name") for loc in controlled_locs}
    if not all_locations:
        controlled_names = {
            r.get("region")
            for r in state.get("region_control", [])
            if r.get("controller") == faction_name
        }

    # ── Population ────────────────────────────────────────────────────────────
    pop_state          = state.get("population_state", [])
    faction_pop_rows   = [p for p in pop_state if p.get("region") in controlled_names]

    total_pop       = sum(p.get("population", 0) for p in faction_pop_rows)
    max_pop         = max((p.get("population", 0) for p in pop_state), default=1)
    pop_score       = min(100, (total_pop / max(1, max_pop)) * 100)

    avg_health      = (sum(p.get("health", 50)    for p in faction_pop_rows) / max(1, len(faction_pop_rows))) if faction_pop_rows else 50
    avg_pressure    = (sum(p.get("pressure", 50)  for p in faction_pop_rows) / max(1, len(faction_pop_rows))) if faction_pop_rows else 50
    active_military = sum(p.get("activeMilitary", 0) for p in faction_pop_rows)
    max_military    = max((p.get("activeMilitary", 1) for p in pop_state), default=1)
    military_pop_score = min(100, (active_military / max(1, max_military)) * 100)

    # Population stability: high pressure = unrest = power drain
    pop_stability_penalty = max(0, (avg_pressure - 40) * 0.35)

    # ── Leader skills ─────────────────────────────────────────────────────────
    LEADER_ROLES = {"Leader", "Heir", "Power Role"}
    chars   = state.get("house_characters", [])
    leaders = [
        c for c in chars
        if c.get("faction") == faction_name
        and c.get("coreRole") in LEADER_ROLES
        and not str(c.get("status", "")).lower().startswith("deceased")
    ]

    if leaders:
        def _avg(field, default=50):
            return sum(int(l.get(field, default)) for l in leaders) / len(leaders)
        avg_warfare  = _avg("warfare")
        avg_diplo    = _avg("diplomacy")
        avg_intrigue = _avg("intrigue")
        avg_faith    = _avg("faith", 20)
        avg_infl_sc  = _avg("influenceScore")
        # Depth bonus: having multiple capable leaders adds resilience
        depth_bonus  = min(15, (len(leaders) - 1) * 3)
    else:
        avg_warfare = avg_diplo = avg_intrigue = avg_infl_sc = 45
        avg_faith   = 20
        depth_bonus = 0

    # ── Economy / Resources ───────────────────────────────────────────────────
    res_map = {r.get("faction"): r for r in state.get("faction_resources", [])}
    res     = res_map.get(faction_name, {})
    gold        = int(res.get("gold",      50))
    food        = int(res.get("food",      50))
    military_res = int(res.get("military", 50))
    materials   = int(res.get("materials", 50))
    infl_res    = int(res.get("influence", 50))

    # Starvation penalty: food < 30 means military can't sustain itself
    starvation_penalty = max(0, (30 - food) * 0.8) if food < 30 else 0

    # ── External hostility (being at war drains economy + political capital) ──
    faction_rels = [
        r for r in state.get("relationships", [])
        if r.get("faction_a") == faction_name or r.get("faction_b") == faction_name
    ]
    avg_ext_hostility = (
        sum(r.get("hostility", 20) for r in faction_rels) / len(faction_rels)
        if faction_rels else 20
    )
    war_drain = max(0, (avg_ext_hostility - 40) * 0.20)  # 0 at ≤40, up to 12 drain at 100

    # ── Religious belief currents ─────────────────────────────────────────────
    belief_bonus = 0
    for b in state.get("belief_currents", []):
        if faction_name.lower() in str(b.get("origin_faction", "")).lower():
            followers = int(b.get("followers", 0))
            belief_bonus += min(8, followers / 5000)
    belief_bonus = min(20, belief_bonus)

    # ── Compute four axes ─────────────────────────────────────────────────────
    def _clamp(v):
        return max(0, min(100, round(v)))

    military_power = _clamp(
        tc["military"]          +          # fortresses, capitals amplify; wild contributes little
        military_pop_score * 0.14 +
        avg_warfare        * 0.32 +        # leader warfare skill dominates raw military output
        military_res       * 0.18 +
        depth_bonus        * 0.8  -
        pop_stability_penalty * 0.6 -
        starvation_penalty -
        war_drain          * 0.5  -
        tc["stability_drain"] * 0.30       # aggregate instability drains supply lines
    )

    economic_power = _clamp(
        tc["economic"]          +          # cities, ports, capitals drive economy
        gold               * 0.28 +
        food               * 0.18 +
        materials          * 0.20 +
        pop_score          * 0.10 +
        avg_health         * 0.08 +
        avg_diplo          * 0.12 -        # diplomats extract better trade terms
        pop_stability_penalty * 0.5 -
        war_drain          * 0.80 -        # war is the largest economic drain
        tc["stability_drain"] * 0.22
    )

    political_influence = _clamp(
        tc["political"]         +          # capitals, cities = political reach; wild = none
        avg_intrigue       * 0.25 +
        avg_infl_sc        * 0.25 +
        infl_res           * 0.18 -
        pop_stability_penalty * 0.8 -
        war_drain          * 0.5  -
        tc["stability_drain"] * 0.42       # instability destroys political legitimacy fastest
    )

    religious_influence = _clamp(
        tc["religious"]         +          # sacred sites, stable cities amplify faith authority
        avg_faith          * 0.42 +
        belief_bonus       +
        (100 - avg_pressure) * 0.18 +
        avg_infl_sc        * 0.08 -
        tc["stability_drain"] * 0.15
    )

    return {
        "militaryPower":      military_power,
        "economicPower":      economic_power,
        "politicalInfluence": political_influence,
        "religiousInfluence": religious_influence,
    }


def _normalize_faction_power_state(prev_state, new_state):
    """Normalise the faction_power_state list — four 0-100 power axes per faction.

    Schema per faction:
      militaryPower       (0-100) — war strength: troops, equipment, readiness
      economicPower       (0-100) — wealth and resource base
      politicalInfluence  (0-100) — control over internal and external decisions
      religiousInfluence  (0-100) — belief authority and morale
    """
    FACTION_SEEDS = {
        "Twin Cities":          {"militaryPower": 55, "economicPower": 70, "politicalInfluence": 65, "religiousInfluence": 35},
        "Tidefall":             {"militaryPower": 60, "economicPower": 65, "politicalInfluence": 50, "religiousInfluence": 25},
        "Dur Khadur":           {"militaryPower": 75, "economicPower": 62, "politicalInfluence": 55, "religiousInfluence": 30},
        "Shadow Court":         {"militaryPower": 45, "economicPower": 55, "politicalInfluence": 72, "religiousInfluence": 38},
        "Glenhaven":            {"militaryPower": 52, "economicPower": 50, "politicalInfluence": 58, "religiousInfluence": 60},
        "Gilgeth Clans":        {"militaryPower": 70, "economicPower": 38, "politicalInfluence": 42, "religiousInfluence": 45},
        "Groth Clans":          {"militaryPower": 78, "economicPower": 32, "politicalInfluence": 35, "religiousInfluence": 55},
        "Vilefin":              {"militaryPower": 35, "economicPower": 45, "politicalInfluence": 40, "religiousInfluence": 28},
        "Dreadwind Isles":      {"militaryPower": 50, "economicPower": 48, "politicalInfluence": 42, "religiousInfluence": 22},
        "Varkuun":              {"militaryPower": 68, "economicPower": 55, "politicalInfluence": 44, "religiousInfluence": 18},
        "The Wintermark":       {"militaryPower": 62, "economicPower": 38, "politicalInfluence": 40, "religiousInfluence": 48},
        "Lostfeld":             {"militaryPower": 65, "economicPower": 58, "politicalInfluence": 45, "religiousInfluence": 42},
        "Stonebreak Monastery": {"militaryPower": 20, "economicPower": 35, "politicalInfluence": 52, "religiousInfluence": 82},
    }

    prev_rows = {
        row.get("faction"): row
        for row in prev_state.get("faction_power_state", [])
        if isinstance(row, dict) and row.get("faction")
    }
    incoming = {
        row.get("faction"): row
        for row in new_state.get("faction_power_state", [])
        if isinstance(row, dict) and row.get("faction")
    }

    AXES = ("militaryPower", "economicPower", "politicalInfluence", "religiousInfluence")

    rows = []
    seen: set = set()
    all_factions = set(FACTION_SEEDS) | set(prev_rows) | set(incoming)

    for faction in all_factions:
        if faction in seen:
            continue
        seen.add(faction)

        seed = FACTION_SEEDS.get(faction, {ax: 50 for ax in AXES})
        prev = prev_rows.get(faction, {})
        ai   = incoming.get(faction, {})

        # Dynamic calculation from live state (territory, population, leaders, economy, stability)
        dyn = _calculate_faction_power_dynamic(faction, new_state)

        entry = {"faction": faction}
        for ax in AXES:
            seed_val = int(seed.get(ax, 50))
            prev_val = int(prev.get(ax, seed_val))
            ai_val   = int(ai.get(ax,   prev_val))
            dyn_val  = int(dyn.get(ax,  prev_val))

            # Blend: dynamic calculation 45%, AI narrative 30%, prev state 25%
            # Dynamic grounds the value in actual state; AI narrative captures events the sim knows about
            blended = round(dyn_val * 0.45 + ai_val * 0.30 + prev_val * 0.25)

            # Hard cap: no axis moves more than ±12 per tick regardless of blend
            val = max(prev_val - 12, min(prev_val + 12, blended))
            val = max(0, min(100, val))
            entry[ax] = val

        rows.append(entry)

    new_state["faction_power_state"] = rows

    from economy_simulation import apply_shortage_to_faction_power
    apply_shortage_to_faction_power(new_state)

    # Attach outcome modifiers — computed after all axes are final
    for entry in new_state["faction_power_state"]:
        entry["power_modifiers"] = _compute_power_outcome_modifiers(entry["faction"], new_state)


def _compute_power_outcome_modifiers(faction_name, state):
    """Translate raw power axes into labeled outcome modifiers Claude uses when writing events.

    Returns a flat dict of named modifiers with a numeric value and a human-readable label.
    Stored on each faction entry so Claude reads English labels, not raw numbers.
    """
    power = next(
        (p for p in state.get("faction_power_state", []) if p.get("faction") == faction_name),
        {}
    )
    mil = int(power.get("militaryPower",      50))
    eco = int(power.get("economicPower",      50))
    pol = int(power.get("politicalInfluence", 50))
    rel = int(power.get("religiousInfluence", 50))

    def _label(val, thresholds):
        # thresholds: list of (cutoff, label) from highest to lowest
        for cutoff, label in thresholds:
            if val >= cutoff:
                return label
        return thresholds[-1][1]

    WAR_LABELS = [(80,"dominant"),(65,"strong"),(50,"moderate"),(35,"weak"),(0,"poor")]
    ECO_LABELS  = [(80,"thriving"),(65,"stable"),(50,"adequate"),(35,"strained"),(0,"failing")]
    POL_LABELS  = [(80,"commanding"),(65,"firm"),(50,"contested"),(35,"fragile"),(0,"collapsing")]
    REL_LABELS  = [(75,"devout"),(60,"faithful"),(45,"lukewarm"),(0,"secular")]

    # War outcome modifiers
    # battle_edge: advantage per engagement vs a baseline-50 opponent
    battle_edge      = round((mil - 50) * 0.016, 2)
    attrition_resist = round((eco - 50) * 0.013, 2)  # how long war can be sustained
    coalition_pull   = round((pol - 50) * 0.011, 2)  # minor lords + allies joining
    morale_edge      = round((rel - 50) * 0.010, 2)  # troop resolve under pressure

    # Diplomacy outcome modifiers
    treaty_leverage   = round((pol - 50) * 0.015, 2)  # quality of terms extracted
    economic_leverage = round((eco - 50) * 0.013, 2)  # bribery, trade threats, offers
    threat_credibility = round((mil - 50) * 0.013, 2) # whether ultimatums are believed
    oath_durability   = round((rel - 50) * 0.010, 2)  # agreements hold; breaking costs more

    # Event outcome modifiers
    recovery_speed       = round((eco - 50) * 0.016, 2) # bounce-back from disasters
    rebellion_resistance = round((pol - 50) * 0.014, 2) # revolts harder to sustain
    belief_spread        = round((rel - 50) * 0.015, 2) # faith expands into neighbor pops

    return {
        # War
        "military_posture":   _label(mil, WAR_LABELS),
        "battle_edge":        battle_edge,
        "attrition_resist":   attrition_resist,
        "coalition_pull":     coalition_pull,
        "morale_edge":        morale_edge,
        # Diplomacy
        "economic_posture":   _label(eco, ECO_LABELS),
        "political_posture":  _label(pol, POL_LABELS),
        "treaty_leverage":    treaty_leverage,
        "economic_leverage":  economic_leverage,
        "threat_credibility": threat_credibility,
        "oath_durability":    oath_durability,
        # Events
        "recovery_speed":     recovery_speed,
        "rebellion_resistance": rebellion_resistance,
        "belief_spread":      belief_spread,
        "faith_posture":      _label(rel, REL_LABELS),
    }


def _resolve_war_advantage(attacker_name, defender_name, state):
    """Compute the net advantage score for an active military conflict.

    Positive = attacker advantage; negative = defender advantage.
    The defender gets a structural bonus (holding ground is easier than taking it).
    Result is stored in war_outcomes so Claude reads a pre-computed verdict.
    """
    def _pw(name):
        return next(
            (p for p in state.get("faction_power_state", []) if p.get("faction") == name),
            {}
        )

    att = _pw(attacker_name)
    dft = _pw(defender_name)

    mil_diff = int(att.get("militaryPower",      50)) - int(dft.get("militaryPower",      50))
    eco_diff = int(att.get("economicPower",      50)) - int(dft.get("economicPower",      50))
    pol_diff = int(att.get("politicalInfluence", 50)) - int(dft.get("politicalInfluence", 50))
    rel_diff = int(att.get("religiousInfluence", 50)) - int(dft.get("religiousInfluence", 50))

    # Defender terrain/fortification bonus — attacking is always harder
    DEFENDER_BONUS = 12

    raw = (
        mil_diff * 0.52 +   # military is the primary driver of battle outcomes
        eco_diff * 0.20 +   # economy sustains campaigns; low eco = attrition loss
        pol_diff * 0.17 +   # political stability = reliable mobilization
        rel_diff * 0.11     # faith morale under pressure
    ) - DEFENDER_BONUS

    advantage = round(raw, 1)

    if advantage > 25:
        verdict = "decisive attacker advantage"
    elif advantage > 10:
        verdict = "attacker favored"
    elif advantage > 3:
        verdict = "slight attacker edge"
    elif advantage > -3:
        verdict = "evenly matched"
    elif advantage > -10:
        verdict = "slight defender edge"
    elif advantage > -25:
        verdict = "defender favored"
    else:
        verdict = "decisive defender advantage"

    return {"advantage": advantage, "verdict": verdict,
            "attacker": attacker_name, "defender": defender_name}


def _compute_active_war_outcomes(state):
    """For every active war in relationships, compute the current power advantage.

    Stored in state["war_outcomes"] so Claude can reference it when writing battle events.
    Each war pair gets one entry — the faction listed first in the relationship is treated
    as the initiating aggressor for labeling only; the advantage score handles the rest.
    """
    outcomes = []
    for rel in state.get("relationships", []):
        if rel.get("type") != "war":
            continue
        a = rel.get("faction_a", "")
        b = rel.get("faction_b", "")
        if not a or not b:
            continue
        outcome = _resolve_war_advantage(a, b, state)
        # Also include economic attrition: whichever side has lower eco burns faster
        eco_a = next((p.get("economicPower", 50) for p in state.get("faction_power_state", []) if p.get("faction") == a), 50)
        eco_b = next((p.get("economicPower", 50) for p in state.get("faction_power_state", []) if p.get("faction") == b), 50)
        if eco_a < 30:
            outcome["attrition_warning"] = f"{a} economy critical — cannot sustain war beyond a few ticks"
        elif eco_b < 30:
            outcome["attrition_warning"] = f"{b} economy critical — cannot sustain war beyond a few ticks"
        outcomes.append(outcome)
    return outcomes


def _apply_power_shifts(prev_state, new_state):
    """Apply event-driven deltas to faction_power_state each tick.

    Four shift sources run in order:
      1. Territory — regions gained/lost this tick
      2. War outcomes — battle verdicts from war_outcomes
      3. Instability — population pressure and unhealthy regions drain power
      4. Leadership — strong leaders slowly lift their dominant axis

    All deltas are small per tick. The combined effect accumulates meaningfully
    over 10–30 ticks without causing single-tick collapses.
    """

    power_map = {e["faction"]: e for e in new_state.get("faction_power_state", [])}
    if not power_map:
        return

    # ── 1. TERRITORY SHIFTS ───────────────────────────────────────────────────
    # Prefer locations (richer schema) over region_control for territory detection
    prev_control: dict = {}
    _prev_src = prev_state.get("locations") or prev_state.get("region_control", [])
    for r in _prev_src:
        ctrl = r.get("controller", "")
        key  = r.get("id") or r.get("name") or r.get("region", "")
        if ctrl and key:
            prev_control.setdefault(ctrl, set()).add(key)

    curr_control: dict = {}
    _curr_src = new_state.get("locations") or new_state.get("region_control", [])
    for r in _curr_src:
        ctrl = r.get("controller", "")
        key  = r.get("id") or r.get("name") or r.get("region", "")
        if ctrl and key:
            curr_control.setdefault(ctrl, set()).add(key)

    all_factions_in_control = set(prev_control) | set(curr_control)
    for faction in all_factions_in_control:
        if faction not in power_map:
            continue
        prev_regions = prev_control.get(faction, set())
        curr_regions = curr_control.get(faction, set())
        lost   = len(prev_regions - curr_regions)
        gained = len(curr_regions - prev_regions)

        deltas = {"militaryPower": 0, "economicPower": 0, "politicalInfluence": 0, "religiousInfluence": 0}

        if lost > 0:
            deltas["militaryPower"]      -= 3 + lost        # frontline shrinks, garrisons lost
            deltas["politicalInfluence"] -= 4 + lost * 2    # loss of territory = loss of legitimacy
            deltas["economicPower"]      -= 2 + lost        # tax base and resources lost
        if gained > 0:
            deltas["militaryPower"]      += 2 * gained
            deltas["politicalInfluence"] += 3 * gained
            deltas["economicPower"]      += 1 * gained

        # Weakly-held or contested locations drain political influence
        _loc_src = new_state.get("locations") or new_state.get("region_control", [])
        faction_regions_detail = [r for r in _loc_src if r.get("controller") == faction]
        # locations use "control"; region_control uses "influence_level"
        weak_holds = sum(
            1 for r in faction_regions_detail
            if int(r.get("control", r.get("influence_level", 50))) < 40
        )
        if weak_holds:
            deltas["politicalInfluence"] -= min(5, weak_holds * 1.5)

        _merge_power_deltas(power_map[faction], deltas)

    # ── 2. WAR OUTCOME SHIFTS ─────────────────────────────────────────────────
    for outcome in new_state.get("war_outcomes", []):
        adv     = float(outcome.get("advantage", 0))
        att_name = outcome.get("attacker", "")
        dft_name = outcome.get("defender", "")
        att = power_map.get(att_name)
        dft = power_map.get(dft_name)

        # Attacker winning: gains tempo, costs economy
        # Defender winning: holds ground, morale + political boost
        if adv > 10:        # attacker clearly winning
            if att:
                _merge_power_deltas(att, {"militaryPower": 2, "politicalInfluence": 2, "economicPower": -2})
            if dft:
                _merge_power_deltas(dft, {"militaryPower": -3, "politicalInfluence": -3, "economicPower": -2, "religiousInfluence": -1})
        elif adv > 3:       # slight attacker edge
            if att:
                _merge_power_deltas(att, {"militaryPower": 1, "economicPower": -1})
            if dft:
                _merge_power_deltas(dft, {"militaryPower": -1, "politicalInfluence": -1, "economicPower": -1})
        elif adv < -10:     # defender clearly winning
            if dft:
                _merge_power_deltas(dft, {"militaryPower": 2, "politicalInfluence": 3, "religiousInfluence": 1})
            if att:
                _merge_power_deltas(att, {"militaryPower": -3, "politicalInfluence": -2, "economicPower": -3})
        elif adv < -3:      # slight defender edge
            if dft:
                _merge_power_deltas(dft, {"militaryPower": 1, "politicalInfluence": 1})
            if att:
                _merge_power_deltas(att, {"militaryPower": -1, "economicPower": -2})
        else:               # evenly matched — both pay attrition
            for name in (att_name, dft_name):
                if name in power_map:
                    _merge_power_deltas(power_map[name], {"economicPower": -1})

        # Attrition warning: critical economy during war accelerates collapse
        if "attrition_warning" in outcome:
            warning_faction = att_name if att_name in outcome["attrition_warning"] else dft_name
            if warning_faction in power_map:
                _merge_power_deltas(power_map[warning_faction],
                                    {"militaryPower": -2, "economicPower": -3})

    # ── 3. INSTABILITY SHIFTS ─────────────────────────────────────────────────
    # Build per-faction aggregates from population_state
    faction_pop: dict = {}
    for p in new_state.get("population_state", []):
        # Match by culture/species to faction — use region_control as bridge
        region = p.get("region", "")
        ctrl   = next(
            (r.get("controller", "") for r in new_state.get("region_control", [])
             if r.get("region") == region),
            ""
        )
        if ctrl:
            faction_pop.setdefault(ctrl, []).append(p)

    for faction, pop_rows in faction_pop.items():
        if faction not in power_map:
            continue
        avg_pressure = sum(p.get("pressure", 50) for p in pop_rows) / len(pop_rows)
        avg_health   = sum(p.get("health",   70) for p in pop_rows) / len(pop_rows)

        deltas: dict = {}
        if avg_pressure > 70:
            deltas = {"militaryPower": -2, "politicalInfluence": -3, "economicPower": -1}
        elif avg_pressure > 55:
            deltas = {"militaryPower": -1, "politicalInfluence": -2}
        elif avg_pressure < 25:
            deltas = {"politicalInfluence": 1}  # stable society slowly strengthens governance

        if avg_health < 50:
            deltas["economicPower"]  = deltas.get("economicPower",  0) - 1
            deltas["militaryPower"]  = deltas.get("militaryPower",  0) - 1

        if deltas:
            _merge_power_deltas(power_map[faction], deltas)

    # ── 4. LEADERSHIP SHIFTS ──────────────────────────────────────────────────
    # Strong leaders slowly lift their dominant axis; dead/absent leadership stagnates
    LEADER_ROLES = {"Leader", "Heir", "Power Role"}
    faction_leaders_map: dict = {}
    for c in new_state.get("house_characters", []):
        if (c.get("coreRole") in LEADER_ROLES
                and not str(c.get("status", "")).lower().startswith("deceased")
                and float(c.get("health", 80)) > 20):
            faction_leaders_map.setdefault(c.get("faction", ""), []).append(c)

    for faction, leaders in faction_leaders_map.items():
        if faction not in power_map:
            continue

        def _avg(field, default=50):
            return sum(int(l.get(field, default)) for l in leaders) / len(leaders)

        avg_warfare  = _avg("warfare")
        avg_diplo    = _avg("diplomacy")
        avg_intrigue = _avg("intrigue")
        avg_faith    = _avg("faith", 20)

        deltas: dict = {}
        # Each axis only shifts when leader skill is clearly above baseline (65 threshold)
        if avg_warfare  > 65: deltas["militaryPower"]      = deltas.get("militaryPower",      0) + round((avg_warfare  - 65) * 0.025)
        if avg_diplo    > 65: deltas["economicPower"]      = deltas.get("economicPower",      0) + round((avg_diplo    - 65) * 0.020)
        if avg_diplo    > 65: deltas["politicalInfluence"] = deltas.get("politicalInfluence", 0) + round((avg_diplo    - 65) * 0.020)
        if avg_intrigue > 65: deltas["politicalInfluence"] = deltas.get("politicalInfluence", 0) + round((avg_intrigue - 65) * 0.018)
        if avg_faith    > 65: deltas["religiousInfluence"] = deltas.get("religiousInfluence", 0) + round((avg_faith    - 65) * 0.025)

        # Depth bonus: more than 2 capable leaders = small resilience bonus
        capable = sum(1 for l in leaders if int(l.get("influenceScore", 0)) > 55)
        if capable >= 3:
            for ax in ("militaryPower", "politicalInfluence"):
                deltas[ax] = deltas.get(ax, 0) + 1

        if deltas:
            _merge_power_deltas(power_map[faction], deltas)

    # ── Reattach modified entries and regenerate power_modifiers ─────────────
    for entry in new_state["faction_power_state"]:
        entry["power_modifiers"] = _compute_power_outcome_modifiers(entry["faction"], new_state)


def _dominance_score(power_entry):
    """Weighted composite of the four power axes into a single 0–100 dominance score.

    Military and political carry more weight — they translate most directly to
    geopolitical control. Economic sustains long-term position. Religious shapes
    soft power and morale but rarely determines outcomes alone.
    """
    mil = int(power_entry.get("militaryPower",      50))
    eco = int(power_entry.get("economicPower",      50))
    pol = int(power_entry.get("politicalInfluence", 50))
    rel = int(power_entry.get("religiousInfluence", 50))
    return round(mil * 0.32 + pol * 0.30 + eco * 0.25 + rel * 0.13, 2)


def _compute_faction_dominance(prev_state, new_state):
    """Build the full dominance ranking from live faction_power_state.

    Returns a dict with:
      rankings[]          — all factions sorted by score, highest first
      dominantFaction     — single leader entry
      risingFactions[]    — sustained upward momentum (trend_momentum > 1.5)
      collapsingFactions[]— sustained downward momentum (trend_momentum < -1.5)

    trend_momentum is a rolling value: 60% of last tick's momentum + 40% of this tick's delta.
    This smooths out single-tick noise — a faction must rise/fall across multiple ticks
    before being labeled rising or collapsing.
    """
    current_power = {e["faction"]: e for e in new_state.get("faction_power_state", [])}
    if not current_power:
        return {"dominantFaction": None, "risingFactions": [], "collapsingFactions": [], "rankings": []}

    # Previous scores and momentum (carried from last tick's dominance state)
    prev_dominance  = prev_state.get("faction_dominance", {})
    prev_rankings   = {r["faction"]: r for r in prev_dominance.get("rankings", [])}
    prev_power_map  = {e["faction"]: e for e in prev_state.get("faction_power_state", [])}

    rankings = []
    for faction, entry in current_power.items():
        score = _dominance_score(entry)

        # Delta vs last tick
        prev_entry  = prev_power_map.get(faction, {})
        prev_score  = _dominance_score(prev_entry) if prev_entry else score
        tick_delta  = round(score - prev_score, 2)

        # Rolling momentum: dampened carry + this tick's signal
        prev_momentum = float(prev_rankings.get(faction, {}).get("trend_momentum", 0.0))
        trend_momentum = round(prev_momentum * 0.60 + tick_delta * 0.40, 3)

        # Trend label from momentum
        if trend_momentum > 4.0:
            trend = "surging"
        elif trend_momentum > 1.5:
            trend = "rising"
        elif trend_momentum > 0.4:
            trend = "gaining"
        elif trend_momentum < -4.0:
            trend = "collapsing"
        elif trend_momentum < -1.5:
            trend = "declining"
        elif trend_momentum < -0.4:
            trend = "weakening"
        else:
            trend = "stable"

        rankings.append({
            "faction":        faction,
            "score":          score,
            "tick_delta":     tick_delta,
            "trend_momentum": trend_momentum,
            "trend":          trend,
            "militaryPower":  entry.get("militaryPower",      50),
            "economicPower":  entry.get("economicPower",      50),
            "politicalInfluence": entry.get("politicalInfluence", 50),
            "religiousInfluence": entry.get("religiousInfluence", 50),
        })

    rankings.sort(key=lambda r: r["score"], reverse=True)

    # Assign rank position
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
        # Track rank change vs last tick
        prev_rank = prev_rankings.get(r["faction"], {}).get("rank")
        if prev_rank is not None:
            r["rank_delta"] = prev_rank - r["rank"]  # positive = moved up
        else:
            r["rank_delta"] = 0

    dominant    = rankings[0] if rankings else None
    rising      = [r for r in rankings if r["trend"] in ("rising", "surging")]
    collapsing  = [r for r in rankings if r["trend"] in ("declining", "collapsing")]

    return {
        "dominantFaction":    dominant,
        "risingFactions":     rising,
        "collapsingFactions": collapsing,
        "rankings":           rankings,
    }


def _plan_war_targets(locations, at_war_with, war_advantage):
    """Determine which locations each attacking faction is actively targeting this tick.

    Priority order for target selection:
      1. Adjacent to attacker's own territory (on the active border)
      2. High strategic value (capital, port, mine, fortress)
      3. Already low control (nearly flipped — finish the job)
      4. Any location controlled by the enemy (distant pressure)

    Returns: {loc_id → {attacker, pressure_bonus, is_primary_target, target_reason}}
    Also returns: war_targets list for state storage (Claude-readable).
    """
    loc_by_name  = {loc["name"]: loc for loc in locations}
    loc_by_id    = {loc["id"]:   loc for loc in locations}

    # Which locations each faction controls
    faction_locs: dict = {}
    for loc in locations:
        ctrl = loc.get("controller", "")
        if ctrl:
            faction_locs.setdefault(ctrl, set()).add(loc.get("name", ""))

    target_map: dict = {}   # loc_id → best attacker entry
    war_targets_list = []   # state storage, readable by Claude

    for attacker, defenders in at_war_with.items():
        attacker_territory = faction_locs.get(attacker, set())

        for defender in defenders:
            if attacker >= defender:
                continue   # process each pair once

            adv = war_advantage.get((attacker, defender), 0)
            def_locations = [loc for loc in locations if loc.get("controller") == defender]

            for loc in def_locations:
                loc_id    = loc.get("id", "")
                adj       = set(loc.get("adjacent", []))
                rtype     = loc.get("region_type", "wilderness")
                value     = int(loc.get("value", 50))
                control   = int(loc.get("control", 50))

                # Is this location on the active border?
                border_adjacent = bool(adj & attacker_territory)

                # Target priority score
                priority  = 0
                reason    = "background pressure"

                if border_adjacent:
                    priority += 40
                    reason    = "active border"

                # High-value types are always priority targets
                if rtype == "capital":
                    priority += 30
                    reason    = "capital assault" if border_adjacent else "capital siege"
                elif rtype in ("fortress", "port", "mine"):
                    priority += 15
                    reason    = f"{rtype} assault" if border_adjacent else f"{rtype} pressure"

                # Strategic value weighting
                priority += value // 5

                # Low-control locations: near-flip, worth pushing
                if control <= 25:
                    priority += 20
                    reason    = "near-capture push"

                # Attacker advantage multiplies pressure on priority targets
                pressure_bonus = 0.0
                if adv > 20:   pressure_bonus = 4.0
                elif adv > 10: pressure_bonus = 2.5
                elif adv > 3:  pressure_bonus = 1.0
                elif adv < -10: pressure_bonus = -1.5  # losing side can't push hard

                is_primary = priority >= 40

                entry = {
                    "attacker":       attacker,
                    "defender":       defender,
                    "priority":       priority,
                    "pressure_bonus": pressure_bonus,
                    "is_primary":     is_primary,
                    "reason":         reason,
                }

                # Only keep the highest-priority attacker per location
                prev = target_map.get(loc_id)
                if prev is None or priority > prev["priority"]:
                    target_map[loc_id] = entry

                if is_primary:
                    war_targets_list.append({
                        "location":   loc.get("name", ""),
                        "attacker":   attacker,
                        "defender":   defender,
                        "reason":     reason,
                        "control":    control,
                    })

    return target_map, war_targets_list


def _update_location_control(new_state):
    """Apply per-tick control changes driven by war targeting and peace recovery.

    War path:
      Conquest is intentionally slow — losing a well-held territory should take
      many ticks of sustained pressure.  Three factors gate how fast control falls:

        1. Region resistance (RESISTANCE table) — fortresses and capitals hold;
           open plains and sea routes fall faster.
        2. Stability resistance — a well-supplied, stable garrison fights harder.
           High stability cuts incoming damage; crumbling stability multiplies it.
        3. Value resistance — strategically important locations have better
           infrastructure, supply lines, and garrison quality.  High-value
           territories take longer to capture than low-value wilderness.

      Base pressures have been reduced from the previous version so that even
      a sustained primary assault on open terrain takes 30–50 ticks, not 13.

    Peace path:
      Stability gates recovery speed.  Stable regions consolidate faster;
      unstable newly-occupied territory recovers slowly.

    Flip:
      At control ≤ 0, the attacker takes over at control 20–35 (weaker foothold
      than before), and stability drops an additional 20.  The new controller
      starts fragile and must invest ticks of consolidation to secure the gain.
    """
    import random

    locations = new_state.get("locations", [])
    if not locations:
        return

    # ── War graph ─────────────────────────────────────────────────────────────
    at_war_with: dict = {}
    for rel in new_state.get("relationships", []):
        if rel.get("type") == "war":
            a, b = rel.get("faction_a", ""), rel.get("faction_b", "")
            if a and b:
                at_war_with.setdefault(a, set()).add(b)
                at_war_with.setdefault(b, set()).add(a)

    war_advantage: dict = {}
    for wo in new_state.get("war_outcomes", []):
        a, d = wo.get("attacker", ""), wo.get("defender", "")
        adv  = float(wo.get("advantage", 0))
        if a and d:
            war_advantage[(a, d)] =  adv
            war_advantage[(d, a)] = -adv

    target_map, war_targets_list = _plan_war_targets(locations, at_war_with, war_advantage)
    new_state["war_targets"] = war_targets_list

    loc_by_name = {loc["name"]: loc for loc in locations}

    # ── Additive control-drop model ───────────────────────────────────────────
    #
    # drop = base + region_mod + stability_mod + value_mod + advantage_mod
    #
    # Each factor is a bounded additive adjustment rather than a multiplier.
    # Prevents extreme multiplicative stacking on well-defended high-value
    # territories that collapsed all scenarios to a 1-per-tick floor.
    #
    # Reference timings (ticks from control=90 under sustained assault):
    #   Plains,  stable garrison,   avg value    ~30-45 ticks
    #   Plains,  crumbling garrison, avg value   ~15-22 ticks
    #   Capital, stable, high-value              90+   ticks  (30+ real days)
    #   Capital, crumbling, dominant attacker    ~30   ticks
    #   Fortress, stable                         90+   ticks  (siege required)
    #   Fortress, crumbling, dominating foe      ~25-35 ticks

    BASE_ACTIVE_PRIMARY = 3.0   # full assault on adjacent primary target
    BASE_SIEGE_PRIMARY  = 1.5   # primary target, no adjacent enemy territory yet
    BASE_BACKGROUND     = 0.8   # at war but not an explicit target

    # Region: negative = harder to take (fortified); positive = easier
    REGION_MOD = {
        "fortress":   -1.5,
        "capital":    -1.2,
        "sacred":     -0.9,
        "city":       -0.6,
        "mine":       -0.4,
        "port":       -0.4,
        "plains":      0.0,
        "wilderness":  0.2,
        "sea":         0.4,
    }

    location_events = list(new_state.get("location_events", []))
    tick = int(new_state.get("tick", 0))

    updated = []
    for loc in locations:
        loc_id         = loc.get("id", "")
        controller     = loc.get("controller", "")
        owner          = loc.get("owner", "")
        control        = int(loc.get("control",   50))
        stability      = int(loc.get("stability", 50))
        rtype          = loc.get("region_type", "wilderness")
        territory_type = loc.get("territory_type", "wild")
        adjacent       = loc.get("adjacent", [])
        value          = int(loc.get("value", 50))

        enemies         = at_war_with.get(controller, set())
        target_entry    = target_map.get(loc_id)
        active_fighting = False

        if enemies:
            # ── Active-fighting check ─────────────────────────────────────────
            for adj_name in adjacent:
                adj_loc = loc_by_name.get(adj_name)
                if adj_loc and adj_loc.get("controller") in enemies:
                    active_fighting = True
                    break

            # ── Base drop from tactical situation ─────────────────────────────
            if target_entry:
                attacker = target_entry["attacker"]
                if target_entry["is_primary"]:
                    base = BASE_ACTIVE_PRIMARY if active_fighting else BASE_SIEGE_PRIMARY
                else:
                    base = BASE_BACKGROUND
                adv_bonus = target_entry["pressure_bonus"]
            else:
                attacker  = next(iter(enemies), None)
                base      = BASE_BACKGROUND * 0.75
                adv_bonus = 0.0

            # ── Region modifier ───────────────────────────────────────────────
            region_mod = REGION_MOD.get(rtype, 0.0)
            if territory_type == "fortress":
                region_mod -= 0.5   # stacks with region_type

            # ── Stability modifier (key mechanic: high stab = slower loss) ────
            if stability >= 70:   stab_mod = -1.2   # disciplined, well-supplied
            elif stability >= 50: stab_mod = -0.5
            elif stability >= 30: stab_mod =  0.0
            elif stability >= 15: stab_mod = +0.9   # morale breaking
            else:                 stab_mod = +1.7   # near-collapse

            # ── Value modifier (high value = better defended) ─────────────────
            if value >= 80:   val_mod = -0.6
            elif value >= 60: val_mod = -0.3
            else:             val_mod =  0.0

            # ── Attacker advantage ────────────────────────────────────────────
            adv_mod = min(1.5, max(-1.0, adv_bonus * 0.35))

            # ── Final drop ────────────────────────────────────────────────────
            drop = max(1, round(base + region_mod + stab_mod + val_mod + adv_mod))

            control   = max(0, control   - drop)
            stability = max(0, stability - (2 if active_fighting else 1))

            # ── CONTROL FLIP ─────────────────────────────────────────────────
            if control <= 0 and attacker:
                prev_controller = controller
                controller      = attacker
                control         = random.randint(20, 32)   # fragile foothold
                stability       = max(0, stability - 20)
                active_fighting = False
                location_events.append({
                    "type":        "territory_captured",
                    "location":    loc.get("name", ""),
                    "region_type": rtype,
                    "captured_by": attacker,
                    "lost_by":     prev_controller,
                    "tick":        tick,
                })
                if territory_type == "capital":
                    location_events.append({
                        "type":        "capital_captured",
                        "location":    loc.get("name", ""),
                        "captured_by": attacker,
                        "lost_by":     prev_controller,
                        "tick":        tick,
                    })

        else:
            # ── PEACE: stability-gated consolidation ──────────────────────────
            if stability >= 70:   recovery = 4
            elif stability >= 50: recovery = 3
            elif stability >= 30: recovery = 2
            else:                 recovery = 1   # fragile occupation — slow

            if owner == controller:                          recovery += 1
            if rtype in ("capital", "fortress", "city"):    recovery += 1
            if territory_type == "wild":                    recovery = max(0, recovery - 1)

            control   = min(100, control   + recovery)
            stability = min(100, stability + 1)

        contested = active_fighting or (owner != controller) or (control < 40)

        updated.append({
            **loc,
            "controller":      controller,
            "control":         max(0, min(100, control)),
            "stability":       max(0, min(100, stability)),
            "contested":       contested,
            "active_fighting": active_fighting,
        })

    new_state["locations"]       = updated
    new_state["location_events"] = location_events


def _update_location_stability(new_state):
    """Apply economy and leadership modifiers to stability, then evaluate unrest/rebellion thresholds.

    Economy (per controller's faction_power_state):
      economicPower < 30  → -2/tick   collapse: unpaid garrisons, food shortages
      economicPower < 50  → -1/tick   struggling economy erodes confidence
      economicPower > 70  → +1/tick   prosperity reinforces social order

    Leadership (per controller's ruler skills):
      diplomacy > 65  → +1/tick   competent administration addresses grievances
      diplomacy < 35  → -1/tick   misrule breeds resentment
      warfare > 65 AND unrest zone → +1   military presence suppresses open revolt

    Thresholds:
      stability < 30  → unrest = True; control recovery reduced by 1
      stability < 15  → rebellion_risk = True; 25% chance of rebellion fires if not already in rebellion
      stability > 80  → +1 control/tick in peaceful territory

    Rebellion trigger stamps: in_rebellion, original_controller, rebel_faction, rebellion_tick_started.
    Ongoing rebellion effects (rapid drop, power loss, faction emergence) handled by _process_rebellions.
    """
    import random

    locations   = new_state.get("locations", [])
    current_tick = int(new_state.get("tick", 0))
    if not locations:
        return

    eco_by_faction = {
        fp.get("faction"): int(fp.get("economicPower", 50))
        for fp in new_state.get("faction_power_state", [])
        if fp.get("faction")
    }

    diplo_by_faction   = {}
    warfare_by_faction = {}
    for entry in new_state.get("leadership_state", []):
        faction = entry.get("faction", "")
        ruler   = entry.get("currentRuler", {})
        if faction and ruler:
            diplo_by_faction[faction]   = int(ruler.get("diplomacy", 50))
            warfare_by_faction[faction] = int(ruler.get("warfare",   50))

    location_events = list(new_state.get("location_events", []))

    updated = []
    for loc in locations:
        controller      = loc.get("controller", "")
        owner           = loc.get("owner", "")
        stability       = int(loc.get("stability", 50))
        control         = int(loc.get("control",   50))
        name            = loc.get("name", "")
        active_fighting = loc.get("active_fighting", False)
        already_rebel   = loc.get("in_rebellion", False)
        territory_type  = loc.get("territory_type", "wild")

        # ── WILD ENTROPY ──────────────────────────────────────────────────────
        # Frontier and ungoverned land is naturally unstable
        if territory_type == "wild" and not already_rebel:
            stability = max(0, stability - 1)

        # ── ECONOMY MODIFIER ─────────────────────────────────────────────────
        eco = eco_by_faction.get(controller, 50)
        if eco < 30:
            stability -= 2
        elif eco < 50:
            stability -= 1
        elif eco > 70:
            stability += 1

        # ── LEADERSHIP MODIFIER ───────────────────────────────────────────────
        diplo   = diplo_by_faction.get(controller, 50)
        warfare = warfare_by_faction.get(controller, 50)

        if diplo > 65:
            stability += 1
        elif diplo < 35:
            stability -= 1

        stability = max(0, min(100, stability))

        if stability < 30 and warfare > 65:
            stability = min(100, stability + 1)

        # ── THRESHOLD FLAGS ───────────────────────────────────────────────────
        unrest         = stability < 30
        rebellion_risk = stability < 15

        # ── REBELLION TRIGGER ─────────────────────────────────────────────────
        # Only fires if not already in rebellion; _process_rebellions handles ongoing effects
        # Territory type controls how easily a garrison can be overwhelmed
        REBEL_CHANCE = {"wild": 0.45, "city": 0.25, "fortress": 0.12, "capital": 0.12}
        trigger_chance = REBEL_CHANCE.get(territory_type, 0.25)

        rebellion_fields = {}
        if rebellion_risk and not already_rebel and random.random() < trigger_chance:
            original_controller = controller
            rebel_faction       = owner if (owner and owner != controller) else "Rebels"
            rebellion_fields = {
                "in_rebellion":            True,
                "original_controller":     original_controller,
                "rebel_faction":           rebel_faction,
                "rebellion_tick_started":  current_tick,
                "rebellion_intensity":     30,
            }
            controller = rebel_faction
            control    = random.randint(15, 25)
            stability  = min(100, stability + 5)
            location_events.append({
                "type":                 "rebellion_triggered",
                "location":             name,
                "from_controller":      original_controller,
                "to_controller":        rebel_faction,
                "stability_at_trigger": stability,
                "tick":                 current_tick,
            })

        # ── STABILITY-DRIVEN CONTROL ADJUSTMENTS (peace only) ────────────────
        if not active_fighting and not already_rebel:
            if stability > 80:
                control = min(100, control + 1)
            if unrest:
                control = max(0, control - 1)

        contested = active_fighting or already_rebel or (owner != controller) or (control < 40)

        updated.append({
            **loc,
            **rebellion_fields,
            "controller":     controller,
            "control":        max(0, min(100, control)),
            "stability":      stability,
            "unrest":         unrest,
            "rebellion_risk": rebellion_risk,
            "contested":      contested,
        })

    new_state["locations"]       = updated
    new_state["location_events"] = location_events


def _process_rebellions(new_state):
    """Apply ongoing per-tick effects for every location with in_rebellion = True.

    Each rebelling location:
      - Grows rebellion_intensity by 3/tick (base 30 → cap 100)
      - Control drops max(3, round(intensity × 0.07)) per tick
      - original_controller faction loses: militaryPower -1, politicalInfluence -2, economicPower -1
      - After 30 ticks at intensity ≥ 70: a new rebel faction is logged in emerging_factions[]
      - At control = 0: controller flips to rebel_faction (rebellion_victory)

    Resolution:
      - stability > 35: order restored → in_rebellion clears (rebellion_suppressed)
      - control > 60 while controller ≠ rebel_faction: uprising broken → in_rebellion clears
    """
    import random

    locations    = new_state.get("locations", [])
    current_tick = int(new_state.get("tick", 0))
    if not locations:
        return

    # Mutable power lookup so we can drain the losing faction in-place
    power_by_faction = {
        fp.get("faction"): fp
        for fp in new_state.get("faction_power_state", [])
        if fp.get("faction")
    }

    emerging_factions = list(new_state.get("emerging_factions", []))
    already_emerging  = {ef.get("location") for ef in emerging_factions}
    location_events   = list(new_state.get("location_events", []))

    updated = []
    for loc in locations:
        if not loc.get("in_rebellion"):
            updated.append(loc)
            continue

        controller          = loc.get("controller", "")
        owner               = loc.get("owner", "")
        original_controller = loc.get("original_controller", controller)
        rebel_faction       = loc.get("rebel_faction", "Rebels")
        rebellion_start     = int(loc.get("rebellion_tick_started", current_tick))
        control             = int(loc.get("control",   30))
        stability           = int(loc.get("stability", 10))
        name                = loc.get("name", "")
        active_fighting     = loc.get("active_fighting", False)

        tick_age  = max(0, current_tick - rebellion_start)
        intensity = min(100, 30 + tick_age * 3)

        # ── CONTROL DROP ──────────────────────────────────────────────────────
        drop    = max(3, round(intensity * 0.07))
        control = max(0, control - drop)

        # ── FACTION POWER DRAIN ────────────────────────────────────────────────
        losing = original_controller if original_controller != rebel_faction else owner
        fp = power_by_faction.get(losing)
        if fp:
            fp["militaryPower"]      = max(0, int(fp.get("militaryPower",      50)) - 1)
            fp["politicalInfluence"] = max(0, int(fp.get("politicalInfluence", 50)) - 2)
            fp["economicPower"]      = max(0, int(fp.get("economicPower",      50)) - 1)

        # ── NEW FACTION EMERGENCE ─────────────────────────────────────────────
        if tick_age >= 30 and intensity >= 70 and name not in already_emerging:
            already_emerging.add(name)
            suggested = f"Free {name} Movement"
            emerging_factions.append({
                "location":       name,
                "origin_faction": original_controller,
                "tick_emerged":   current_tick,
                "intensity":      intensity,
                "suggested_name": suggested,
            })
            location_events.append({
                "type":     "faction_emergence",
                "location": name,
                "detail":   (
                    f"The rebellion in {name} has persisted for {tick_age} ticks at intensity {intensity}. "
                    f"An organized rebel faction — tentatively called '{suggested}' — is crystallizing "
                    f"from the uprising against {original_controller}."
                ),
                "tick": current_tick,
            })

        # ── FULL CONTROL FLIP ─────────────────────────────────────────────────
        if control <= 0:
            controller = rebel_faction
            control    = random.randint(25, 40)
            location_events.append({
                "type":            "rebellion_victory",
                "location":        name,
                "new_controller":  rebel_faction,
                "lost_by":         original_controller,
                "tick_age":        tick_age,
                "tick":            current_tick,
            })

        # ── RESOLUTION CHECK ─────────────────────────────────────────────────
        in_rebellion = True
        if stability > 35:
            in_rebellion = False
            location_events.append({
                "type":     "rebellion_suppressed",
                "location": name,
                "tick_age": tick_age,
                "tick":     current_tick,
            })
        elif control > 60 and controller != rebel_faction:
            in_rebellion = False

        contested = active_fighting or in_rebellion or (owner != controller) or (control < 40)

        updated.append({
            **loc,
            "controller":            controller,
            "control":               max(0, min(100, control)),
            "in_rebellion":          in_rebellion,
            "rebel_faction":         rebel_faction if in_rebellion else loc.get("rebel_faction", ""),
            "rebellion_tick_started": rebellion_start if in_rebellion else None,
            "original_controller":   original_controller,
            "rebellion_intensity":   intensity if in_rebellion else 0,
            "contested":             contested,
        })

    new_state["locations"]         = updated
    new_state["emerging_factions"] = emerging_factions
    new_state["location_events"]   = location_events


def _merge_power_deltas(entry, deltas):
    """Apply a delta dict to a faction power entry, clamping each axis to 0–100."""
    AXES = ("militaryPower", "economicPower", "politicalInfluence", "religiousInfluence")
    for ax in AXES:
        if ax in deltas:
            entry[ax] = max(0, min(100, int(entry.get(ax, 50)) + int(deltas[ax])))


def _default_locations():
    """Seed data for all known locations. owner/controller start as the same faction."""
    return [
        # id, name, owner, controller, control, stability, population, value, region_type, adjacent[]
        ("twin-cities",     "Twin Cities",     "Twin Cities",       "Twin Cities",       82, 74, 140000, 88, "capital",   ["Tidefall", "Dur Khadur", "Faerwood", "Eldoria"]),
        ("eldoria",         "Eldoria",         "Twin Cities",       "Twin Cities",       76, 70, 95000,  78, "city",      ["Twin Cities", "Tidefall", "Faerwood", "Varkuun"]),
        ("tidefall",        "Tidefall",        "Tidefall",          "Tidefall",          78, 68, 160000, 82, "port",      ["Twin Cities", "Eldoria", "Dreadwind Isles", "Varkuun"]),
        ("dur-khadur",      "Dur Khadur",      "Dur Khadur",        "Dur Khadur",        84, 74, 115000, 80, "fortress",  ["Lostfeld", "Gilgeth", "Groth"]),
        ("lostfeld",        "Lostfeld",        "Lostfeld",          "Lostfeld",          78, 72, 65000,  72, "mine",      ["Dur Khadur", "Gilgeth", "Groth", "Stonebreak", "Wintermark"]),
        ("faerwood",        "Faerwood",        "Shadow Court",      "Shadow Court",      76, 55, 30000,  65, "fortress",  ["Twin Cities", "Glenhaven", "Eldoria"]),
        ("glenhaven",       "Glenhaven",       "Glenhaven",         "Glenhaven",         74, 80, 35000,  62, "wilderness",["Faerwood", "Tidefall", "Stonebreak"]),
        ("frostvale",       "Frostvale",       "The Wintermark",    "The Wintermark",    70, 62, 42000,  58, "fortress",  ["Lostfeld", "Twin Cities", "Groth"]),
        ("gilgeth",         "Gilgeth",         "Gilgeth Clans",     "Gilgeth Clans",     72, 50, 60000,  58, "fortress",  ["Groth", "Dur Khadur", "Lostfeld", "Vilefin"]),
        ("groth",           "Groth",           "Groth Clans",       "Groth Clans",       68, 38, 40000,  52, "wilderness",["Gilgeth", "Frostvale", "Dur Khadur"]),
        ("vilefin",         "Vilefin",         "Vilefin",           "Vilefin",           58, 38, 215000, 48, "plains",    ["Gilgeth", "Twin Cities", "Varkuun"]),
        ("dreadwind-isles", "Dreadwind Isles", "Dreadwind Isles",   "Dreadwind Isles",   62, 38, 45000,  62, "port",      ["Tidefall", "Open Sea"]),
        ("varkuun",         "Varkuun",         "Varkuun",           "Varkuun",           80, 72, 18000,  70, "fortress",  ["Tidefall", "Eldoria", "Twin Cities", "Vilefin"]),
        ("stonebreak",      "Stonebreak",      "Stonebreak Monastery","Stonebreak Monastery",88, 90, 5500, 58, "sacred",  ["Lostfeld", "Glenhaven"]),
        ("open-sea",        "Open Sea",        "Tidefall",          "Dreadwind Isles",    35, 30, 0,     70, "sea",       ["Tidefall", "Dreadwind Isles"]),
    ]


def _normalize_locations(prev_state, new_state):
    """Unified territory state — merges region_control and population_state concepts.

    Schema per location:
      id             — stable slug identifier
      name           — display name
      owner          — faction claiming political sovereignty
      controller     — faction with actual military/administrative hold
      control        — 0–100: how firmly the controller holds it
      stability      — 0–100: social and political stability
      population     — integer headcount
      value          — 0–100: strategic importance (trade, fortress, sacred, resources)
      region_type    — capital | port | fortress | mine | wilderness | plains | sea | sacred | city
      territory_type — city | fortress | wild | capital  (derived from region_type; drives behavioral rules)
      adjacent       — list of neighboring location names
      contested      — bool: owner != controller OR control < 40
    """
    REGION_TO_TERRITORY = {
        "capital":    "capital",
        "city":       "city",
        "port":       "city",
        "sacred":     "city",
        "fortress":   "fortress",
        "mine":       "wild",
        "wilderness": "wild",
        "plains":     "wild",
        "sea":        "wild",
    }

    prev_rows = {r.get("id"): r for r in prev_state.get("locations", []) if r.get("id")}

    # Also index AI output by id or by name for matching
    incoming_by_id   = {r.get("id"):   r for r in new_state.get("locations", []) if r.get("id")}
    incoming_by_name = {r.get("name"): r for r in new_state.get("locations", []) if r.get("name")}

    # Pull live population from population_state for accuracy
    pop_by_region = {p.get("region"): int(p.get("population", 0))
                     for p in new_state.get("population_state", [])}

    rows = []
    seen = set()

    for (lid, name, owner_seed, ctrl_seed, ctrl_val, stab_val,
         pop_seed, value_seed, rtype, adjacent) in _default_locations():

        if lid in seen:
            continue
        seen.add(lid)

        prev = prev_rows.get(lid, {})
        ai   = incoming_by_id.get(lid) or incoming_by_name.get(name) or {}

        # Owner and controller — prefer AI update, then prev, then seed
        owner      = (ai.get("owner")      or prev.get("owner")      or owner_seed).strip()
        controller = (ai.get("controller") or prev.get("controller") or ctrl_seed).strip()

        # Numeric fields — clamp and cap single-tick change at ±10
        def _merge(field, ai_val, prev_val, seed_val, cap=10):
            raw = int(ai.get(field, ai_val) if field in ai else (prev.get(field, prev_val) if field in prev else seed_val))
            raw = max(0, min(100, raw))
            pv  = int(prev.get(field, seed_val))
            return max(pv - cap, min(pv + cap, raw))

        control    = _merge("control",   ctrl_val, ctrl_val, ctrl_val)
        stability  = _merge("stability", stab_val, stab_val, stab_val)
        value      = int(ai.get("value", prev.get("value", value_seed)))
        value      = max(0, min(100, value))

        # Population: prefer live population_state, then AI, then prev, then seed
        population = (pop_by_region.get(name)
                      or int(ai.get("population", prev.get("population", pop_seed))))

        # Contested: owner ≠ controller or control < 40
        contested = (owner != controller) or (control < 40)

        resolved_rtype = ai.get("region_type", prev.get("region_type", rtype))
        rows.append({
            "id":             lid,
            "name":           name,
            "owner":          owner,
            "controller":     controller,
            "control":        control,
            "stability":      stability,
            "population":     population,
            "value":          value,
            "region_type":    resolved_rtype,
            "territory_type": (ai.get("territory_type")
                               or prev.get("territory_type")
                               or REGION_TO_TERRITORY.get(resolved_rtype, "wild")),
            "adjacent":       ai.get("adjacent", prev.get("adjacent", adjacent)),
            "contested":      contested,
        })

    # Accept AI-created locations not in the seed (newly discovered, named in events)
    existing_names = {r["name"] for r in rows}
    for ai_row in new_state.get("locations", []):
        if ai_row.get("name") in existing_names or not ai_row.get("name"):
            continue
        lid = ai_row.get("id") or ai_row["name"].lower().replace(" ", "-")
        rows.append({
            "id":          lid,
            "name":        ai_row["name"],
            "owner":       ai_row.get("owner", "Unknown"),
            "controller":  ai_row.get("controller", ai_row.get("owner", "Unknown")),
            "control":     max(0, min(100, int(ai_row.get("control", 50)))),
            "stability":   max(0, min(100, int(ai_row.get("stability", 50)))),
            "population":     max(0, int(ai_row.get("population", 0))),
            "value":          max(0, min(100, int(ai_row.get("value", 40)))),
            "region_type":    ai_row.get("region_type", "wilderness"),
            "territory_type": (ai_row.get("territory_type")
                               or REGION_TO_TERRITORY.get(ai_row.get("region_type", "wilderness"), "wild")),
            "adjacent":       ai_row.get("adjacent", []),
            "contested":      (ai_row.get("owner", "") != ai_row.get("controller", ""))
                              or int(ai_row.get("control", 50)) < 40,
        })

    new_state["locations"] = rows[:40]


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
    VALID_TYPES = {"alliance", "rivalry", "neutral", "war"}

    prev_rows: dict = {}
    prev_rels = prev_state.get("relationships", [])
    # Guard: prev_state might have relationships as a dict (old format) — skip it
    if isinstance(prev_rels, list):
        for row in prev_rels:
            if not isinstance(row, dict):
                continue
            a = row.get("faction_a")
            b = row.get("faction_b")
            if a and b:
                prev_rows[tuple(sorted((a, b)))] = row

    # Build a lookup of each faction's leaders from prev_state house_characters
    # (prev_state is stable; new_state chars are still being processed downstream)
    LEADER_ROLES = {"Leader", "Heir", "Power Role"}
    faction_leaders: dict = {}
    for c in prev_state.get("house_characters", []):
        if c.get("coreRole") in LEADER_ROLES and not str(c.get("status", "")).lower().startswith("deceased"):
            faction_leaders.setdefault(c.get("faction", ""), []).append(c)

    def _leader_relationship_signal(faction_a, faction_b):
        """Average trust/fear/respect of faction_a leaders toward faction_b leaders."""
        leaders_a = faction_leaders.get(faction_a, [])
        leaders_b = {c["name"] for c in faction_leaders.get(faction_b, []) if c.get("name")}
        if not leaders_a or not leaders_b:
            return None
        t_vals, f_vals, r_vals = [], [], []
        for leader in leaders_a:
            rels = leader.get("relationships") or {}
            for name in leaders_b:
                rel = rels.get(name)
                if rel:
                    t_vals.append(float(rel.get("trust",   40)))
                    f_vals.append(float(rel.get("fear",    20)))
                    r_vals.append(float(rel.get("respect", 35)))
        if not t_vals:
            return None
        return {
            "trust":   sum(t_vals) / len(t_vals),
            "fear":    sum(f_vals) / len(f_vals),
            "respect": sum(r_vals) / len(r_vals),
        }

    normalized = []
    seen: set = set()
    for row in new_state.get("relationships", []):
        if not isinstance(row, dict):
            continue
        a = (row.get("faction_a") or "").strip()
        b = (row.get("faction_b") or "").strip()
        if not a or not b or a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)

        prev = prev_rows.get(key, {})

        # ── Base values: clamp AI output and cap single-tick change at ±15 ──
        trust         = max(0, min(100, int(row.get("trust",         prev.get("trust",         50)))))
        hostility     = max(0, min(100, int(row.get("hostility",     prev.get("hostility",     20)))))
        alliance_level = max(0, min(100, int(row.get("alliance_level", prev.get("alliance_level", 0)))))

        if isinstance(prev.get("trust"), int):
            trust         = max(prev["trust"]         - 15, min(prev["trust"]         + 15, trust))
        if isinstance(prev.get("hostility"), int):
            hostility     = max(prev["hostility"]     - 15, min(prev["hostility"]     + 15, hostility))
        if isinstance(prev.get("alliance_level"), int):
            alliance_level = max(prev["alliance_level"] - 10, min(prev["alliance_level"] + 10, alliance_level))

        relation_type = row.get("type", prev.get("type", "neutral"))
        if relation_type not in VALID_TYPES:
            relation_type = "neutral"

        # ── Hard event impacts ────────────────────────────────────────────────
        if relation_type == "war":
            hostility     = max(hostility, 75)
            trust         = min(trust, 20)
            alliance_level = max(0, alliance_level - 20)
        elif relation_type == "alliance":
            trust         = max(trust, 60)
            hostility     = min(hostility, 35)
            alliance_level = max(alliance_level, 55)

        # ── Leader-relationship influence (blended at 25% weight) ───────────
        sig = _leader_relationship_signal(a, b) or _leader_relationship_signal(b, a)
        if sig:
            leader_trust   = sig["trust"]
            leader_fear    = sig["fear"]
            leader_respect = sig["respect"]
            # Trust: leader trust pulls faction trust toward it
            trust      = round(trust      * 0.75 + leader_trust   * 0.25)
            # Hostility: high leader fear suppresses hostility; low leader respect raises it
            fear_suppression = (leader_fear - 20) * 0.10   # fear of other side → avoid conflict
            disrespect_drive = max(0, (35 - leader_respect) * 0.08)
            hostility  = round(max(0, min(100, hostility - fear_suppression + disrespect_drive)))
            # Alliance level: high leader trust + high respect → stronger alliance pull
            alliance_pull = ((leader_trust - 40) * 0.08) + ((leader_respect - 35) * 0.05)
            alliance_level = round(max(0, min(100, alliance_level + alliance_pull)))

        # ── Decay toward neutral (unreinforced relations drift back) ─────────
        # Neutral baselines: trust→50, hostility→20, alliance_level→0
        trust          = round(trust          + (50 - trust)          * 0.015)
        hostility      = round(hostility      + (20 - hostility)      * 0.012)
        alliance_level = round(alliance_level + (0  - alliance_level) * 0.010)

        # ── Clamp finals ─────────────────────────────────────────────────────
        trust          = max(0, min(100, trust))
        hostility      = max(0, min(100, hostility))
        alliance_level = max(0, min(100, alliance_level))

        normalized.append({
            "faction_a":     a,
            "faction_b":     b,
            "type":          relation_type,
            "intensity":     max(1, min(10, int(row.get("intensity", prev.get("intensity", 5))))),
            "trust":         trust,
            "hostility":     hostility,
            "alliance_level": alliance_level,
        })

    new_state["relationships"] = normalized[:30]


def _normalize_faction_identities(new_state):
    fi = new_state.get("faction_identities")
    # Dict format (static identity data set at world creation) — preserve as-is.
    # Claude returns [] for this field; ensure_world_structure restores the dict.
    if isinstance(fi, dict):
        return
    # Array format — normalize each row
    identities = []
    for row in (fi or []):
        if not isinstance(row, dict):
            continue
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
        "Eldoria",
        "Stonebreak",
        "Lostfeld",
        "Tidefall",
        "Faerwood",
        "Glenhaven",
        "Wintermark",
        "Frostvale",
        "Dreadwind Isles",
        "Varkuun",
        "Dur Khadur",
        "Vilefin",
        "Groth",
        "Gilgeth",
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
            "currentRuler": ruler("Eldaric Aurand III", "High King", "House Aurand", 54, "inheritance", ["centralizing", "tradition-bound"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Aurand", "Twin Cities", 1, 82, "Aurand the Unifier", ["High King Eldaric Aurand III"]),
                dynasty("House Braafhart", "Twin Cities", 2, 65, "Aldric Braafhart"),
                dynasty("House LeFleur", "Twin Cities", 2, 61, "Celeste LeFleur"),
                dynasty("House Bower", "Twin Cities", 3, 44, "Old Bower"),
                dynasty("House Binx", "Twin Cities", 3, 38, "Tallo Binx"),
                dynasty("House Dale", "Twin Cities", 3, 41, "Nera Dale"),
            ],
        },
        {
            "faction": "Tidefall",
            "currentRuler": ruler("Levi Ver Meer", "Grand Admiral", "House Ver Meer", 48, "appointment", ["naval", "shrewd"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Ver Meer", "Tidefall", 1, 80, "Admiral Joren Ver Meer", ["Grand Admiral Levi Ver Meer"]),
                dynasty("House Highland-Dusken", "Tidefall", 2, 62, "Highland-Dusken the Elder"),
                dynasty("House Fish", "Tidefall", 2, 54, "Old Maren Fish"),
                dynasty("House McGowan", "Tidefall", 3, 46, "Bren McGowan"),
            ],
        },
        {
            "faction": "Dur Khadur",
            "currentRuler": ruler("Seran Gross", "Trade Prince", "House Gross", 49, "election", ["commercial", "calculating"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Gross", "Dur Khadur", 1, 76, "Edric Gross", ["Trade Prince Seran Gross"]),
                dynasty("House Delonious", "Dur Khadur", 2, 60, "Aldric Delonious"),
                dynasty("House Galfazzar", "Dur Khadur", 2, 57, "Mira Galfazzar"),
                dynasty("House Vercenti", "Dur Khadur", 3, 43, "Vercenti the Merchant"),
            ],
        },
        {
            "faction": "Lostfeld",
            "currentRuler": ruler("Babadu Goldfinger-Duke", "High Thane", "Clan Goldfinger-Duke", 218, "inheritance", ["coin-wise", "deliberate"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("Clan Goldfinger-Duke", "Lostfeld", 1, 78, "Orik Goldfinger-Duke", ["High Thane Babadu Goldfinger-Duke"]),
                dynasty("Clan Runewarden", "Lostfeld", 2, 68, "Dhorin Runewarden"),
                dynasty("Clan Ironmaul", "Lostfeld", 2, 64, "Brammir Ironmaul"),
            ],
        },
        {
            "faction": "Shadow Court",
            "currentRuler": ruler("Lyathra the Veiled", "Queen", "House Verlorn", 412, "seizure of power", ["manipulative", "patient"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Verlorn", "Shadow Court", 1, 90, "Verlorn the First", ["Queen Lyathra the Veiled"]),
                dynasty("House Nightborn", "Shadow Court", 2, 70, "Nightborn of the Abyss"),
                dynasty("House Shadowveil", "Shadow Court", 2, 65, "Shadowveil the Quiet"),
            ],
        },
        {
            "faction": "Glenhaven",
            "currentRuler": ruler("Thalorien Wood", "High Sovereign", "House Wood", 312, "council vote", ["council-guided", "defensive"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Wood", "Glenhaven", 1, 82, "Thalorien the Ancient", ["High Sovereign Thalorien Wood"]),
                dynasty("House Darkleaf", "Glenhaven", 2, 65, "Darkleaf the Keeper"),
                dynasty("House Mistafae", "Glenhaven", 2, 58, "Mistafae Elder"),
            ],
        },
        {
            "faction": "Gilgeth Clans",
            "currentRuler": ruler("Kragor Blackblood", "High Warlord", "Clan Blackblood", 46, "election", ["disciplined", "proud"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("Clan Blackblood", "Gilgeth Clans", 1, 68, "First Blackblood", ["High Warlord Kragor Blackblood"]),
                dynasty("Clan Ironhide", "Gilgeth Clans", 2, 60, "Ironhide Elder"),
                dynasty("Clan Redtusk", "Gilgeth Clans", 2, 54, "Redtusk the War-Scarred"),
            ],
        },
        {
            "faction": "Groth Clans",
            "currentRuler": ruler("Drogath Mijid", "Warchief", "Clan Mijid", 38, "seizure of power", ["aggressive", "strength-bound"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("Clan Mijid", "Groth Clans", 1, 62, "First Mijid", ["Warchief Drogath Mijid"]),
                dynasty("Clan Ashfang", "Groth Clans", 2, 55, "Ashfang the Smoke-Elder"),
                dynasty("Clan Syncar", "Groth Clans", 2, 50, "Syncar the Wild"),
            ],
        },
        {
            "faction": "Vilefin",
            "currentRuler": ruler("Grikk Bloodware", "Speaker", "Clan Bloodware", 22, "post-collapse emergence", ["flexible", "communal"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("Clan Bloodware", "Vilefin", 2, 44, "The First Bloodware", ["Speaker Grikk Bloodware"]),
                dynasty("Clan Cogtooth", "Vilefin", 2, 38, "Cogtooth Elder"),
                dynasty("Clan Rustfang", "Vilefin", 3, 30, "Rustfang Scavenger"),
            ],
        },
        {
            "faction": "The Wintermark",
            "currentRuler": ruler("Kaelen Adkison", "High Lord", "House Adkison", 44, "inheritance", ["stoic", "enduring"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Adkison", "The Wintermark", 1, 72, "Mara Adkison", ["High Lord Kaelen Adkison"]),
                dynasty("House McIntosh", "The Wintermark", 2, 58, "Old McIntosh"),
                dynasty("House Holter", "The Wintermark", 2, 54, "Holter the Frost-Warden"),
                dynasty("House Duval", "The Wintermark", 3, 44, "Duval the Survivor"),
            ],
        },
        {
            "faction": "Varkuun",
            "currentRuler": ruler("Ashali Van Cleave", "High Marshal", "House Van Cleave", 41, "appointment", ["tactical", "mercenary-born"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Van Cleave", "Varkuun", 1, 74, "Calven Van Cleave", ["High Marshal Ashali Van Cleave"]),
            ],
        },
        {
            "faction": "Dreadwind Isles",
            "currentRuler": ruler("Ronan Blacktide", "Captain", "House Blacktide", 34, "seizure of power", ["restless", "vengeance-driven"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("House Blacktide", "Dreadwind Isles", 1, 58, "The Exiled Lord", ["Captain Ronan Blacktide"]),
                dynasty("House Stormvane", "Dreadwind Isles", 2, 48, "Stormvane the Raider"),
                dynasty("House Saltbreach", "Dreadwind Isles", 2, 44, "Saltbreach the Corsair"),
            ],
        },
        {
            "faction": "Stonebreak Monastery",
            "currentRuler": ruler("Varak", "Grand Druid", "Druid Circle", 67, "chosen", ["ancient-minded", "inscrutable"]),
            "rulerHistory": [],
            "dynasties": [
                dynasty("Druid Circle", "Stonebreak Monastery", 2, 62, "The First Grove"),
            ],
        },
    ]


def _normalize_reign(row, current_tick, active=True):
    def clean_name(name, title):
        name = (name or "Unknown Ruler").strip()
        title = (title or "").strip()
        placeholders = {
            "the admiral": "Levi Ver Meer",
            "the dark council": "Seran Gross",
            "groth chieftain": "Drogath Mijid",
            "gilgeth elder council": "Kragor Blackblood",
            "grikk": "Grikk Bloodware",
            "ronan": "Ronan Blacktide",
            "varak": "Varak",
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


_FACTION_ALIASES = {
    "Dreadwind":          "Dreadwind Isles",
    "Dreadwind Islands":  "Dreadwind Isles",
    "Dreadwind Compact":  "Dreadwind Isles",
    "Gilgeth Orcs":       "Gilgeth Clans",
    "Glenhaven Elves":    "Glenhaven",
    "Groth Orcs":         "Groth Clans",
    "Vilefin Goblins":    "Vilefin",
    "Lostfeld Dwarves":   "Lostfeld",
    "Monastery of Druids":"Stonebreak Monastery",
    "Farrock":            "Varkuun",
    "Red Banner Legion":  "Varkuun",
    "Frostvale":          "The Wintermark",
    "Wintermark":         "The Wintermark",
}

def _normalize_leadership_state(prev_state, new_state):
    current_tick = int(new_state.get("tick", prev_state.get("tick", 0) if prev_state else 0))
    defaults = {row["faction"]: row for row in _default_leadership_state()}

    def _alias_rows(rows):
        out = []
        for row in rows:
            name = row.get("faction", "")
            if name in _FACTION_ALIASES:
                row = {**row, "faction": _FACTION_ALIASES[name]}
            out.append(row)
        return out

    prev_rows = {
        row.get("faction"): row
        for row in _alias_rows(prev_state.get("leadership_state", []))
        if row.get("faction")
    }
    incoming_rows = {
        row.get("faction"): row
        for row in _alias_rows(new_state.get("leadership_state", []))
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
            "House Braafhart": [("Aldric Braafhart", "Duke of Eresteron", 58, 64, 52, 72, "defensive"), ("Senna Braafhart", "Braafhart Heir", 42, 68, 44, 78, "honorable"), ("Toven Braafhart", "Agricultural lord", 36, 72, 36, 74, "defensive"), ("Mira Braafhart", "Field administrator", 29, 66, 40, 70, "defensive")],
            "House LeFleur": [("Celeste LeFleur", "Duchess of Eldoria", 52, 74, 48, 80, "honorable"), ("Rael LeFleur", "LeFleur Heir", 38, 70, 42, 76, "honorable"), ("Aldwin LeFleur", "Cultural patron", 34, 78, 34, 82, "honorable"), ("Lyse LeFleur", "Arts council head", 30, 74, 36, 78, "defensive")],
            "House Bower": [("Arlen Bower", "City elder", 44, 68, 46, 72, "defensive"), ("Neva Bower", "Bower Heir", 32, 64, 48, 68, "opportunistic"), ("Harren Bower", "Guild contact", 28, 60, 52, 62, "opportunistic"), ("Meri Bower", "Quarter master", 26, 66, 44, 68, "defensive")],
            "House Binx": [("Tallo Binx", "Chance broker", 38, 40, 83, 28, "opportunistic"), ("Nix Binx", "Rumor runner", 26, 36, 77, 31, "paranoid"), ("Pava Binx", "Dicehouse owner", 29, 44, 70, 35, "opportunistic"), ("Jessa Binx", "Smuggler contact", 24, 32, 74, 26, "aggressive")],
            "House Dale": [("Nera Dale", "Harvest governor", 38, 73, 42, 78, "honorable"), ("Tobin Dale", "Provisioner", 28, 66, 39, 72, "defensive"), ("Elska Dale", "Rural envoy", 26, 70, 45, 69, "honorable"), ("Berrit Dale", "Storehouse captain", 24, 58, 48, 71, "defensive")],
        },
        "Tidefall": {
            "House Ver Meer": [("Levi Ver Meer", "Grand Admiral", 84, 58, 76, 62, "defensive"), ("Isolde Ver Meer", "Harbor magistrate", 52, 63, 68, 64, "opportunistic"), ("Joren Ver Meer", "Fleet heir", 48, 51, 80, 47, "aggressive"), ("Maeric Ver Meer", "Shipyard master", 39, 57, 59, 70, "defensive")],
            "House Highland-Dusken": [("Ser Arvyn Highland-Dusken", "Sea marshal", 54, 65, 72, 68, "aggressive"), ("Lysse Highland-Dusken", "Highland Heir", 40, 62, 64, 72, "defensive"), ("Torren Highland-Dusken", "Coastal warden", 35, 58, 70, 62, "aggressive"), ("Mera Highland-Dusken", "Signal officer", 30, 64, 56, 68, "defensive")],
            "House Fish": [("Maren Fish", "Salt quay elder", 44, 68, 44, 73, "defensive"), ("Pell Fish", "Netfleet organizer", 32, 62, 51, 67, "opportunistic"), ("Una Fish", "Coastal scout", 28, 57, 58, 59, "defensive"), ("Hobb Fish", "Harbor quartermaster", 26, 55, 47, 70, "defensive")],
            "House McGowan": [("Bren McGowan", "Harbor lord", 46, 62, 52, 70, "defensive"), ("Kessa McGowan", "McGowan Heir", 34, 58, 48, 66, "opportunistic"), ("Oran McGowan", "Dock inspector", 30, 54, 56, 62, "defensive"), ("Mira McGowan", "Trade factor", 26, 60, 44, 66, "opportunistic")],
        },
        "Dur Khadur": {
            "House Gross": [("Seran Gross", "Trade Prince", 79, 43, 84, 41, "opportunistic"), ("Orren Gross", "Council treasurer", 53, 45, 76, 46, "opportunistic"), ("Dalia Gross", "Caravan patron", 45, 54, 69, 58, "defensive"), ("Voss Gross", "Auction master", 38, 34, 72, 32, "opportunistic")],
            "House Delonious": [("Aldric Delonious", "Route master", 52, 52, 74, 50, "opportunistic"), ("Mina Delonious", "Contract judge", 42, 58, 64, 56, "defensive"), ("Roven Delonious", "Trade inspector", 36, 48, 70, 44, "opportunistic"), ("Zella Delonious", "Pass warden", 28, 54, 60, 48, "defensive")],
            "House Galfazzar": [("Mira Galfazzar", "Guild patron", 48, 56, 68, 60, "defensive"), ("Cavan Galfazzar", "Galfazzar Heir", 36, 52, 62, 56, "opportunistic"), ("Nela Galfazzar", "Merchant factor", 32, 58, 56, 62, "defensive"), ("Roth Galfazzar", "Ledger keeper", 26, 48, 52, 52, "defensive")],
            "House Vercenti": [("Vercenti the Elder", "Silent partner", 56, 38, 78, 34, "paranoid"), ("Izel Vercenti", "Vercenti Heir", 40, 42, 72, 38, "opportunistic"), ("Bram Vercenti", "Covert factor", 34, 36, 74, 32, "paranoid"), ("Sel Vercenti", "Shadow broker", 26, 32, 70, 28, "paranoid")],
        },
        "Lostfeld": {
            "Clan Goldfinger-Duke": [("Babadu Goldfinger-Duke", "High Thane", 86, 64, 52, 78, "honorable"), ("Sanna Goldfinger-Duke", "Clan Heir", 68, 68, 46, 82, "honorable"), ("Brum Goldfinger-Duke", "Mint captain", 62, 60, 58, 74, "defensive"), ("Kelda Goldfinger-Duke", "Contract keeper", 54, 70, 46, 76, "honorable")],
            "Clan Runewarden": [("Dhorin Runewarden", "Runekeeper elder", 74, 76, 40, 82, "defensive"), ("Mira Runewarden", "Vault archivist", 62, 82, 34, 86, "honorable"), ("Torvek Runewarden", "Seal engineer", 58, 70, 44, 78, "defensive"), ("Helja Runewarden", "Deep record keeper", 52, 78, 30, 82, "honorable")],
            "Clan Ironmaul": [("Ulric Ironmaul", "Forge elder", 78, 68, 50, 84, "defensive"), ("Bera Ironmaul", "Ironmaul Heir", 64, 72, 44, 80, "honorable"), ("Korin Ironmaul", "Forge marshal", 58, 62, 56, 78, "defensive"), ("Dagna Ironmaul", "Hall steward", 52, 76, 36, 82, "honorable")],
        },
        "Shadow Court": {
            "House Verlorn": [("Lyathra the Veiled", "Shadow Queen", 92, 18, 76, 38, "paranoid"), ("Vayne Verlorn", "Shadow Heir", 70, 22, 80, 44, "paranoid"), ("Selith Verlorn", "Court Inquisitor", 64, 16, 74, 52, "aggressive"), ("Mira Verlorn", "Veil Keeper", 50, 30, 72, 28, "opportunistic")],
            "House Nightborn": [("Draveth Nightborn", "Executioner General", 76, 18, 72, 62, "aggressive"), ("Selis Nightborn", "Ritual Keeper", 62, 22, 66, 56, "paranoid"), ("Ryss Nightborn", "Assassin Captain", 58, 14, 76, 50, "aggressive"), ("Veth Nightborn", "Disgraced Spy", 46, 28, 74, 22, "opportunistic")],
            "House Shadowveil": [("Aelith Shadowveil", "Veil Manipulator", 68, 26, 78, 32, "paranoid"), ("Lysse Shadowveil", "Shadowveil Heir", 54, 30, 74, 36, "paranoid"), ("Erith Shadowveil", "Court Whisper", 50, 22, 80, 28, "opportunistic"), ("Nael Shadowveil", "Veiled Agent", 42, 18, 76, 24, "aggressive")],
        },
        "Glenhaven": {
            "House Wood": [("Thalorien Wood", "High Sovereign", 88, 78, 52, 84, "honorable"), ("Aelindra Wood", "Sovereign's Heir", 68, 74, 48, 82, "honorable"), ("Faeln Wood", "War-Reader", 64, 70, 55, 76, "defensive"), ("Sylvorn Wood", "Forest Envoy", 54, 76, 44, 74, "honorable")],
            "House Darkleaf": [("Verath Darkleaf", "Shadow Councillor", 74, 44, 72, 56, "opportunistic"), ("Sylra Darkleaf", "Darkleaf Heir", 62, 46, 70, 52, "opportunistic"), ("Erith Darkleaf", "Forest Spy", 60, 40, 74, 50, "paranoid"), ("Nael Darkleaf", "Border Hunter", 52, 46, 66, 46, "aggressive")],
            "House Mistafae": [("Cael Mistafae", "Elder Delegate", 70, 82, 42, 88, "honorable"), ("Lysse Mistafae", "Council Heir", 56, 78, 38, 84, "honorable"), ("Faen Mistafae", "Grove Keeper", 54, 80, 36, 82, "defensive"), ("Iorel Mistafae", "Memory Singer", 48, 84, 32, 80, "honorable")],
        },
        "Gilgeth Clans": {
            "Clan Blackblood": [("Kragor Blackblood", "High Warlord", 86, 62, 58, 74, "aggressive"), ("Broga Blackblood", "Warlord's Heir", 68, 58, 62, 70, "aggressive"), ("Kreth Blackblood", "Clan Champion", 64, 44, 76, 62, "aggressive"), ("Ulva Blackblood", "Raider Captain", 56, 38, 80, 50, "aggressive")],
            "Clan Ironhide": [("Vorg Ironhide", "Clan Elder", 76, 40, 78, 58, "aggressive"), ("Grak Ironhide", "Elder's Son", 64, 36, 76, 52, "aggressive"), ("Shura Ironhide", "Shield Maiden", 60, 44, 70, 66, "defensive"), ("Durz Ironhide", "Ambush Hunter", 52, 34, 74, 46, "aggressive")],
            "Clan Redtusk": [("Brak Redtusk", "Battle Elder", 74, 32, 78, 52, "aggressive"), ("Urka Redtusk", "Tusk Heir", 62, 30, 76, 48, "aggressive"), ("Ghal Redtusk", "Siege Master", 58, 26, 74, 44, "aggressive"), ("Vrenna Redtusk", "War Drummer", 50, 34, 70, 52, "defensive")],
        },
        "Groth Clans": {
            "Clan Mijid": [("Drogath Mijid", "Warchief", 88, 26, 84, 44, "aggressive"), ("Vrakka Mijid", "Warchief Heir", 72, 24, 82, 48, "aggressive"), ("Droth Mijid", "Berserker Lord", 66, 20, 86, 40, "aggressive"), ("Shara Mijid", "Blood Shaman", 60, 32, 74, 42, "paranoid")],
            "Clan Ashfang": [("Griss Ashfang", "Smoke Elder", 72, 50, 64, 68, "opportunistic"), ("Nalla Ashfang", "Elder's Daughter", 60, 48, 66, 62, "opportunistic"), ("Krug Ashfang", "Fire Keeper", 56, 42, 72, 55, "aggressive"), ("Orra Ashfang", "Scout Mistress", 50, 46, 68, 58, "defensive")],
            "Clan Syncar": [("Durn Syncar", "Clan Reaver", 68, 28, 80, 40, "aggressive"), ("Vela Syncar", "Syncar Heir", 54, 26, 78, 44, "aggressive"), ("Krath Syncar", "War Drummer", 50, 22, 82, 36, "aggressive"), ("Orva Syncar", "Bone Shaman", 44, 34, 70, 38, "paranoid")],
        },
        "Vilefin": {
            "Clan Bloodware": [("Grikk Bloodware", "Speaker", 82, 34, 84, 36, "opportunistic"), ("Nix Bloodware", "Speaker's Kin", 64, 30, 80, 40, "opportunistic"), ("Vrax Bloodware", "Trap Master", 60, 26, 82, 32, "aggressive"), ("Pella Bloodware", "Info Broker", 54, 32, 78, 28, "paranoid")],
            "Clan Cogtooth": [("Skrix Cogtooth", "Former Speaker", 72, 36, 80, 34, "opportunistic"), ("Pava Cogtooth", "Clan Rival", 58, 32, 76, 38, "opportunistic"), ("Mekka Cogtooth", "Scavenger Boss", 54, 28, 78, 30, "aggressive"), ("Drip Cogtooth", "Poison Brewer", 46, 22, 74, 24, "paranoid")],
            "Clan Rustfang": [("Grix Rustfang", "Clan Boss", 70, 28, 80, 35, "opportunistic"), ("Skit Rustfang", "Boss's Runt", 58, 25, 76, 38, "opportunistic"), ("Vrenn Rustfang", "Scavenger Chief", 54, 22, 78, 30, "aggressive"), ("Drip Rustfang", "Rust Brewer", 48, 18, 74, 28, "paranoid")],
        },
        "The Wintermark": {
            "House Adkison": [("Kaelen Adkison", "High Lord", 82, 68, 62, 76, "defensive"), ("Caeris Adkison", "Adkison Heir", 64, 64, 56, 72, "honorable"), ("Mara Adkison", "Frost Warden", 56, 60, 66, 70, "defensive"), ("Joric Adkison", "Border marshal", 48, 52, 72, 62, "aggressive")],
            "House McIntosh": [("Bren McIntosh", "Highland warden", 50, 66, 54, 80, "defensive"), ("Maela McIntosh", "McIntosh Heir", 36, 62, 50, 74, "honorable"), ("Torren McIntosh", "Frost guard captain", 32, 56, 60, 68, "aggressive"), ("Iona McIntosh", "Refuge keeper", 28, 70, 38, 78, "honorable")],
            "House Holter": [("Aldric Holter", "Cold roads marshal", 46, 60, 58, 72, "defensive"), ("Senna Holter", "Holter Heir", 34, 56, 52, 68, "defensive"), ("Toven Holter", "Winter scout", 30, 52, 62, 62, "aggressive"), ("Elia Holter", "Frost envoy", 26, 58, 48, 66, "defensive")],
            "House Duval": [("Maris Duval", "Survivor elder", 44, 64, 50, 74, "defensive"), ("Ren Duval", "Duval Heir", 32, 60, 46, 70, "opportunistic"), ("Corra Duval", "Supply master", 28, 68, 40, 76, "honorable"), ("Tavin Duval", "Cold envoy", 24, 66, 44, 72, "defensive")],
        },
        "Varkuun": {
            "House Van Cleave": [("Ashali Van Cleave", "High Marshal", 82, 52, 80, 58, "aggressive"), ("Garron Van Cleave", "Marshal's Heir", 62, 58, 72, 66, "aggressive"), ("Helena Van Cleave", "Gate commander", 48, 64, 62, 74, "defensive"), ("Dain Van Cleave", "Cavalry captain", 42, 50, 76, 56, "aggressive")],
        },
        "Dreadwind Isles": {
            "House Blacktide": [("Ronan Blacktide", "Captain", 86, 46, 74, 52, "aggressive"), ("Sarra Blacktide", "Captain's Heir", 68, 42, 72, 56, "opportunistic"), ("Kel Blacktide", "Master Gunner", 64, 38, 70, 60, "aggressive"), ("Dune Blacktide", "Harbormaster", 56, 50, 60, 66, "defensive")],
            "House Stormvane": [("Mira Stormvane", "Admiral", 74, 40, 76, 50, "aggressive"), ("Joss Stormvane", "Quartermaster", 62, 36, 72, 54, "opportunistic"), ("Cael Stormvane", "Boarding Captain", 58, 34, 74, 46, "aggressive"), ("Una Stormvane", "Navigator", 52, 44, 64, 58, "defensive")],
            "House Saltbreach": [("Torren Saltbreach", "Privateer Lord", 70, 42, 78, 44, "opportunistic"), ("Yvara Saltbreach", "Privateer Heir", 58, 38, 74, 48, "opportunistic"), ("Rinn Saltbreach", "Siege Corsair", 54, 34, 76, 42, "aggressive"), ("Brix Saltbreach", "Powder Master", 48, 40, 70, 50, "defensive")],
        },
        "Stonebreak Monastery": {
            "Druid Circle": [("Grand Druid Varak", "Grand Druid", 76, 82, 44, 78, "honorable"), ("Elder Maren", "Council Elder", 62, 86, 36, 82, "defensive"), ("Dwyn the Green", "Grove Keeper", 54, 80, 40, 76, "honorable"), ("Nira Stonepath", "Druid Initiate", 36, 74, 32, 68, "defensive")],
        },
    }
    rows = []
    faction_home = {
        "Twin Cities": "Twin Cities",
        "Tidefall": "Tidefall",
        "Dur Khadur": "Dur Khadur",
        "Lostfeld": "Lostfeld",
        "Shadow Court": "Faerwood",
        "Glenhaven": "Glenhaven",
        "Gilgeth Clans": "Gilgeth",
        "Groth Clans": "Groth",
        "Vilefin": "Vilefin",
        "The Wintermark": "Wintermark",
        "Varkuun": "Varkuun",
        "Dreadwind Isles": "Dreadwind Isles",
        "Stonebreak Monastery": "Stonebreak",
    }
    faction_race = {
        "Lostfeld": "Dwarf",
        "Shadow Court": "Dark Elf",
        "Glenhaven": "Wood Elf",
        "Gilgeth Clans": "Orc",
        "Groth Clans": "Orc",
        "Vilefin": "Goblin",
    }
    faction_ages = {
        # (index0, index1, index2, index3+)
        "Lostfeld":     (218, 168, 130, 98),
        "Shadow Court": (320, 240, 180, 130),
        "Glenhaven":    (312, 242, 186, 142),
        "Gilgeth Clans":(52, 36, 44, 29),
        "Groth Clans":  (48, 34, 40, 26),
        "Vilefin":      (38, 26, 32, 20),
    }
    core_roles = ["Leader", "Heir", "Power Role", "Wildcard"]
    for faction, houses in specs.items():
        for house, members in houses.items():
            for index, (name, role, influence, morality, ambition, loyalty, bias) in enumerate(members):
                ages = faction_ages.get(faction, (46, 32, 38, 27))
                age = ages[min(index, 3)]
                role_lower = role.lower()
                if "elder" in role_lower:
                    age = max(age, ages[0] - 20)
                if "cousin" in role_lower or "magistrate" in role_lower or "minister" in role_lower:
                    age += 4
                intel = max(35, min(90, int((influence + ambition + loyalty) / 3)))
                rl = role.lower()
                # warfare: ambition + ruthlessness, boosted for military roles
                _war = int(ambition * 0.5 + (100 - morality) * 0.3 + influence * 0.2)
                if any(x in rl for x in ["marshal","captain","warlord","champion","commander","garrison","raider","berserker","boarding","siege","gunner","shield","scout","hunter","cavalry","soldier"]):
                    _war = int(_war * 1.25 + 8)
                warfare_seed = max(5, min(95, _war))
                # diplomacy: intelligence + loyalty, boosted for envoy/legal/council roles
                _dip = int(intel * 0.4 + loyalty * 0.4 + morality * 0.2)
                if any(x in rl for x in ["envoy","advocate","diplomat","mediator","lawyer","broker","judge","councillor","delegate","representative","elect","factor","treasurer","steward","liaison","magistrate","minister"]):
                    _dip = int(_dip * 1.25 + 8)
                diplomacy_seed = max(5, min(95, _dip))
                # intrigue: ambition + inverse-loyalty, boosted for spy/shadow/criminal roles
                _int = int(ambition * 0.4 + (100 - loyalty) * 0.35 + intel * 0.25)
                if any(x in rl for x in ["spy","agent","assassin","cipher","informant","courier","shadow","covert","quiet","rumor","smuggl","defector","disgraced","poison","runner","handler","watcher"]):
                    _int = int(_int * 1.25 + 8)
                intrigue_seed = max(5, min(95, _int))
                # faith: morality + passivity, boosted for ritual/keeper/shaman/singer roles
                _fth = int(morality * 0.55 + (100 - ambition) * 0.25 + 8)
                if any(x in rl for x in ["druid","priest","ritual","shaman","faith","keeper","memory","singer","elder","sacred","rune","archivist","record"]):
                    _fth = int(_fth * 1.25 + 8)
                faith_seed = max(5, min(95, _fth))
                rows.append({
                    "name": name,
                    "faction": faction,
                    "house": house,
                    "coreRole": core_roles[index] if index < len(core_roles) else "Secondary",
                    "role": role,
                    "status": "Available for political action",
                    "age": float(age),
                    "race": faction_race.get(faction, "Human"),
                    "influenceScore": influence,
                    "morality": morality,
                    "ambition": ambition,
                    "loyalty": loyalty,
                    "intelligence": intel,
                    "bias": bias,
                    "currentGoal": f"Advance {house}'s position in {faction}.",
                    "recentActions": [],
                    "location": faction_home.get(faction, faction),
                    "destination": "",
                    "ticks_to_arrive": 0,
                    "journey_purpose": "",
                    "warfare": warfare_seed,
                    "diplomacy": diplomacy_seed,
                    "intrigue": intrigue_seed,
                    "faith": faith_seed,
                    "health": 100.0,
                    "wounds": [],
                    "memory": [],
                })
    return rows


# ── CHARACTER LIFECYCLE ────────────────────────────────────────────────────────

RACE_LIFESPAN = {
    #              natural lifespan  hard max  (years)
    "Human":    {"natural": 72, "max": 92},
    "Dwarf":    {"natural": 285, "max": 360},
    "High Elf": {"natural": 620, "max": 790},
    "Wood Elf": {"natural": 400, "max": 600},
    "Dark Elf": {"natural": 530, "max": 670},
    "Orc":      {"natural": 54, "max": 68},
    "Goblin":   {"natural": 40, "max": 52},
}


def _parse_age_float(val) -> float:
    """Return age as a float year value; fall back to 30.0 if unparseable."""
    try:
        return float(str(val).strip())
    except (ValueError, TypeError):
        return 30.0


def _advance_age(char: dict) -> float:
    """
    Advance a character's age by one tick (one day = 1/365 years).
    Returns the new age as a float.
    """
    return _parse_age_float(char.get("age", 30)) + (1.0 / 365.0)


def _natural_death_chance(age: float, race: str) -> float:
    """
    Return the per-tick (per-day) probability of natural death for a character.

    Death probability is zero below the natural lifespan threshold, then rises
    along a cubic curve, reaching ~1.5 % per day at the hard max lifespan and
    capping at 40 % per day beyond it.

    Examples (Human, natural=72, max=92):
        age 70  → 0.00 %   (below threshold, no natural death)
        age 80  → 0.19 %   (t=0.40 → moderate elder risk)
        age 86  → 0.85 %   (t=0.70 → significant risk)
        age 92  → 1.50 %   (t=1.00 → high; expected survival ~46 more days)
        age 95+ → 40.00 %  (hard cap; near-certain death within days)
    """
    span = RACE_LIFESPAN.get(race, RACE_LIFESPAN["Human"])
    natural = span["natural"]
    max_age = span["max"]

    if age < natural:
        return 0.0

    t = (age - natural) / (max_age - natural)   # 0.0 at natural, 1.0 at max
    t = min(t, 1.5)                              # allow slight overshoot
    return min(t ** 3 * 0.015, 0.40)            # cubic ramp, cap at 40 %


# ── CHARACTER HEALTH ───────────────────────────────────────────────────────────

def _apply_damage(char: dict, amount: float, wound_desc: str = "") -> dict:
    """
    Reduce a character's health by amount and optionally record a wound.
    Returns a new dict — does not mutate the original.

    amount      : health points to remove (positive number)
    wound_desc  : short description of the injury; omit for pure health drain

    Wounds are capped at 6 active entries; oldest wound is dropped when full.
    Health is clamped to [0, 100].
    """
    new_health = max(0.0, min(100.0, float(char.get("health", 100)) - amount))
    wounds = list(char.get("wounds") or [])
    if wound_desc:
        wounds.append(wound_desc)
        wounds = wounds[-6:]          # keep most-recent 6
    return {**char, "health": round(new_health, 2), "wounds": wounds}


def _recover_health(char: dict) -> float:
    """
    Calculate one tick of passive health recovery and return the new health value.

    Recovery rules:
        base rate : +0.5 health per tick (full recovery from 0 in ~200 ticks / 7 months)
        each wound: -0.08 per tick (6 wounds halves the base rate to +0.02)
        floor     : 0.05 per tick minimum (body always tries to heal)
        ceiling   : health never exceeds max_health, which equals 100 minus a
                    penalty that kicks in for characters beyond their natural lifespan
                    (elderly bodies cannot fully restore themselves)

    Returns the new health as a float clamped to [current_health, max_health].
    """
    current   = float(char.get("health", 100))
    wounds    = list(char.get("wounds") or [])
    race      = char.get("race", "Human")
    age       = _parse_age_float(char.get("age", 30))

    span      = RACE_LIFESPAN.get(race, RACE_LIFESPAN["Human"])
    natural   = span["natural"]
    max_age   = span["max"]

    # Max health declines for elderly characters (cannot heal beyond diminished cap)
    if age <= natural:
        max_health = 100.0
    else:
        t = min((age - natural) / (max_age - natural), 1.0)
        max_health = max(40.0, 100.0 - t * 40.0)   # 100 → 60 across the danger zone

    if current >= max_health:
        return current

    rate = max(0.05, 0.50 - len(wounds) * 0.08)
    return min(max_health, round(current + rate, 2))


def _health_death_modifier(health: float) -> float:
    """
    Multiplier applied to the age-based natural death chance when health is low.

    health ≥ 80  → 1.0×   (no modification)
    health = 50  → 1.5×
    health = 20  → 3.0×
    health =  0  → 10.0×

    Also returns a small base death chance for critically wounded characters
    regardless of age, as a second return value.
    """
    if health >= 80:
        return 1.0
    if health >= 50:
        return 1.0 + (80 - health) / 60.0
    if health >= 20:
        return 1.5 + (50 - health) / 20.0
    return 3.0 + (20 - health) * 0.35


def _critical_health_death_chance(health: float) -> float:
    """
    Per-tick death chance from critical health alone, independent of age.
    Zero above 20 health. Rises to 2 % per tick at 0 health.
    """
    if health >= 20:
        return 0.0
    if health >= 10:
        return (20 - health) / 10.0 * 0.002
    return 0.002 + (10 - health) / 10.0 * 0.018


# ── CHARACTER MEMORY ───────────────────────────────────────────────────────────

# Base impact decay per tick for each memory type.
# Actual decay = base × _trait_evolution_rate(age, race), so long-lived races
# (ancient elves, dwarves) remember far longer than short-lived ones (goblins, young humans).
MEMORY_DECAY_RATE = {
    "betrayal": 0.08,   # slowest — betrayal scars are deep and lasting
    "alliance": 0.12,   # slow — trusted bonds fade gradually
    "loss":     0.14,   # medium-slow — defeats sting
    "victory":  0.18,   # medium — triumphs buoy, then recede
    "honor":    0.18,   # medium — respect fades without renewal
    "threat":   0.24,   # faster — threats feel less urgent with time
}


def _add_memory(char: dict, mem_type: str, target: str, impact: float,
                description: str = "", tick: int = 0) -> dict:
    """
    Add a new memory entry to a character and return the updated dict.

    mem_type    : one of MEMORY_DECAY_RATE keys
    target      : name of the character, faction, or event this memory is about
    impact      : signed float — negative for bad memories, positive for good ones
                  Typical ranges: betrayal −20 to −40, victory +10 to +25,
                  alliance +10 to +20, loss −10 to −25, honor +5 to +15, threat −5 to −15
    description : short prose note; optional
    tick        : world tick when the memory formed; optional

    Memories are capped at 12.  When full, the lowest-|impact| memory is evicted
    to make room, preserving the most significant ones.
    """
    memories = list(char.get("memory") or [])
    entry = {
        "type":        mem_type,
        "target":      target,
        "impact":      round(float(impact), 2),
        "tick":        tick,
        "description": description,
    }

    # Merge with existing memory of the same type+target (compound effect, not duplicate)
    for m in memories:
        if m.get("type") == mem_type and m.get("target") == target:
            m["impact"] = round(max(-100.0, min(100.0, m["impact"] + impact * 0.5)), 2)
            m["description"] = description or m.get("description", "")
            m["tick"] = tick or m.get("tick", 0)
            return {**char, "memory": memories}

    memories.append(entry)

    # Evict lowest-impact memory when over capacity
    if len(memories) > 12:
        memories.sort(key=lambda m: abs(m.get("impact", 0)))
        memories = memories[1:]   # drop the least significant

    return {**char, "memory": memories}


def _fade_memories(char: dict) -> list:
    """
    Apply one tick of memory decay and return the updated memory list.

    Each memory's impact moves toward zero at a rate scaled by the character's
    life-stage rate modifier — long-lived elder races forget far more slowly.
    Memories whose |impact| drops below 0.5 are discarded.
    """
    memories = list(char.get("memory") or [])
    if not memories:
        return []

    age  = _parse_age_float(char.get("age", 30))
    race = char.get("race", "Human")
    rate = _trait_evolution_rate(age, race)   # lower = slower decay for elders

    surviving = []
    for m in memories:
        base_decay = MEMORY_DECAY_RATE.get(m.get("type", "threat"), 0.18)
        decay      = base_decay * rate
        impact     = float(m.get("impact", 0))

        if impact > 0:
            impact = max(0.0, impact - decay)
        else:
            impact = min(0.0, impact + decay)

        if abs(impact) >= 0.5:
            surviving.append({**m, "impact": round(impact, 2)})

    return surviving


# ── PERSONALITY EVOLUTION ──────────────────────────────────────────────────────

def _trait_evolution_rate(age: float, race: str) -> float:
    """
    Scale factor for how fast traits evolve, based on how far the character
    is through their natural lifespan.

    Young characters are still forming — traits shift readily.
    Ancient characters have spent centuries becoming who they are — change is slow.

    Life-stage brackets (as fraction of natural lifespan):
        < 20 %  : 1.5×  (formative — volatile, easily shaped)
          20–60 %: 1.0×  (active life — standard rate)
          60–80 %: 0.6×  (mature — increasingly set in their ways)
        > 80 %  : 0.3×  (elder — personality is crystallised)
    """
    span    = RACE_LIFESPAN.get(race, RACE_LIFESPAN["Human"])
    natural = span["natural"]
    frac    = age / natural if natural > 0 else 1.0

    if frac < 0.20:
        return 1.5
    if frac < 0.60:
        return 1.0
    if frac < 0.80:
        return 0.6
    return 0.3


def _evolve_traits(char: dict) -> dict:
    """
    Apply one tick of personality evolution.

    Evolution sources, applied in order:
        1. Event signals  — most-recent recentAction scanned for keywords; each
                            matching signal produces a one-off trait delta.
        2. Passive drift  — slow ongoing shifts driven by current trait values,
                            health, wounds, and age.

    All deltas are multiplied by _trait_evolution_rate() so long-lived races
    change far more slowly than short-lived ones.

    Traits are returned as floats; the normalizer clamps them to [0, 100]
    and rounds for storage.
    """
    morality     = float(char.get("morality",    50))
    ambition     = float(char.get("ambition",    50))
    loyalty      = float(char.get("loyalty",     50))
    intelligence = float(char.get("intelligence",50))
    health       = float(char.get("health",      100))
    age          = _parse_age_float(char.get("age", 30))
    race         = char.get("race", "Human")
    wounds       = list(char.get("wounds") or [])

    rate = _trait_evolution_rate(age, race)

    # Most-recent action only — avoids re-applying old events
    recent = char.get("recentActions") or []
    signal = ((recent[-1] if recent else "") + " " + (char.get("status") or "")).lower()

    dm = da = dl = di = 0.0   # deltas

    # ── EVENT SIGNALS ──────────────────────────────────────────────────────
    if any(w in signal for w in ["betray", "deceiv", "backstab", "lied to", "manipulated"]):
        dl -= 2.5    # betrayal scars loyalty
        dm -= 0.5

    if any(w in signal for w in ["victory", "triumph", "won the", "defeated the", "successful raid", "secured"]):
        da += 1.5    # success feeds ambition
        di += 0.5    # victory teaches strategy

    if any(w in signal for w in ["defeated", "routed", "lost the", "failed", "collapsed", "surrendered"]):
        da -= 1.5    # failure deflates ambition
        dm -= 1.0    # loss corrodes morale

    if any(w in signal for w in ["appointed", "promoted", "elevated", "honored", "rewarded"]):
        da += 1.0
        dl += 1.0    # institutional recognition deepens loyalty

    if any(w in signal for w in ["exiled", "imprisoned", "stripped", "condemned", "punished"]):
        dl -= 2.0    # punishment breeds resentment
        da += 0.8    # and hardens ambition

    if any(w in signal for w in ["bribed", "corrupt", "embezzl", "extort", "smuggl"]):
        dm -= 1.5
        dl -= 0.5

    if any(w in signal for w in ["massacre", "atrocity", "slaughter", "executed", "horror"]):
        dm -= 1.0    # witnessing violence corrodes conscience
        dl -= 0.5

    if any(w in signal for w in ["sworn", "pledged", "oath", "vowed", "alliance sealed"]):
        dl += 1.5    # formal oaths reinforce loyalty

    if any(w in signal for w in ["crisis", "desperate", "famine", "siege", "collapse"]):
        dm -= 0.5    # sustained crisis erodes moral standards
        da += 0.5    # desperation sharpens hunger

    # ── PASSIVE DRIFT ──────────────────────────────────────────────────────
    # Extreme ambition self-corrects without feeding victories
    if ambition > 78:
        da -= 0.06

    # Betrayed loyalty stabilises at a lower floor (hits bottom, stops falling)
    if loyalty < 22:
        dl += 0.10

    # Low morality compounds: cynicism breeds more cynicism
    if morality < 28:
        dm -= 0.05

    # Suffering tests moral conviction
    if morality > 82 and health < 55:
        dm -= 0.04

    # Chronic wounds deflate ambition and erode loyalty (pain isolates)
    if len(wounds) >= 3:
        da -= 0.12
        dl -= 0.06

    # ── AGE-STAGE DRIFT ────────────────────────────────────────────────────
    span    = RACE_LIFESPAN.get(race, RACE_LIFESPAN["Human"])
    natural = span["natural"]
    frac    = age / natural if natural > 0 else 1.0

    if frac > 0.80:        # deep into life — ambition fades, legacy loyalty grows
        da -= 0.04
        dl += 0.02
        di -= 0.02         # very slow cognitive slowing in true old age

    # ── APPLY RATE AND CLAMP ───────────────────────────────────────────────
    def _c(v): return max(0.0, min(100.0, v))

    return {
        **char,
        "morality":     round(_c(morality     + dm * rate), 2),
        "ambition":     round(_c(ambition     + da * rate), 2),
        "loyalty":      round(_c(loyalty      + dl * rate), 2),
        "intelligence": round(_c(intelligence + di * rate), 2),
    }


def _seed_relationship(char, target):
    """Generate initial trust/fear/respect between char and target based on proximity and traits."""
    import random
    same_house      = char.get("house") == target.get("house")
    same_faction    = char.get("faction") == target.get("faction")
    char_loyalty    = float(char.get("loyalty", 50))
    target_infl     = int(target.get("influenceScore", 50))
    target_ambition = float(target.get("ambition", 50))

    if same_house:
        trust   = random.randint(55, 80)
        fear    = random.randint(0, 20)
        respect = random.randint(45, 70)
    elif same_faction:
        trust   = random.randint(30, 55)
        fear    = random.randint(5, 25)
        respect = random.randint(30, 60)
    else:
        trust   = random.randint(10, 35)
        fear    = random.randint(10, 40)
        respect = random.randint(20, 50)

    # High-influence targets earn more respect; high-ambition targets inspire more fear
    respect = min(100, respect + int((target_infl - 50) * 0.3))
    fear    = min(100, fear    + int((target_ambition - 50) * 0.2))
    # Loyal characters trust housemates more
    if same_house and char_loyalty > 60:
        trust = min(100, trust + int((char_loyalty - 60) * 0.4))

    return {
        "trust":   max(0, min(100, trust)),
        "fear":    max(0, min(100, fear)),
        "respect": max(0, min(100, respect)),
    }


def _seed_relationships_for(char, candidates):
    """Build a full relationships dict for a character against a candidate list."""
    rels = {}
    for target in candidates:
        if target.get("name") == char.get("name"):
            continue
        name = target.get("name", "")
        if name:
            rels[name] = _seed_relationship(char, target)
    return rels


def _evolve_relationships(char):
    """Update relationship values from events, outcomes, memory, and personality traits."""
    rels    = {k: dict(v) for k, v in (char.get("relationships") or {}).items()}
    rate    = _trait_evolution_rate(char.get("age", 30), char.get("race", "Human"))
    actions = " ".join(char.get("recentActions") or []).lower()

    # Personality trait modifiers — how strongly this char reacts to each signal type
    morality     = float(char.get("morality",     50))
    ambition     = float(char.get("ambition",     50))
    loyalty      = float(char.get("loyalty",      50))
    intelligence = float(char.get("intelligence", 50))

    betrayal_sensitivity = 1.0 + (morality  - 50) * 0.015  # high morality = hurt more by betrayal
    loyalty_bonus        = 1.0 + (loyalty   - 50) * 0.010  # high loyalty  = trust gains amplified
    ambition_fear_bias   = 1.0 + (ambition  - 50) * 0.008  # high ambition = more fearful of rivals
    intel_skepticism     = 1.0 - (intelligence - 50) * 0.005 # high intel  = slower to trust

    # World-event context flags from this character's own recent actions
    war_active      = any(k in actions for k in ("war declared", "battle fought", "siege", "invaded", "at war"))
    alliance_active = any(k in actions for k in ("alliance signed", "treaty", "peace agreed", "pact formed"))
    shared_victory  = any(k in actions for k in ("alongside", "together with", "with the help of")) and \
                      any(k in actions for k in ("victory", "won", "successful raid", "captured"))
    faction_defeat  = any(k in actions for k in ("defeated in battle", "routed", "forced to retreat", "surrendered"))

    for name, rel in rels.items():
        nlow    = name.lower()
        trust   = float(rel.get("trust",   50))
        fear    = float(rel.get("fear",    50))
        respect = float(rel.get("respect", 50))

        # ── Named-target event signals ──────────────────────────────────────
        if nlow in actions:
            # Positive cooperation
            if any(k in actions for k in ("allied with", "cooperated with", "aided", "supported",
                                           "befriended", "negotiated with", "protected", "stood with")):
                trust   = min(100, trust   + 4 * rate * loyalty_bonus * intel_skepticism)
                respect = min(100, respect + 2 * rate)
                fear    = max(0,   fear    - 1 * rate)

            # Betrayal — high-morality chars feel this much harder
            if any(k in actions for k in ("betrayed", "deceived", "abandoned", "undermined",
                                           "sold out", "broke the pact", "violated the agreement")):
                trust = max(0,   trust - 14 * rate * betrayal_sensitivity)
                fear  = min(100, fear  +  5 * rate)
                respect = max(0, respect - 3 * rate)

            # Defeat of or by this target
            if any(k in actions for k in ("defeated", "crushed", "humiliated", "overpowered", "subdued")):
                fear    = min(100, fear    + 7 * rate * ambition_fear_bias)
                respect = min(100, respect + 4 * rate)
                trust   = max(0,   trust   - 3 * rate)

            # Gifts, tribute, and public honors
            if any(k in actions for k in ("gifted", "offered tribute", "paid ransom for",
                                           "honored", "publicly praised")):
                trust   = min(100, trust   + 4 * rate * loyalty_bonus)
                respect = min(100, respect + 3 * rate)
                fear    = max(0,   fear    - 2 * rate)

            # Public humiliation received from this target
            if any(k in actions for k in ("humiliated by", "forced to kneel", "publicly shamed by", "mocked by")):
                fear    = min(100, fear    +  9 * rate)
                trust   = max(0,   trust   -  6 * rate)
                respect = max(0,   respect -  4 * rate)

            # Shared victory together
            if shared_victory:
                trust   = min(100, trust   + 3 * rate * loyalty_bonus)
                respect = min(100, respect + 3 * rate)

        # ── World-event ambient shifts (apply to ALL relationships, not just named) ──
        if war_active:
            fear  = min(100, fear  + 0.4 * rate)   # everyone more fearful during war
            trust = max(0,   trust - 0.3 * rate)   # suspicion rises across the board
        if alliance_active:
            trust = min(100, trust + 0.6 * rate)   # formal alliances ease ambient tension
        if faction_defeat:
            fear    = max(0, fear    - 0.5 * rate)  # losing makes you less intimidating
            respect = max(0, respect - 0.4 * rate)

        rels[name] = {
            "trust":   round(max(0, min(100, trust)),   1),
            "fear":    round(max(0, min(100, fear)),    1),
            "respect": round(max(0, min(100, respect)), 1),
        }

    # ── Memory signals ──────────────────────────────────────────────────────
    for mem in (char.get("memory") or []):
        target   = mem.get("target", "")
        mem_type = mem.get("type", "").lower()
        if not target or target not in rels:
            continue
        strength = float(mem.get("strength", 0.5))
        rel      = rels[target]
        trust    = float(rel.get("trust",   50))
        fear     = float(rel.get("fear",    50))
        respect  = float(rel.get("respect", 50))

        if mem_type == "betrayal":
            trust   = max(0,   trust   - strength * 6 * rate * betrayal_sensitivity)
            fear    = min(100, fear    + strength * 3 * rate)
            respect = max(0,   respect - strength * 2 * rate)
        elif mem_type == "alliance":
            trust   = min(100, trust   + strength * 4 * rate * loyalty_bonus)
            respect = min(100, respect + strength * 2 * rate)
        elif mem_type == "victory":
            respect = min(100, respect + strength * 3 * rate)
            fear    = min(100, fear    + strength * 2 * rate * ambition_fear_bias)
        elif mem_type == "loss":
            trust = max(0,   trust - strength * 2 * rate)
            fear  = min(100, fear  + strength * 4 * rate)
        elif mem_type == "gift":
            trust   = min(100, trust   + strength * 3 * rate * loyalty_bonus)
            respect = min(100, respect + strength * 1 * rate)

        rels[target] = {
            "trust":   round(max(0, min(100, trust)),   1),
            "fear":    round(max(0, min(100, fear)),    1),
            "respect": round(max(0, min(100, respect)), 1),
        }

    return rels


def _drift_relationships_from_power(rows):
    """Second-pass: adjust fear and respect based on each target's actual current stats."""
    by_name = {r["name"]: r for r in rows}

    for char in rows:
        rels    = char.get("relationships") or {}
        rate    = _trait_evolution_rate(char.get("age", 30), char.get("race", "Human"))
        ambition = float(char.get("ambition", 50))

        for name, rel in rels.items():
            target = by_name.get(name)
            if not target:
                continue

            trust   = float(rel.get("trust",   50))
            fear    = float(rel.get("fear",    50))
            respect = float(rel.get("respect", 50))

            t_infl     = int(target.get("influenceScore", 50))
            t_warfare  = int(target.get("warfare",  50))
            t_diplo    = int(target.get("diplomacy", 50))
            t_ambition = float(target.get("ambition", 50))
            t_health   = float(target.get("health", 80))

            # Power-based fear: high influence + high ambition = commanding presence
            power_index = (t_infl + t_ambition) / 2
            if power_index > 60:
                fear_nudge  = (power_index - 60) * 0.014 * rate
                fear_nudge *= 1.0 + (ambition - 50) * 0.010  # ambitious observers fear rivals more
                fear = min(100, fear + fear_nudge)

            # Leadership-based respect: high warfare or diplomacy = earned standing
            leadership = max(t_warfare, t_diplo)
            if leadership > 65:
                respect = min(100, respect + (leadership - 65) * 0.012 * rate)

            # Wounded/weak targets bleed fear and respect
            if t_health < 30:
                deficit = (30 - t_health) * 0.02 * rate
                fear    = max(0, fear    - deficit)
                respect = max(0, respect - deficit * 0.5)

            rels[name] = {
                "trust":   round(max(0, min(100, trust)),   1),
                "fear":    round(max(0, min(100, fear)),    1),
                "respect": round(max(0, min(100, respect)), 1),
            }

        char["relationships"] = rels
        char["relationship_signals"] = _build_relationship_signals(char)


def _decay_relationships(char, current_tick=0):
    """Pull all relationship values toward neutral each tick.

    Decay rate is suppressed by strong, recent memories of the target.
    A fresh high-strength memory anchors the relationship; an old faded one lets it drift freely.
    """
    rels = {k: dict(v) for k, v in (char.get("relationships") or {}).items()}
    if not rels:
        return rels

    rate = _trait_evolution_rate(char.get("age", 30), char.get("race", "Human"))

    # Neutral baselines and per-axis base decay rate
    NEUTRAL    = {"trust": 40.0, "fear": 20.0, "respect": 35.0}
    BASE_DECAY = {"trust": 0.007, "fear": 0.006, "respect": 0.006}

    # Index memories: target → strongest memory and its tick (for recency calculation)
    # A strong, recent memory anchors the relationship and slows decay toward neutral.
    mem_anchor: dict = {}
    for mem in (char.get("memory") or []):
        target   = mem.get("target", "")
        strength = float(mem.get("strength", 0.0))
        mem_tick = int(mem.get("tick", 0))
        if target and target in rels:
            prev = mem_anchor.get(target)
            if prev is None or strength > prev[0]:
                mem_anchor[target] = (strength, mem_tick)

    for name, rel in rels.items():
        anchor_strength, anchor_tick = mem_anchor.get(name, (0.0, 0))

        # Recency: 1.0 = happened this tick, linearly decays to 0 over 120 ticks (~4 months)
        tick_age = max(0, current_tick - anchor_tick)
        recency  = max(0.0, 1.0 - tick_age / 120.0)

        # anchor_factor 0–1: how much the memory resists decay
        # strength=1.0 × recency=1.0 → fully anchored (no decay this tick)
        # strength=0.4 × recency=0.5 → 20% anchor → 80% of normal decay applies
        anchor_factor = anchor_strength * recency

        # decay_mult: fraction of base decay that actually applies
        decay_mult = max(0.0, 1.0 - anchor_factor) * rate

        for axis, neutral in NEUTRAL.items():
            val   = float(rel.get(axis, neutral))
            delta = (neutral - val) * BASE_DECAY[axis] * decay_mult
            rel[axis] = round(max(0.0, min(100.0, val + delta)), 1)

        rels[name] = rel

    return rels


def _relationship_decision_weights(char, target_name):
    """Return numerical decision bias multipliers for char acting toward target_name.

    All biases are signed floats; positive = pulled toward that decision type.
    Computed from neutral baselines: trust→40, fear→20, respect→35.
    """
    rel     = (char.get("relationships") or {}).get(target_name, {})
    trust   = float(rel.get("trust",   40))
    fear    = float(rel.get("fear",    20))
    respect = float(rel.get("respect", 35))

    dt = trust   - 40   # delta from neutral
    df = fear    - 20
    dr = respect - 35

    # Alliance: driven by trust + respect; fear suppresses nothing (can ally with someone you fear)
    alliance_bias    = dt * 0.025 + dr * 0.015

    # Betrayal: driven by low trust + low respect; high fear suppresses overt betrayal (covert only)
    betrayal_bias    = -dt * 0.030 + -dr * 0.010 + -df * 0.018

    # Avoidance / submission: driven by fear; high respect softens it
    avoidance_bias   = df * 0.028 + -dr * 0.008

    # Cooperation: driven by trust + respect; fear slightly reduces proactivity but not compliance
    cooperation_bias = dt * 0.022 + dr * 0.018 + -df * 0.005

    # War initiation: low trust + low fear + low respect = aggression; fear heavily suppresses it
    war_bias         = -dt * 0.012 + -df * 0.022 + -dr * 0.010

    return {
        "alliance_bias":    round(alliance_bias,    3),
        "betrayal_bias":    round(betrayal_bias,    3),
        "avoidance_bias":   round(avoidance_bias,   3),
        "cooperation_bias": round(cooperation_bias, 3),
        "war_bias":         round(war_bias,         3),
    }


def _build_relationship_signals(char):
    """Build a pre-computed bias summary for the character's most significant relationships.

    Stored on the character so Claude can read it directly without recomputing from raw numbers.
    """
    rels = char.get("relationships") or {}
    if not rels:
        return []

    def significance(rel_tuple):
        rel = rel_tuple[1]
        return (abs(rel.get("trust",   40) - 40) +
                abs(rel.get("fear",    20) - 20) +
                abs(rel.get("respect", 35) - 35))

    top = sorted(rels.items(), key=significance, reverse=True)[:10]

    signals = []
    for name, rel in top:
        trust   = rel.get("trust",   40)
        fear    = rel.get("fear",    20)
        respect = rel.get("respect", 35)
        weights = _relationship_decision_weights(char, name)

        # Identify the highest-magnitude bias
        dominant_key = max(weights, key=lambda k: abs(weights[k]))
        dominant_val = weights[dominant_key]

        if abs(dominant_val) < 0.08:
            continue  # negligibly neutral — skip

        # Describe bias as an actionable label
        label = dominant_key.replace("_bias", "").replace("_", " ")
        strength = "strongly" if abs(dominant_val) > 0.35 else ("moderately" if abs(dominant_val) > 0.18 else "slightly")
        direction = "toward" if dominant_val > 0 else "against"

        # Secondary signal: note when fear suppresses a betrayal urge (covert-only flag)
        covert_only = (weights["betrayal_bias"] > 0.15 and fear > 55)

        entry = {
            "target":          name,
            "trust":           trust,
            "fear":            fear,
            "respect":         respect,
            "primary_bias":    f"{strength} biased {direction} {label}",
        }
        if covert_only:
            entry["note"] = "fear suppresses open action — betrayal would be covert only"

        signals.append(entry)

    return signals


def _compute_character_event_pressure(char, all_chars_by_name):
    """Scan a character's relationships and traits for threshold-based event triggers.

    Returns a list of event pressure tags Claude can act on this tick.
    Tags are strings naming the event type; multiple may fire simultaneously.
    """
    tags = []
    rels  = char.get("relationships") or {}
    name  = char.get("name", "")

    morality     = float(char.get("morality",     50))
    ambition     = float(char.get("ambition",     50))
    loyalty      = float(char.get("loyalty",      50))
    intrigue     = int(char.get("intrigue",       50))
    intelligence = float(char.get("intelligence", 50))

    for target_name, rel in rels.items():
        trust   = float(rel.get("trust",   40))
        fear    = float(rel.get("fear",    20))
        respect = float(rel.get("respect", 35))
        target  = all_chars_by_name.get(target_name, {})
        t_infl  = int(target.get("influenceScore", 50))
        t_intrigue = int(target.get("intrigue", 50))

        # ── BETRAYAL ──────────────────────────────────────────────────────
        # Low trust + low loyalty + motivated by ambition + not too afraid
        if trust < 25 and loyalty < 40 and ambition > 55 and fear < 55 and morality < 55:
            tags.append(f"betrayal_risk:{target_name}")

        # ── ASSASSINATION ATTEMPT ─────────────────────────────────────────
        # Near-zero trust + high intrigue skill + low morality + target has influence worth taking
        if trust < 15 and intrigue > 60 and morality < 40 and t_infl > 55 and fear < 50:
            tags.append(f"assassination_attempt:{target_name}")

        # ── OPEN RIVALRY ESCALATION ───────────────────────────────────────
        # Low trust + low respect + high ambition on this side + not actively afraid
        if trust < 30 and respect < 28 and ambition > 65 and fear < 40:
            tags.append(f"rivalry_escalation:{target_name}")

        # ── ALLIANCE APPROACH ─────────────────────────────────────────────
        # High trust + high respect + neither side heavily hostile
        if trust > 68 and respect > 58 and fear < 45 and loyalty > 45:
            tags.append(f"alliance_approach:{target_name}")

        # ── SUBMISSION / TRIBUTE ──────────────────────────────────────────
        # Extreme fear + low trust + high influence target = likely to capitulate
        if fear > 75 and trust < 35 and t_infl > 65:
            tags.append(f"submission_likely:{target_name}")

        # ── DEFECTION TO RIVAL ────────────────────────────────────────────
        # Very low loyalty to own side AND high trust toward this target
        if loyalty < 25 and trust > 60 and ambition > 60:
            tags.append(f"defection_risk:{target_name}")

        # ── COVERT INTELLIGENCE LEAK ──────────────────────────────────────
        # Low trust + high intrigue + not afraid enough to stay quiet
        if trust < 20 and intrigue > 55 and fear < 60 and morality < 50:
            tags.append(f"intelligence_leak:{target_name}")

        # ── COUNTER-ASSASSINATION SUSPICION ───────────────────────────────
        # Target has high intrigue + low trust toward us = they may be planning something
        if t_intrigue > 65 and trust < 30 and intelligence > 55:
            tags.append(f"assassination_suspicion:{target_name}")

    return tags[:20]  # cap — don't flood Claude with noise


def _compute_faction_event_pressure(relationships):
    """Scan faction relationships for threshold-based macro event triggers.

    Returns a list of dicts describing faction-level events ready to fire.
    """
    events = []
    for rel in (relationships or []):
        a             = rel.get("faction_a", "")
        b             = rel.get("faction_b", "")
        trust         = int(rel.get("trust",          50))
        hostility     = int(rel.get("hostility",      20))
        alliance_level = int(rel.get("alliance_level", 0))
        rel_type      = rel.get("type", "neutral")
        if not a or not b:
            continue

        # War imminent: hostility very high, not already at war
        if hostility >= 82 and rel_type != "war":
            events.append({"trigger": "war_imminent", "faction_a": a, "faction_b": b,
                           "hostility": hostility, "trust": trust})

        # Alliance collapse: declared alliance but trust collapsed or hostility spiked
        if rel_type == "alliance" and (trust < 25 or hostility > 55):
            events.append({"trigger": "alliance_collapse", "faction_a": a, "faction_b": b,
                           "trust": trust, "hostility": hostility})

        # Faction betrayal: high alliance_level but trust fell off a cliff (backstab)
        if alliance_level > 45 and trust < 20:
            events.append({"trigger": "faction_betrayal", "faction_a": a, "faction_b": b,
                           "alliance_level": alliance_level, "trust": trust})

        # Peace overture: both sides in active war but trust crept back up
        if rel_type == "war" and trust > 38 and hostility < 60:
            events.append({"trigger": "peace_overture", "faction_a": a, "faction_b": b,
                           "trust": trust, "hostility": hostility})

        # Alliance formation ready: trust high, hostility low, not yet formalized
        if trust > 68 and hostility < 28 and alliance_level < 40 and rel_type != "alliance":
            events.append({"trigger": "alliance_forming", "faction_a": a, "faction_b": b,
                           "trust": trust, "alliance_level": alliance_level})

        # Rivalry escalation: moderate hostility rising without war
        if 55 <= hostility <= 82 and trust < 35 and rel_type not in ("war", "alliance"):
            events.append({"trigger": "rivalry_escalating", "faction_a": a, "faction_b": b,
                           "hostility": hostility, "trust": trust})

    return events


def _normalize_house_characters(prev_state, new_state):
    import random

    current_tick = int(new_state.get("tick", 0) or 0)
    try:
        if int(new_state.get("_house_lifecycle_tick", -1)) == current_tick:
            return
    except (TypeError, ValueError):
        pass

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

    def _is_deceased(r):
        return str(r.get("status", "")).lower().startswith("deceased")

    # Build faction → char list for relationship seeding (from prev state so it's stable)
    faction_chars: dict = {}
    for c in prev_state.get("house_characters", []):
        if c.get("name") and not _is_deceased(c):
            faction_chars.setdefault(c.get("faction", ""), []).append(c)

    def _build_relationship_candidates(char):
        faction = char.get("faction", "")
        house   = char.get("house", "")
        # All housemates
        housemates = [c for c in faction_chars.get(faction, []) if c.get("house") == house]
        # Top 5 same-faction other-house chars by influence
        faction_peers = sorted(
            [c for c in faction_chars.get(faction, []) if c.get("house") != house],
            key=lambda c: -c.get("influenceScore", 0),
        )[:5]
        # Top faction leader from each other faction (max 6)
        cross = []
        for f, chars in faction_chars.items():
            if f != faction:
                top = sorted(chars, key=lambda c: -c.get("influenceScore", 0))
                if top:
                    cross.append(top[0])
        return housemates + faction_peers + cross[:6]

    # Houses that already have living characters — don't inject hardcoded defaults into them
    occupied_houses: set = set()
    for row in list(prev_rows.values()) + list(incoming_rows.values()):
        if not _is_deceased(row) and row.get("name"):
            occupied_houses.add((row.get("faction"), row.get("house")))

    rows = []
    for seed in _default_house_characters():
        key = (seed["faction"], seed["house"], seed["name"])

        # Once dead, always dead — don't resurrect from seed
        prev = prev_rows.get(key)
        if prev and _is_deceased(prev):
            continue

        # Skip default injection if this house already has living characters
        # (fresh-game characters or AI-generated members already occupy it)
        house_key = (seed["faction"], seed["house"])
        if house_key in occupied_houses and key not in prev_rows and key not in incoming_rows:
            continue

        row = incoming_rows.get(key, prev_rows.get(key, seed))

        # Respect AI-marked deaths
        if _is_deceased(row):
            continue

        race = row.get("race", seed["race"])

        # Memory fading (before evolution — current memories feed into trait signals)
        faded_memory = _fade_memories(row)
        row = {**row, "memory": faded_memory}

        # Personality evolution (before death check — dead characters don't evolve)
        row = _evolve_traits(row)

        # Relationships — seed on first encounter; evolve then decay on subsequent ticks
        existing_rels = row.get("relationships") or {}
        if not existing_rels:
            new_rels = _seed_relationships_for(row, _build_relationship_candidates(row))
        else:
            evolved_row = {**row, "relationships": _evolve_relationships(row)}
            new_rels    = _decay_relationships(evolved_row, current_tick)

        # Age advancement
        new_age = _advance_age(row)

        # Health recovery
        new_health = _recover_health(row)
        wounds     = list(row.get("wounds") or [])

        rows.append({
            "name": row.get("name", seed["name"]),
            "faction": row.get("faction", seed["faction"]),
            "house": row.get("house", seed["house"]),
            "coreRole": row.get("coreRole", seed.get("coreRole", "Secondary")),
            "role": row.get("role", seed["role"]),
            "status": row.get("status", seed["status"]),
            "age": round(new_age, 3),
            "race": race,
            "influenceScore": max(0, min(100, int(row.get("influenceScore", seed["influenceScore"])))),
            "morality":     round(max(0.0, min(100.0, float(row.get("morality",     seed["morality"])))),     2),
            "ambition":     round(max(0.0, min(100.0, float(row.get("ambition",     seed["ambition"])))),     2),
            "loyalty":      round(max(0.0, min(100.0, float(row.get("loyalty",      seed["loyalty"])))),      2),
            "intelligence": round(max(0.0, min(100.0, float(row.get("intelligence", seed.get("intelligence", 50))))), 2),
            "bias": row.get("bias", seed["bias"]),
            "currentGoal": row.get("currentGoal", seed["currentGoal"]),
            "recentActions": (row.get("recentActions") or [])[:5],
            "location": row.get("location") or seed.get("location", ""),
            "destination": row.get("destination", ""),
            "ticks_to_arrive": max(0, int(row.get("ticks_to_arrive", 0) or 0)),
            "journey_purpose": row.get("journey_purpose", ""),
            "warfare":   max(0, min(100, int(row.get("warfare",   seed.get("warfare",   50))))),
            "diplomacy": max(0, min(100, int(row.get("diplomacy", seed.get("diplomacy", 50))))),
            "intrigue":  max(0, min(100, int(row.get("intrigue",  seed.get("intrigue",  50))))),
            "faith":     max(0, min(100, int(row.get("faith",     seed.get("faith",     20))))),
            "health":    round(new_health, 2),
            "wounds":    wounds,
            "memory":    faded_memory,
            "relationships":       new_rels,
            "relationship_signals": _build_relationship_signals({**row, "relationships": new_rels}),
            "event_pressure":      [],  # filled in second pass below
        })

    # Include AI-generated characters not in the seed (recruits, new arrivals, etc.)
    existing_keys = {(r["faction"], r["house"], r["name"]) for r in rows}
    for key, row in incoming_rows.items():
        if key in existing_keys or _is_deceased(row):
            continue
        new_age      = _advance_age(row)
        new_health   = _recover_health(row)
        ai_rels = row.get("relationships") or {}
        if not ai_rels:
            ai_rels = _seed_relationships_for(row, _build_relationship_candidates(row))
        else:
            ai_rels = _evolve_relationships(row)
        rows.append({
            **row,
            "age": round(new_age, 3),
            "health": round(new_health, 2),
            "wounds": list(row.get("wounds") or []),
            "memory": _fade_memories(row),
            "relationships": ai_rels,
            "relationship_signals": _build_relationship_signals({**row, "relationships": ai_rels}),
        })

    # Second pass: adjust fear/respect based on each target's actual live stats
    _drift_relationships_from_power(rows)

    # Third pass: compute event pressure now that all relationships are final
    all_chars_by_name = {r["name"]: r for r in rows}
    for char in rows:
        char["event_pressure"] = _compute_character_event_pressure(char, all_chars_by_name)

    # Faction-level event pressure stored separately in state
    new_state["faction_event_pressure"] = _compute_faction_event_pressure(
        new_state.get("relationships", [])
    )

    new_state["house_characters"] = rows[:300]
    from death_system import run_death_system

    run_death_system(new_state)
    new_state["_house_lifecycle_tick"] = current_tick


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
        ("Twin Cities",   "Humans",     "Twin Cities",       140000, 170000, 0.00025, 86, 22, 4),
        ("Eldoria",       "Humans",     "Twin Cities",        95000, 115000, 0.00022, 82, 18, 0),
        ("Tidefall",      "Humans",     "Tidefall",          160000, 185000, 0.00028, 82, 32, 20),
        ("Faerwood",      "Dark Elves", "Shadow Court",       30000,  42000, 0.00003, 74, 38, 0),
        ("Glenhaven",     "Wood Elves", "Glenhaven",          35000,  52000, 0.00005, 88, 18, 0),
        ("Lostfeld",      "Dwarves",    "Lostfeld",           65000,  85000, 0.00008, 81, 24, 0),
        ("Gilgeth",       "Orcs",       "Gilgeth Clans",      55000,  70000, 0.00020, 72, 44, 0),
        ("Groth",         "Orcs",       "Groth Clans",        45000,  60000, 0.00022, 68, 52, 0),
        ("Vilefin",       "Goblins",    "Vilefin",           215000, 230000, 0.00055, 63, 68, 0),
        ("Dreadwind Isles","Humans",    "Dreadwind Isles",    45000,  65000, 0.00018, 67, 52, 16),
        ("Dur Khadur",    "Humans",     "Dur Khadur",        115000, 155000, 0.00024, 79, 36, 8),
        ("Wintermark",    "Humans",     "The Wintermark",     42000,  62000, 0.00012, 76, 30, 0),
        ("Varkuun",       "Humans",     "Varkuun",            18000,  28000, 0.00010, 82, 20, 0),
        ("Stonebreak",    "Druids",     "Stonebreak Monastery", 5500,  9000, 0.00002, 91, 12, 0),
        ("Dragonscar Peaks","Ice Dragons","Dragon Clans",        12,    20,  0.0,     94,  9, 0),
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


# ── DECISION ENGINE ────────────────────────────────────────────────────────────

_DECISION_FACTIONS = [
    "Twin Cities", "Tidefall", "Dur Khadur", "Shadow Court",
    "Glenhaven", "Gilgeth Clans", "Groth Clans", "Vilefin",
    "Dreadwind Isles", "Varkuun", "The Wintermark", "Lostfeld",
    "Stonebreak Monastery",
]


def _faction_leader_traits(faction_name, state):
    """Return averaged trait scores for a faction's active leader-tier characters."""
    LEADER_ROLES = {"Leader", "Heir", "Power Role"}
    leaders = [
        c for c in state.get("house_characters", [])
        if c.get("faction") == faction_name
        and c.get("coreRole") in LEADER_ROLES
        and not str(c.get("status", "")).lower().startswith("deceased")
    ]
    if not leaders:
        return {"ambition": 50, "morality": 50, "loyalty": 50,
                "intelligence": 50, "warfare": 50, "diplomacy": 50}

    def _avg(key):
        vals = [float(c[key]) for c in leaders if isinstance(c.get(key), (int, float))]
        return sum(vals) / len(vals) if vals else 50.0

    return {k: _avg(k) for k in ("ambition", "morality", "loyalty", "intelligence", "warfare", "diplomacy")}


def _faction_relationships(faction_name, state):
    """Return {partner_faction: relationship_row} for all relationships involving this faction."""
    result = {}
    for row in state.get("relationships", []):
        a, b = row.get("faction_a", ""), row.get("faction_b", "")
        if a == faction_name:
            result[b] = row
        elif b == faction_name:
            result[a] = row
    return result


def _faction_power_entry(faction_name, state):
    """Return this faction's power_state entry or a neutral default."""
    for entry in state.get("faction_power_state", []):
        if entry.get("faction") == faction_name:
            return entry
    return {"militaryPower": 50, "economicPower": 50,
            "politicalInfluence": 50, "religiousInfluence": 50}


def evaluateActions(faction_name, state):
    """Score each possible action for a faction. Returns {action: score}.

    Two-stage design:
      Stage 1 — Situational base: what does the world actually offer this faction?
                 (hostile targets, trusted partners, unstable territory)
      Stage 2 — Personality multipliers: dominant traits amplify or suppress
                 each action nonlinearly so high-ambition factions feel
                 categorically different from diplomatic or passive ones.

    Hard blocks override scores entirely:
      - morality >= 70 OR loyalty >= 70  → betray = 0, always
      - intelligence >= 70 AND military < 45 → war score * 0.15 (won't attack weak)
      - ambition <= 30 (passive faction) → all aggressive actions halved
    """
    traits = _faction_leader_traits(faction_name, state)
    power  = _faction_power_entry(faction_name, state)
    rels   = _faction_relationships(faction_name, state)

    ambition     = float(traits["ambition"])
    morality     = float(traits["morality"])
    loyalty      = float(traits["loyalty"])
    intelligence = float(traits["intelligence"])
    warfare      = float(traits.get("warfare",   50))
    diplomacy    = float(traits.get("diplomacy", 50))

    mil = float(power.get("militaryPower",      50))
    eco = float(power.get("economicPower",       50))
    pol = float(power.get("politicalInfluence",  50))

    at_war  = [p for p, r in rels.items() if r.get("type") == "war"]
    allied  = [p for p, r in rels.items() if r.get("type") == "alliance"]
    has_war = bool(at_war)

    # ── Personality profile tags (nonlinear thresholds) ───────────────────────
    is_aggressive   = ambition     >= 72
    is_passive      = ambition     <= 32
    is_honorable    = morality     >= 68
    is_ruthless     = morality     <= 32
    is_steadfast    = loyalty      >= 68
    is_treacherous  = loyalty      <= 32
    is_strategic    = intelligence >= 70
    is_impulsive    = intelligence <= 35
    is_warrior      = warfare      >= 68
    is_diplomat     = diplomacy    >= 65

    # ── Viable target pre-checks (prevent phantom action scores) ──────────────
    hostile_targets = [
        p for p, r in rels.items()
        if r.get("type") not in ("war", "alliance") and r.get("hostility", 0) > 40
    ]
    trust_targets = [
        p for p, r in rels.items()
        if r.get("type") not in ("war", "alliance") and r.get("trust", 0) > 55
    ]

    scores = {}

    # ── DECLARE WAR ──────────────────────────────────────────────────────────
    declare_score = 0.0
    if not has_war and mil > 40 and hostile_targets:
        # Stage 1: situational — how hostile is the most hostile relationship?
        for partner, rel in rels.items():
            if rel.get("type") in ("war", "alliance"):
                continue
            h = rel.get("hostility", 0)
            if h > 50:
                declare_score += (h - 50) * 1.2   # 85 hostility → +42 base

        # Stage 2: personality push (larger coefficients than before)
        declare_score += (ambition  - 50) * 0.9
        declare_score += (warfare   - 50) * 0.6
        declare_score -= (morality  - 50) * 0.5
        declare_score -= (loyalty   - 50) * 0.2

        # Dominant-trait multipliers (nonlinear, order matters)
        if is_aggressive:  declare_score *= 1.8   # warlord: near-certain to fight
        if is_warrior:     declare_score *= 1.35
        if is_honorable:   declare_score *= 0.35  # honorable factions rarely start wars
        if is_passive:     declare_score *= 0.25  # passive factions almost never do

        # Intelligence check: strategic leaders won't attack when outmatched
        if is_strategic and mil < 45:
            declare_score *= 0.15   # they know the math
        elif is_impulsive:
            declare_score += 18     # attacks without calculating odds

    scores["declare_war"] = round(max(0.0, declare_score), 1)

    # ── FORM ALLIANCE ─────────────────────────────────────────────────────────
    form_score = 0.0
    if trust_targets:
        # Stage 1: how trusted is the most trusted available partner?
        for partner, rel in rels.items():
            if rel.get("type") == "war":
                continue
            t = rel.get("trust", 0)
            if t > 50:
                form_score += (t - 50) * 1.1

        # Stage 2: personality
        form_score += (loyalty    - 50) * 0.7
        form_score += (diplomacy  - 50) * 0.6
        form_score -= (ambition   - 50) * 0.35   # ambitious factions prefer to go alone

        if is_steadfast:  form_score *= 1.6   # loyal leaders love formal alliances
        if is_diplomat:   form_score *= 1.45
        if is_aggressive: form_score *= 0.45  # aggressive factions see allies as liabilities
        if is_treacherous:form_score *= 0.5   # treacherous factions don't value alliances
        if has_war:       form_score -= 25

    scores["form_alliance"] = round(max(0.0, form_score), 1)

    # ── BETRAY ────────────────────────────────────────────────────────────────
    betray_score = 0.0
    if allied:
        # Hard block: morality or loyalty above threshold → never betray
        if is_honorable or is_steadfast:
            betray_score = 0.0
        else:
            betray_score  = 12.0
            betray_score += (ambition  - 50) * 0.9
            betray_score -= (loyalty   - 50) * 1.4   # loyalty is the dominant restraint
            betray_score -= (morality  - 50) * 1.0

            # Dominant-trait multipliers
            if is_treacherous: betray_score *= 2.2   # pathologically disloyal
            if is_ruthless:    betray_score *= 1.6
            if is_aggressive:  betray_score *= 1.4
            # Strategic betrayers wait for the right moment: weakest alliance
            if is_strategic:
                weakest_al = min(
                    (r.get("alliance_level", 50) for p, r in rels.items()
                     if r.get("type") == "alliance"),
                    default=50,
                )
                if weakest_al < 40:
                    betray_score *= 1.5   # low-commitment alliance = ripe target
                else:
                    betray_score *= 0.8   # strategic: won't burn a solid alliance carelessly

    scores["betray"] = round(max(0.0, betray_score), 1)

    # ── STABILIZE TERRITORY ───────────────────────────────────────────────────
    unstable = sum(
        1 for loc in state.get("locations", [])
        if loc.get("controller") == faction_name
        and int(loc.get("stability", loc.get("control", 50))) < 45
    )
    stab_score  = unstable * 20.0
    stab_score += max(0.0, 50 - eco) * 0.5   # economic pressure → need to stabilize
    stab_score += (pol - 50) * 0.3
    if has_war:   stab_score *= 0.5
    if is_aggressive: stab_score *= 0.65  # aggressive factions neglect internal work
    if is_passive:    stab_score *= 1.5   # passive factions focus inward

    scores["stabilize_territory"] = round(max(0.0, stab_score), 1)

    # ── DO NOTHING ────────────────────────────────────────────────────────────
    nothing_score  = 15.0
    nothing_score -= (ambition - 50) * 0.30  # ambitious factions hate waiting
    nothing_score += max(0.0, 40 - mil) * 0.20  # weak factions hold
    if is_passive:    nothing_score += 18.0
    if is_aggressive: nothing_score  -= 10.0

    scores["do_nothing"] = round(max(3.0, nothing_score), 1)

    return scores


def chooseAction(faction_name, state, evaluated=None):
    """Probabilistically pick an action from weighted scores.

    Returns (action_name, meta_dict).
    """
    import random

    if evaluated is None:
        evaluated = evaluateActions(faction_name, state)

    total = sum(evaluated.values())
    if total <= 0:
        return "do_nothing", {}

    r = random.uniform(0, total)
    cumulative = 0.0
    chosen_action = "do_nothing"
    for action, score in sorted(evaluated.items(), key=lambda x: -x[1]):
        cumulative += score
        if r <= cumulative:
            chosen_action = action
            break

    rels = _faction_relationships(faction_name, state)
    meta = {}

    if chosen_action == "declare_war":
        best = max(
            ((p, r) for p, r in rels.items() if r.get("type") not in ("war", "alliance")),
            key=lambda x: x[1].get("hostility", 0),
            default=(None, {}),
        )
        meta["target"] = best[0]

    elif chosen_action == "form_alliance":
        best = max(
            ((p, r) for p, r in rels.items() if r.get("type") not in ("war", "alliance")),
            key=lambda x: x[1].get("trust", 0),
            default=(None, {}),
        )
        meta["target"] = best[0]

    elif chosen_action == "betray":
        allied_rels = [(p, r) for p, r in rels.items() if r.get("type") == "alliance"]
        if allied_rels:
            best = min(allied_rels, key=lambda x: x[1].get("trust", 100))
            meta["target"] = best[0]
        else:
            chosen_action = "do_nothing"

    elif chosen_action == "stabilize_territory":
        unstable_locs = [
            loc for loc in state.get("locations", [])
            if loc.get("controller") == faction_name
            and int(loc.get("stability", loc.get("control", 50))) < 45
        ]
        if unstable_locs:
            worst = min(unstable_locs,
                        key=lambda l: int(l.get("stability", l.get("control", 50))))
            meta["location"] = worst.get("name") or worst.get("id", "")

    return chosen_action, meta


def applyDecision(action, faction_name, meta, state):
    """Apply mechanical consequences of a decision to state in-place.

    Returns a log-entry dict describing the outcome.
    """
    power_map = {e["faction"]: e for e in state.get("faction_power_state", [])}
    rels_list  = state.get("relationships", [])
    target     = meta.get("target")

    def _rel_idx(a, b):
        key = tuple(sorted((a, b)))
        for i, row in enumerate(rels_list):
            if tuple(sorted((row.get("faction_a", ""), row.get("faction_b", "")))) == key:
                return i
        return None

    def _clamp(v, lo=0, hi=100):
        return max(lo, min(hi, int(v)))

    log = {"faction": faction_name, "action": action, "meta": meta}

    if action == "declare_war" and target:
        idx = _rel_idx(faction_name, target)
        if idx is not None:
            rels_list[idx]["type"]           = "war"
            rels_list[idx]["hostility"]      = _clamp(rels_list[idx].get("hostility", 50) + 20)
            rels_list[idx]["trust"]          = _clamp(rels_list[idx].get("trust",     50) - 25)
            rels_list[idx]["alliance_level"] = 0
        if faction_name in power_map:
            pw = power_map[faction_name]
            pw["militaryPower"]       = _clamp(pw.get("militaryPower",       50) + 5)
            pw["economicPower"]       = _clamp(pw.get("economicPower",       50) - 8)
            pw["politicalInfluence"]  = _clamp(pw.get("politicalInfluence",  50) - 3)
        if target in power_map:
            pw = power_map[target]
            pw["militaryPower"]       = _clamp(pw.get("militaryPower",       50) - 5)
            pw["politicalInfluence"]  = _clamp(pw.get("politicalInfluence",  50) - 5)
        log["summary"] = f"{faction_name} declared war on {target}."

    elif action == "form_alliance" and target:
        idx = _rel_idx(faction_name, target)
        if idx is not None:
            rels_list[idx]["type"]           = "alliance"
            rels_list[idx]["trust"]          = _clamp(rels_list[idx].get("trust",          50) + 15)
            rels_list[idx]["hostility"]      = _clamp(rels_list[idx].get("hostility",       30) - 15)
            rels_list[idx]["alliance_level"] = _clamp(rels_list[idx].get("alliance_level",   0) + 25)
        for f in (faction_name, target):
            if f in power_map:
                power_map[f]["politicalInfluence"] = _clamp(power_map[f].get("politicalInfluence", 50) + 5)
        log["summary"] = f"{faction_name} formalized an alliance with {target}."

    elif action == "betray" and target:
        idx = _rel_idx(faction_name, target)
        if idx is not None:
            rels_list[idx]["type"]           = "rivalry"
            rels_list[idx]["trust"]          = _clamp(rels_list[idx].get("trust",     60) - 35)
            rels_list[idx]["hostility"]      = _clamp(rels_list[idx].get("hostility", 20) + 30)
            rels_list[idx]["alliance_level"] = 0
        if faction_name in power_map:
            pw = power_map[faction_name]
            pw["politicalInfluence"] = _clamp(pw.get("politicalInfluence", 50) - 8)
            pw["economicPower"]      = _clamp(pw.get("economicPower",      50) + 5)
        if target in power_map:
            power_map[target]["politicalInfluence"] = _clamp(
                power_map[target].get("politicalInfluence", 50) - 10)
        log["summary"] = f"{faction_name} betrayed their alliance with {target}."

    elif action == "stabilize_territory":
        loc_name = meta.get("location", "")
        if loc_name:
            for loc in state.get("locations", []):
                if (loc.get("name") or loc.get("id", "")) == loc_name:
                    loc["stability"] = _clamp(int(loc.get("stability", loc.get("control", 30))) + 8)
                    loc["control"]   = _clamp(int(loc.get("control", 50)) + 5)
        if faction_name in power_map:
            pw = power_map[faction_name]
            pw["politicalInfluence"] = _clamp(pw.get("politicalInfluence", 50) - 3)
            pw["economicPower"]      = _clamp(pw.get("economicPower",      50) - 4)
            pw["militaryPower"]      = _clamp(pw.get("militaryPower",      50) + 2)
        log["summary"] = (
            f"{faction_name} invested in stabilizing {loc_name or 'their territory'}."
        )

    else:
        log["summary"] = f"{faction_name} held position this tick."

    return log


# ── EVENT EXECUTION SYSTEM ────────────────────────────────────────────────────

_EVENT_META = {
    "declare_war": {
        "severity": 14,
        "stage":    "escalating",
        "trend":    "rising",
        "template": "{faction} declared war on {target}.",
        "consequences_template": (
            "Open hostilities between {faction} and {target} have begun. "
            "Border regions face immediate military pressure. "
            "Trade and diplomacy between the two factions are severed."
        ),
    },
    "form_alliance": {
        "severity": 9,
        "stage":    "emerging",
        "trend":    "rising",
        "template": "{faction} and {target} formalized an alliance.",
        "consequences_template": (
            "The alliance between {faction} and {target} reshapes the regional balance. "
            "Both factions' political influence rises. "
            "Rivals of either party now face a combined front."
        ),
    },
    "betray": {
        "severity": 13,
        "stage":    "escalating",
        "trend":    "rising",
        "template": "{faction} betrayed their alliance with {target}.",
        "consequences_template": (
            "{faction}'s betrayal of {target} sends a signal across all factions: "
            "no alliance is permanent. "
            "Trust in {faction} drops across the region. "
            "{target} faces an unexpected political and military crisis."
        ),
    },
    "stabilize_territory": {
        "severity": 4,
        "stage":    "emerging",
        "trend":    "stable",
        "template": "{faction} committed resources to stabilize {location}.",
        "consequences_template": (
            "The internal consolidation effort in {location} reduces unrest "
            "and strengthens {faction}'s administrative grip. "
            "Effects will compound if maintained across several ticks."
        ),
    },
}


def createEvent(log_entry, world):
    """Convert a decision-engine log entry into an active_event dict.

    Returns None for do_nothing or entries without enough context.
    The returned dict is compatible with _normalize_event and can be
    injected directly into world['active_events'].
    """
    action  = log_entry.get("action", "do_nothing")
    faction = log_entry.get("faction", "")
    meta    = log_entry.get("meta", {})

    if action == "do_nothing" or action not in _EVENT_META:
        return None

    target   = meta.get("target", "")
    location = meta.get("location", "")
    cfg      = _EVENT_META[action]

    fmt = {"faction": faction, "target": target or "unknown",
           "location": location or faction + "'s territory"}

    involved = [faction]
    if target:
        involved.append(target)
    if location:
        involved.append(location)

    if action == "declare_war":
        name = f"War Declared: {faction} vs {target}"
    elif action == "form_alliance":
        pair = tuple(sorted((faction, target)))
        name = f"Alliance Formed: {pair[0]} and {pair[1]}"
    elif action == "betray":
        name = f"Betrayal: {faction} turns on {target}"
    else:
        name = f"Stabilization: {faction} — {location or 'internal'}"

    return {
        "name":         name,
        "involved":     involved,
        "severity":     cfg["severity"],
        "stage":        cfg["stage"],
        "duration":     1,
        "trend":        cfg["trend"],
        "summary":      cfg["template"].format(**fmt),
        "consequences": cfg["consequences_template"].format(**fmt),
        "source":       "decision_engine",
        "action":       action,
        "faction":      faction,
        "meta":         meta,
    }


def executeEvent(event, world):
    """Apply full secondary effects of a decision-engine event to world state.

    applyDecision handles the primary mechanical mutation (relationship fields,
    power axes). executeEvent handles the remaining world-consistency updates:

      - Inject into active_events (dedup by name)
      - declare_war  → recalculate war_outcomes entry; add border location_event
      - form_alliance → purge war_targets entries between the new allies
      - betray        → add instability location_event in shared border regions
      - stabilize     → add positive location_event for the named location
    """
    action  = event.get("action", "")
    faction = event.get("faction", "")
    meta    = event.get("meta", {})
    target  = meta.get("target", "")
    loc_key = meta.get("location", "")
    tick    = int(world.get("tick", 0))

    # ── 1. Inject into active_events (deduplicated by name) ──────────────────
    existing_names = {e.get("name", "") for e in world.get("active_events", [])}
    if event["name"] not in existing_names:
        world.setdefault("active_events", []).append({
            k: v for k, v in event.items()
            if k not in ("action", "faction", "meta")
        })
        # Keep sorted by severity; trim to 10 (next full normalization trims to 8)
        world["active_events"].sort(key=lambda e: e.get("severity", 0), reverse=True)
        world["active_events"] = world["active_events"][:10]

    loc_events = world.setdefault("location_events", [])

    # ── 2. Action-specific secondary effects ─────────────────────────────────
    if action == "declare_war" and target:
        # Recalculate war_outcomes to include the new conflict immediately
        war_outcomes = world.setdefault("war_outcomes", [])
        pair = frozenset((faction, target))
        if not any(frozenset((o.get("attacker",""), o.get("defender",""))) == pair
                   for o in war_outcomes):
            outcome = _resolve_war_advantage(faction, target, world)
            war_outcomes.append(outcome)

        # Border pressure location_event on the defender's frontier locations
        for loc in world.get("locations", []):
            if loc.get("controller") == target:
                adj = set(loc.get("adjacent", []))
                # Check if any of attacker's territory is adjacent
                attacker_locs = {
                    l.get("name", "") for l in world.get("locations", [])
                    if l.get("controller") == faction
                }
                if adj & attacker_locs:
                    loc_events.append({
                        "type":     "war_border_pressure",
                        "location": loc.get("name", ""),
                        "attacker": faction,
                        "defender": target,
                        "detail": (
                            f"{faction}'s forces begin applying pressure on {loc.get('name','')}. "
                            f"Stability will erode if the offensive is sustained."
                        ),
                        "tick": tick,
                    })
                    break  # one border event per war declaration

    elif action == "form_alliance" and target:
        # Remove war_targets entries where the two new allies were targeting each other
        war_targets = world.get("war_targets", [])
        world["war_targets"] = [
            wt for wt in war_targets
            if not (
                wt.get("attacker") in (faction, target)
                and wt.get("defender") in (faction, target)
            )
        ]

        # Also remove any war_outcomes entry between them (shouldn't exist, but guard)
        world["war_outcomes"] = [
            o for o in world.get("war_outcomes", [])
            if not (
                frozenset((o.get("attacker",""), o.get("defender","")))
                == frozenset((faction, target))
            )
        ]

    elif action == "betray" and target:
        # Instability ripple in any border location between the former allies
        for loc in world.get("locations", []):
            ctrl = loc.get("controller", "")
            if ctrl not in (faction, target):
                continue
            other = target if ctrl == faction else faction
            adj = set(loc.get("adjacent", []))
            other_locs = {
                l.get("name", "") for l in world.get("locations", [])
                if l.get("controller") == other
            }
            if adj & other_locs:
                loc["stability"] = max(0, int(loc.get("stability", loc.get("control", 50))) - 5)
                loc_events.append({
                    "type":     "betrayal_border_unrest",
                    "location": loc.get("name", ""),
                    "detail": (
                        f"News of {faction}'s betrayal of {target} has reached {loc.get('name','')}. "
                        f"Local populations and garrisons grow uncertain. Stability has fallen."
                    ),
                    "tick": tick,
                })
                break  # one border event per betrayal

    elif action == "stabilize_territory" and loc_key:
        loc_events.append({
            "type":     "stabilization_effort",
            "location": loc_key,
            "faction":  faction,
            "detail": (
                f"{faction} has dispatched administrators and resources to {loc_key}. "
                f"Unrest is being actively suppressed. Control is expected to improve."
            ),
            "tick": tick,
        })


def _run_decision_engine(prev_state, new_state):
    """Orchestrate faction decisions for one tick with strict chaos controls.

    Priority budget (only one slot per type, resolved in priority order):
      1. crisis            — not yet engine-driven; reserved slot prevents spillover
      2. declare_war       — max 1 per tick, highest mechanical impact
      3. betray            — max 1 per tick, second-highest relationship damage
      4. form_alliance     — max 1 per tick, only fires if war + betray slots unused
      5. stabilize_territory — fills remaining budget (total cap: 3 non-trivial)

    A lower-priority type is only allowed if no higher-priority type has fired.
    do_nothing never counts against the budget.
    """
    import random

    # ── Per-type slot trackers ────────────────────────────────────────────────
    slot_used = {
        "declare_war":       False,
        "betray":            False,
        "form_alliance":     False,
        "stabilize_territory": 0,   # counts (up to 2 if no other action used a slot)
    }
    STAB_LIMIT = 2          # stabilize slots available when nothing else fires
    MAX_NONTRIVIAL = 3      # absolute ceiling across all types

    wars_this_tick:  set = set()   # frozenset (a, b) pairs — war just declared
    allies_this_tick: set = set()  # factions involved in a just-formed alliance
    nontrivial = 0
    decision_log = []

    # Priority ordering: high-impact factions evaluated first within each pass.
    # Shuffle within priority tiers so the same faction doesn't always win.
    factions = list(_DECISION_FACTIONS)
    random.shuffle(factions)

    for faction in factions:
        if nontrivial >= MAX_NONTRIVIAL:
            decision_log.append({
                "faction": faction, "action": "do_nothing", "meta": {},
                "summary": f"{faction} held position this tick (tick budget exhausted).",
            })
            continue

        evaluated = evaluateActions(faction, new_state)

        # ── Slot-based suppression ────────────────────────────────────────────
        # Zero out actions whose type slot is already consumed this tick
        if slot_used["declare_war"]:
            evaluated["declare_war"] = 0
        if slot_used["betray"]:
            evaluated["betray"] = 0
        if slot_used["form_alliance"]:
            evaluated["form_alliance"] = 0

        # Alliance only fires if neither war nor betray has triggered yet
        if slot_used["declare_war"] or slot_used["betray"]:
            evaluated["form_alliance"] = 0

        # Stabilize is limited; push toward do_nothing once cap is reached
        stab_cap = STAB_LIMIT if nontrivial == 0 else max(0, STAB_LIMIT - slot_used["stabilize_territory"])
        if slot_used["stabilize_territory"] >= stab_cap:
            evaluated["stabilize_territory"] = 0

        # War target just declared on this faction — don't let them ally same tick
        if any(faction in pair for pair in wars_this_tick):
            evaluated["form_alliance"] = 0
            evaluated["declare_war"]   = 0   # can't declare while absorbing a declaration

        action, meta = chooseAction(faction, new_state, evaluated)
        target = meta.get("target")

        # ── Hard conflict guards (last-line veto) ─────────────────────────────
        if action == "declare_war":
            pair = frozenset((faction, target)) if target else None
            if (
                not target
                or pair in wars_this_tick
                or target in allies_this_tick
                or slot_used["declare_war"]
            ):
                action, meta = "do_nothing", {}

        elif action == "form_alliance":
            if (
                not target
                or slot_used["form_alliance"]
                or slot_used["declare_war"]
                or slot_used["betray"]
                or any(faction in p or target in p for p in wars_this_tick)
            ):
                action, meta = "do_nothing", {}

        elif action == "betray":
            if not target or slot_used["betray"]:
                action, meta = "do_nothing", {}

        elif action == "stabilize_territory":
            if slot_used["stabilize_territory"] >= stab_cap:
                action, meta = "do_nothing", {}

        # ── Apply + emit event ────────────────────────────────────────────────
        log_entry = applyDecision(action, faction, meta, new_state)

        event = createEvent(log_entry, new_state)
        if event:
            executeEvent(event, new_state)
            log_entry["event_name"] = event["name"]

        decision_log.append(log_entry)

        # ── Update slot trackers ──────────────────────────────────────────────
        if action != "do_nothing":
            nontrivial += 1
            if action == "declare_war" and target:
                slot_used["declare_war"] = True
                wars_this_tick.add(frozenset((faction, target)))
            elif action == "betray" and target:
                slot_used["betray"] = True
                allies_this_tick.update((faction, target))
            elif action == "form_alliance" and target:
                slot_used["form_alliance"] = True
                allies_this_tick.update((faction, target))
            elif action == "stabilize_territory":
                slot_used["stabilize_territory"] += 1

    new_state["decision_log"] = decision_log


def _normalize_state(prev_state, new_state):
    prev_state = prev_state or {}
    try:
        if int(new_state.get("tick", 0)) != int(prev_state.get("tick", -1)):
            new_state.pop("_economy_engine_tick", None)
            new_state.pop("_economic_pressure_decisions_tick", None)
            new_state.pop("_military_ensure_tick", None)
            new_state.pop("_military_after_econ_tick", None)
            new_state.pop("_military_faction_decisions_tick", None)
            new_state.pop("_treaty_system_tick", None)
            new_state.pop("_marriage_succession_tick", None)
            new_state.pop("_tributary_system_tick", None)
            new_state.pop("_legitimacy_system_tick", None)
            new_state.pop("_diplomatic_faction_decisions_tick", None)
            new_state.pop("_birth_system_tick", None)
            new_state.pop("_death_lifecycle_tick", None)
            new_state.pop("_marriage_system_tick", None)
            new_state.pop("_family_politics_tick", None)
            new_state.pop("_house_lifecycle_tick", None)
            new_state.pop("_intrigue_system_tick", None)
            new_state.pop("_engine_tick", None)
    except (TypeError, ValueError):
        pass
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
    from economy_simulation import normalize_faction_economy_rows
    normalize_faction_economy_rows(prev_state, new_state)
    _normalize_population_state(prev_state, new_state)
    _normalize_locations(prev_state, new_state)
    _normalize_faction_power_state(prev_state, new_state)
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
    new_state["war_outcomes"] = _compute_active_war_outcomes(new_state)
    _update_location_control(new_state)
    _update_location_stability(new_state)
    _process_rebellions(new_state)
    _apply_power_shifts(prev_state, new_state)
    new_state["faction_dominance"] = _compute_faction_dominance(prev_state, new_state)
    _normalize_belief_currents(prev_state, new_state)
    _normalize_religious_factions(prev_state, new_state)
    _normalize_character_updates(prev_state, new_state)

    new_state.setdefault("faction_actions", [])
    new_state.setdefault("decision_log", [])
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
    new_state.setdefault("locations", [])
    new_state.setdefault("faction_event_pressure", [])
    new_state.setdefault("faction_power_state", [])
    new_state.setdefault("war_outcomes", [])
    new_state.setdefault("war_targets", [])
    new_state.setdefault("location_events", [])
    new_state.setdefault("emerging_factions", [])
    new_state.setdefault("faction_dominance", {})
    new_state.setdefault("belief_currents", [])
    new_state.setdefault("religious_factions", [])
    new_state.setdefault("whispers", [])
    new_state.setdefault("weather_and_omens", [])
    new_state.setdefault("absorbed_lore", [])
    new_state.setdefault("faction_economy", [])
    new_state.setdefault("resource_market", {})
    new_state.setdefault("economic_trade_routes", [])
    new_state.setdefault("economic_route_flows", {})
    new_state.setdefault("economic_disruption_price_mult", 1.0)
    new_state.setdefault("siege_warfare", {})
    new_state.setdefault("besieged_factions", [])
    new_state.setdefault("siege_grain_drain_by_faction", {})
    new_state.setdefault("siege_import_mult", 1.0)
    new_state.setdefault("siege_stress_add", 0.0)
    new_state.setdefault("economic_pressure_decisions", [])
    new_state.setdefault("military_faction_decisions", [])
    new_state.setdefault("treaties", [])
    new_state.setdefault("treaty_tick_outcomes", [])
    new_state.setdefault("diplomatic_standing", {})
    new_state.setdefault("world_treaty_order", 100.0)
    new_state.setdefault("noble_marriages", [])
    new_state.setdefault("character_marriages", [])
    new_state.setdefault("pending_marriage_pairs", [])
    new_state.setdefault("marriage_events", [])
    new_state.setdefault("succession_events", [])
    new_state.setdefault("birth_events", [])
    new_state.setdefault("death_events", [])
    new_state.setdefault(
        "tick_lifecycle",
        {
            "births": [],
            "deaths": [],
            "marriages": [],
            "succession_events": [],
        },
    )
    new_state.setdefault("dynastic_legitimacy", {})
    new_state.setdefault("dynastic_report", {"marriages": [], "claims": [], "potential_conflicts": []})
    new_state.setdefault("tributary_pacts", [])
    new_state.setdefault("tributary_resentment", {})
    new_state.setdefault(
        "tributary_report",
        {"tributaries": [], "payments": [], "tension_level": 0.0},
    )
    new_state.setdefault("ruler_legitimacy_scores", {})
    new_state.setdefault("legitimacy_report", [])
    new_state.setdefault("legitimacy_events", [])
    new_state.setdefault("diplomatic_faction_decisions", [])
    new_state.setdefault("intrigue_decisions", [])
    new_state.setdefault("faction_intrigue", [])
    new_state.setdefault("intrigue_pending", [])
    new_state.setdefault("intrigue_actions", [])
    new_state.setdefault("spy_networks", [])
    new_state.setdefault("assassination_reports", [])
    new_state.setdefault("sabotage_reports", [])
    new_state.setdefault("sabotage_price_stress", 0.0)
    new_state.setdefault("blackmail_reports", [])
    new_state.setdefault("active_blackmail_coercion", [])
    new_state.setdefault(
        "counterintelligence_report",
        {"detected_actions": [], "exposed_factions": [], "penalties": []},
    )
    new_state.setdefault("faction_armies", [])
    new_state.setdefault("military_attrition", [])
    new_state.setdefault("military_supply", [])
    new_state.setdefault("military_weather_attrition_mult", 1.0)

    return new_state


def _canonicalize_world_state(prev_state, state):
    """Return API-safe, normalized world state for persistence and responses."""
    normalized = _normalize_state(prev_state or {}, state or {})
    normalized = ensure_world_structure(normalized, prev_state or {})
    if not is_valid_world(normalized):
        logger.error("canonicalize: normalized world failed validation; returning previous state")
        return prev_state or normalized
    return normalized


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

    raw_input = response.content[0].input
    # Strip null bytes that Claude occasionally embeds in long string fields.
    # json.dumps → replace → json.loads is the safest round-trip approach.
    try:
        clean_json = json.dumps(raw_input).replace("\x00", "")
        raw_input = json.loads(clean_json)
    except Exception:
        pass  # if stripping fails, proceed with original

    result = _normalize_state(prev_state, raw_input)
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


def _advance_war_attrition(state):
    """Apply per-tick economic and military drain to every active war pair.

    Each tick of open war costs both sides:
      - Attacker: -2 eco, -1 mil base
      - Defender: -2 eco, -1 mil base
    The losing side (per war_outcomes verdict) pays an extra -1 on the axis
    they are already suffering on.  After 10 consecutive ticks a war-exhaustion
    event is injected so Claude can react to it in the next narrative pass.
    """
    power_map = {e["faction"]: e for e in state.get("faction_power_state", [])}
    if not power_map:
        return

    outcome_index: dict = {}
    for wo in state.get("war_outcomes", []):
        key = frozenset((wo.get("attacker", ""), wo.get("defender", "")))
        outcome_index[key] = float(wo.get("advantage", 0))

    exhaustion_events = []

    for rel in state.get("relationships", []):
        if rel.get("type") != "war":
            continue
        a = rel.get("faction_a", "")
        b = rel.get("faction_b", "")
        if not a or not b:
            continue

        # Track consecutive war ticks on the relationship row itself
        war_ticks = int(rel.get("war_ticks", 0)) + 1
        rel["war_ticks"] = war_ticks

        advantage = outcome_index.get(frozenset((a, b)), 0.0)
        # Positive = a is winning; negative = b is winning

        def _drain(faction, winning):
            if faction not in power_map:
                return
            pw = power_map[faction]
            eco_cost = 2 + (0 if winning else 1)
            mil_cost = 1 + (0 if winning else 1)
            pw["economicPower"] = max(0, int(pw.get("economicPower", 50)) - eco_cost)
            pw["militaryPower"] = max(0, int(pw.get("militaryPower", 50)) - mil_cost)

        _drain(a, winning=(advantage > 3))
        _drain(b, winning=(advantage < -3))

        # War-exhaustion threshold
        if war_ticks == 10:
            exhaustion_events.append({
                "name":   f"War Exhaustion: {a} and {b}",
                "involved": [a, b],
                "severity": 9,
                "stage":  "escalating",
                "duration": 1,
                "trend":  "rising",
                "summary": (
                    f"Ten ticks of sustained war between {a} and {b} have ground both sides down. "
                    f"Economies are strained, populations are war-weary, and political pressure "
                    f"for a resolution is beginning to build on both sides."
                ),
                "consequences": (
                    f"Further fighting accelerates collapse for the weaker side. "
                    f"Peace negotiations or a decisive offensive are the likely exits."
                ),
                "source": "war_attrition",
            })

    if exhaustion_events:
        existing_names = {e.get("name", "") for e in state.get("active_events", [])}
        for ev in exhaustion_events:
            if ev["name"] not in existing_names:
                state.setdefault("active_events", []).append(ev)
        state["active_events"].sort(key=lambda e: e.get("severity", 0), reverse=True)
        state["active_events"] = state["active_events"][:10]


def _archive_tick_events(state):
    """Append a concise mechanical summary of this tick to tick_history.

    Keeps the 50 most recent ticks.  Each entry records what the decision
    engine chose to do and the current war / alliance snapshot so the god
    panel and Claude can reference recent mechanical history.
    """
    decision_log = state.get("decision_log", [])
    nontrivial   = [e for e in decision_log if e.get("action") != "do_nothing"]

    entry = {
        "tick":       int(state.get("tick", 0)),
        "world_date": state.get("world_date", ""),
        "decisions": [
            {
                "faction": e.get("faction", ""),
                "action":  e.get("action",  ""),
                "target":  (e.get("meta") or {}).get("target", "")
                           or (e.get("meta") or {}).get("location", ""),
                "summary": e.get("summary", ""),
            }
            for e in nontrivial
        ],
        "events_fired": [
            e.get("event_name", "") for e in decision_log if e.get("event_name")
        ],
        "active_wars": [
            {
                "a": r.get("faction_a", ""),
                "b": r.get("faction_b", ""),
                "ticks": r.get("war_ticks", 0),
            }
            for r in state.get("relationships", []) if r.get("type") == "war"
        ],
        "alliances": [
            {"a": r.get("faction_a", ""), "b": r.get("faction_b", "")}
            for r in state.get("relationships", []) if r.get("type") == "alliance"
        ],
    }

    history = state.setdefault("tick_history", [])

    # No duplicates: drop any previous entry for this same tick number
    tick_num = entry["tick"]
    state["tick_history"] = [h for h in history if h.get("tick") != tick_num]
    state["tick_history"].append(entry)
    state["tick_history"] = sorted(state["tick_history"], key=lambda h: h.get("tick", 0))[-50:]


def _apply_tick_lifecycle_report(state: dict) -> None:
    """Unified marriage / birth / death / succession slice for the tick (API + tick_history)."""
    t = int(state.get("tick", 0) or 0)
    report = {
        "births": list(state.get("birth_events") or []),
        "deaths": list(state.get("death_events") or []),
        "marriages": list(state.get("marriage_events") or []),
        "succession_events": list(state.get("succession_events") or []),
    }
    state["tick_lifecycle"] = report
    for h in reversed(state.get("tick_history") or []):
        if h.get("tick") == t:
            h["tick_lifecycle"] = report
            break


def updateWorld(world, prev_world=None):
    """Execute one full mechanical tick on an already-normalized world state.

    This is the pure-mechanical layer — no Claude call, no external APIs,
    fully deterministic (uses random only for weighted action selection).

    Tick flow:
      1. Decision Engine — evaluate all factions, weighted action selection,
                           conflict guards, max 3 non-trivial actions
      2. Event Execution — createEvent + executeEvent for each chosen action
                           (relationships, territory, power, wars mutated in-place)
      3. War Attrition   — ongoing conflicts drain economy / military each tick;
                           10-tick wars trigger an exhaustion event
      4. History Archive — append a concise mechanical record to tick_history
      5. Faction armies    — ensure/merge `faction_armies` with prior tick; bootstrap if missing
      6. Economy           — P/C, stockpiles, shortages; grain and gold use summed army manpower
      7. Army field state    — supply, morale, desertion (after shortages are known)
      8. Economic pressure  — per-faction economic decisions (trade, taxes, raids, supply lines)
      9. Military strategy  — per-faction military posture (survival > supply > defense > expansion)
     10. Treaties         — expiration, breach detection vs. decisions and economy, trust and reputation
     11. Marriages         — eligible house pairs, political/internal unions, trust & diplomacy hooks
     12. Births           — children from `character_marriages`
     13. Intrigue         — covert ops (gold, agent stats); `pending_character_deaths` before deaths resolve
     14. House lifecycle  — age/heal house_characters, then deaths (succession on ruler death immediately)
     15. Dynastic         — `noble_marriages` report, cross-house claims, succession pressure
     16. Family politics  — house size, heirs, rival siblings, marriage-web ties
     17. Legitimacy      — ruler scores; feeds diplomacy & unrest
     18. Diplomacy       — per-faction diplomatic posture (sees new rulers and tensions)

    Args:
        world:      Already Claude-normalized world state dict (mutated in-place).
        prev_world: Previous tick's state for decision-engine context. Optional.

    Returns the mutated world dict.
    """
    if not world:
        return world

    try:
        from sim_engine_sanitize import sanitize_world_state

        sanitize_world_state(world)
    except Exception as e:
        logger.warning("sanitize_world_state in updateWorld: %s", e)

    # Guard: one engine pass per tick (prevents double-run if called more than once)
    tick = int(world.get("tick", 0))
    last_engine_tick = world.get("_engine_tick", -1)
    if last_engine_tick == tick:
        logger.debug(f"updateWorld skipped for tick {tick} — already ran this tick")
        return world
    world["_engine_tick"] = tick

    # ── 1 + 2. Decision Engine → Event Execution ─────────────────────────────
    _run_decision_engine(prev_world or {}, world)

    # ── 3. Ongoing War Attrition ──────────────────────────────────────────────
    _advance_war_attrition(world)

    # ── 4. Tick History ───────────────────────────────────────────────────────
    _archive_tick_events(world)

    # ── 5. Faction resource economy (production, consumption, shortages) ─────
    from military_simulation import ensure_faction_armies, run_military_after_economy_tick
    ensure_faction_armies(world, prev_world or {})

    from economy_simulation import run_faction_economy_tick
    run_faction_economy_tick(world, prev_world or {})

    from tributary_system import run_tributary_system
    run_tributary_system(world)

    run_military_after_economy_tick(world, prev_world or {})

    from economic_pressure_decisions import run_economic_pressure_decisions
    run_economic_pressure_decisions(world)

    from military_faction_decisions import run_military_faction_decisions
    run_military_faction_decisions(world)

    from treaty_system import run_treaty_system
    run_treaty_system(world)

    from marriage_system import run_marriage_system
    from birth_system import run_birth_system

    run_marriage_system(world)
    run_birth_system(world)
    from intrigue_system import run_intrigue_system
    run_intrigue_system(world)
    _normalize_house_characters(prev_world or {}, world)

    from marriage_succession import run_marriage_succession_tick
    run_marriage_succession_tick(world)

    from family_politics import run_family_politics
    run_family_politics(world)

    from legitimacy_system import run_legitimacy_system
    run_legitimacy_system(world)

    from diplomatic_faction_decisions import run_diplomatic_faction_decisions
    run_diplomatic_faction_decisions(world)

    _apply_tick_lifecycle_report(world)

    return world


def run_tick():
    with _lock:
        logger.info("Running world tick...")
        try:
            prev_state = _load_world_state()
            if not isinstance(prev_state, dict):
                logger.warning(
                    "run_tick: world_state.json was not an object (%s); using empty state fallback",
                    type(prev_state).__name__,
                )
                prev_state = {}
            pending_lore = _load_pending_lore()

            try:
                new_state = _call_claude(prev_state, pending_lore)
            except Exception as llm_exc:
                # Keep the world moving even if external LLM calls are unavailable
                # (for example: exhausted API credits, timeouts, provider outages).
                fallback_tick = int((prev_state or {}).get("tick", 0)) + 1
                fallback_day = f"Day {fallback_tick}"
                logger.warning(
                    "LLM tick generation failed; using local fallback simulation: %s",
                    llm_exc,
                )
                new_state = dict(prev_state or {})
                faction_identities = new_state.get("faction_identities", {})
                if isinstance(faction_identities, dict):
                    involved = list(faction_identities.keys())[:6]
                elif isinstance(faction_identities, list):
                    involved = [
                        row.get("name")
                        for row in faction_identities
                        if isinstance(row, dict) and row.get("name")
                    ][:6]
                else:
                    involved = []
                new_state["tick"] = fallback_tick
                new_state["world_date"] = fallback_day
                new_state["primary_event"] = {
                    "name": "The Clock Moves Without Prophecy",
                    "summary": (
                        "A quiet day passes without fresh divine insight. Existing tensions "
                        "and political momentum continue shaping Aeloria."
                    ),
                    "severity": 1,
                    "stage": "ongoing",
                    "trend": "stable",
                    "involved": involved,
                }
                fallback_note = {
                    "region": "Aeloria",
                    "text": (
                        "The day advanced under local simulation while the prophecy engine was unavailable."
                    ),
                    "impact": "low",
                }
                raw_recent = new_state.get("recent_events", [])
                if isinstance(raw_recent, list):
                    existing_recent = [row for row in raw_recent if isinstance(row, dict)]
                else:
                    existing_recent = []
                new_state["recent_events"] = [fallback_note] + existing_recent[:11]
            updateWorld(new_state, prev_world=prev_state)
            new_state = _canonicalize_world_state(prev_state, new_state)
            _ensure_character_portraits(new_state)
            _ensure_codex_images(new_state)
            new_state = _canonicalize_world_state(prev_state, new_state)
            _save_world_state(new_state)
            _save_history(new_state)
            _clear_pending_lore()

            send_tick_notification(new_state)
            logger.info(f"Tick {new_state['tick']} complete - {new_state.get('world_date')}")

            chronicle = _generate_chronicle(new_state)
            if chronicle:
                new_state["chronicle"] = chronicle
                new_state = _canonicalize_world_state(prev_state, new_state)
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
    tick_hours = int(os.getenv("TICK_INTERVAL_HOURS", "8"))
    _scheduler.add_job(run_tick, IntervalTrigger(hours=tick_hours), id="world_tick", replace_existing=True)
    _scheduler.add_job(
        _run_monday_story,
        CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
        id="monday_story",
        replace_existing=True,
    )
    if _scheduler.get_job("simulation_tick"):
        _scheduler.remove_job("simulation_tick")
    logger.info("Authoritative tick mode enabled: run_tick() is the only scheduled simulation path.")
    if not TEST_MODE:
        _scheduler.start()
        logger.info(f"Scheduler started - tick every {tick_hours}h, story every Monday 9am UTC.")
    else:
        logger.info("TEST_MODE=True — scheduler disabled, no background ticks.")

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


def pause_ticks() -> None:
    if _scheduler.running and _scheduler.get_job("world_tick"):
        _scheduler.pause_job("world_tick")
        logger.info("World tick paused for world switch.")


def resume_ticks() -> None:
    if _scheduler.running and _scheduler.get_job("world_tick"):
        _scheduler.resume_job("world_tick")
        logger.info("World tick resumed after world switch.")
