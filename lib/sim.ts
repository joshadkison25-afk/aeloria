// lib/sim.ts
// Core simulation engine for Aeloria

export interface Faction {
  name: string;
  goal: 'expand' | 'survive' | 'convert';
  trait: 'aggressive' | 'paranoid' | 'spiritual';
}

export interface WorldState {
  factions: Faction[];
}

export interface Event {
  text: string;
}

// Initialize world with some factions
const initialFactions: Faction[] = [
  { name: 'The Iron Covenant', goal: 'expand', trait: 'aggressive' },
  { name: 'The Whispering Veil', goal: 'survive', trait: 'paranoid' },
  { name: 'The Celestial Order', goal: 'convert', trait: 'spiritual' },
];

let worldState: WorldState = {
  factions: initialFactions,
};

const actions = ['attack', 'ally', 'spread belief', 'investigate omen'] as const;
type Action = typeof actions[number];

function getRandomAction(): Action {
  return actions[Math.floor(Math.random() * actions.length)];
}

function generateEventText(faction: Faction, action: Action): string {
  const templates = {
    attack: [
      `${faction.name} launches a fierce assault on neighboring lands, driven by their ${faction.trait} nature.`,
      `In a display of ${faction.trait} aggression, ${faction.name} strikes at their enemies.`,
    ],
    ally: [
      `${faction.name}, seeking ${faction.goal}, forms an uneasy alliance with another power.`,
      `${faction.name} extends a hand of friendship, their ${faction.trait} caution guiding them.`,
    ],
    'spread belief': [
      `${faction.name} sends missionaries to convert the unbelievers, fulfilling their ${faction.goal}.`,
      `Whispers of ${faction.name}'s faith spread through the lands, their ${faction.trait} devotion evident.`,
    ],
    'investigate omen': [
      `${faction.name} consults ancient omens, their ${faction.trait} nature making them wary.`,
      `Mysterious signs lead ${faction.name} to investigate hidden truths.`,
    ],
  };

  const template = templates[action][Math.floor(Math.random() * templates[action].length)];
  return template;
}

export function runTick(): Event {
  const events: string[] = [];

  for (const faction of worldState.factions) {
    const action = getRandomAction();
    const eventText = generateEventText(faction, action);
    events.push(eventText);
  }

  // Combine events into one narrative
  const combinedText = events.join(' Meanwhile, ');

  return {
    text: combinedText,
  };
}