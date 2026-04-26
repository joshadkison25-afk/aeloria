/**
 * Region polygons in **pixel space** — tune to your basemap in `public/` (default: `aeloria-basemap-paint.png`)
 * (and the labeled reference): **1024 × 682**. Coordinates: x → east, y → south.
 * Layout follows the art: Wintermark north; Shadow Court (Faerwood) NW; Glenhaven west;
 * Lostfeld & Stonebreak west-central; Twin Cities heartland (Eresteron + Eldoria); Groth NE;
 * Gilgeth & Dur Khadur east; Tidefall & Varkuun & Vilefin south; Dreadwind Isles open ocean SE–E.
 */
export type RegionCoordinate = [number, number];

export type RegionDefinition = {
  id: string;
  name: string;
  description: string;
  coordinates: RegionCoordinate[];
};

/** Pixels: matches the isometric / labeled basemap art. */
export const MAP_WIDTH = 1024;
export const MAP_HEIGHT = 682;

export const MAP_BOUNDS: [[number, number], [number, number]] = [
  [0, 0],
  [MAP_HEIGHT, MAP_WIDTH],
];

export const regions: RegionDefinition[] = [
  {
    id: 'frostvale',
    name: 'The Wintermark',
    description:
      'Frozen highlands and glacial passes — the crown of the north. High Lord Kaelen Adkison of House Adkison, with Houses McIntosh, Holter, and Duval. Rivers born here flow toward the Twin Cities and the sea.',
    coordinates: [
      [400, 24],
      [640, 20],
      [680, 200],
      [500, 220],
      [360, 140],
    ],
  },
  {
    id: 'faerwood',
    name: 'Shadow Court',
    description:
      'Twilight forest and cragged uplands: seat of the Shadow Court — Queen Lyathra, Houses Verlorn, Nightborn, and Shadowveil. Infiltration, not open war, is their way.',
    coordinates: [
      [32, 96],
      [380, 72],
      [440, 300],
      [300, 440],
      [120, 400],
      [40, 260],
    ],
  },
  {
    id: 'glenhaven',
    name: 'Glenhaven',
    description:
      'The Greenwood Enclave: Wood Elves under council (Wood, Darkleaf, Mistafae) and High Sovereign Thalorien. The forest is governed by protection, not conquest.',
    coordinates: [
      [16, 300],
      [220, 280],
      [280, 540],
      [72, 600],
      [20, 480],
    ],
  },
  {
    id: 'lostfeld',
    name: 'Lostfeld',
    description:
      'Dwarven holds: forges, vaults, and clan thrones. High Thane Babadu Goldfinger-Duke, Runewarden and Ironmaul. Debts and oaths are carved in stone.',
    coordinates: [
      [280, 300],
      [480, 280],
      [520, 480],
      [360, 520],
      [260, 420],
    ],
  },
  {
    id: 'stonebreak',
    name: 'Stonebreak Monastery',
    description:
      'Ring of stone around a living vale — Grand Druid Varak, neutrality in public, the Gloomspire in the shadows. Healing, ritual, and old observation.',
    coordinates: [
      [320, 400],
      [420, 384],
      [448, 480],
      [360, 508],
      [300, 456],
    ],
  },
  {
    id: 'eresteron',
    name: 'Eresteron',
    description:
      'Agricultural heartland of the High Kingdom — the Braafhart duchy. Feeds the Twin Cities, pays the crown’s price, and remembers every levy.',
    coordinates: [
      [480, 360],
      [620, 344],
      [656, 500],
      [520, 544],
      [448, 472],
    ],
  },
  {
    id: 'eldoria',
    name: 'Eldoria',
    description:
      'Noble and cultural center — House LeFleur, alliances, courts, and quiet knives. The other crown of the Twin Cities.',
    coordinates: [
      [620, 344],
      [800, 392],
      [824, 520],
      [700, 552],
      [636, 496],
    ],
  },
  {
    id: 'groth',
    name: 'Groth',
    description:
      'Badlands and war-proving ground: Mijid, Ashfang, Syncar. Drogath Mijid’s name is earned in blood. Groth has nearly broken the kingdoms before.',
    coordinates: [
      [680, 32],
      [1008, 48],
      [1016, 240],
      [800, 280],
      [700, 160],
    ],
  },
  {
    id: 'gilgeth',
    name: 'Gilgeth',
    description:
      'Iron Dominion: Blackblood, Ironhide, Redtusk. Council and hierarchy; Kragor Blackblood at the top. The eastern shield wall against the world.',
    coordinates: [
      [760, 280],
      [1000, 320],
      [980, 500],
      [800, 484],
      [748, 380],
    ],
  },
  {
    id: 'dur_khadur',
    name: 'Dur Khadur',
    description:
      'Fortress and crossroads — Trade Prince Seran Gross, merchant empire in stone. Aligned with power, not sermons.',
    coordinates: [
      [700, 480],
      [900, 512],
      [880, 620],
      [700, 600],
      [660, 540],
    ],
  },
  {
    id: 'tidefall',
    name: 'Tidefall',
    description:
      'Admiralty, harbors, and the broken memory of the Saltborn Crown. Levi Ver Meer and the great houses: sea is law.',
    coordinates: [
      [360, 500],
      [580, 488],
      [700, 640],
      [480, 672],
      [360, 600],
    ],
  },
  {
    id: 'farrock',
    name: 'Varkuun',
    description:
      'Farrock: sole fortress and pass — the Van Cleave line. Professional soldiers who became a state.',
    coordinates: [
      [500, 520],
      [620, 500],
      [660, 620],
      [540, 656],
      [480, 580],
    ],
  },
  {
    id: 'vilefin',
    name: 'Vilefin',
    description:
      'Scrap clans, stone plains, and three-way speakership. Bloodware, Cogtooth, Rustfang — Grikk holds the word for now.',
    coordinates: [
      [680, 540],
      [1008, 500],
      [1008, 660],
      [720, 676],
    ],
  },
  {
    id: 'dreadwind_isles',
    name: 'Dreadwind Isles',
    description:
      'Blacktide, salt, and exile — isles in the long sea. Ronan and the deposed line did not beg for the crown: they left with the storm.',
    coordinates: [
      [860, 180],
      [1000, 160],
      [1004, 400],
      [900, 420],
    ],
  },
];
