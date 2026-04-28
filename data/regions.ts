/**
 * Macro region polygons in **pixel space** on the 1024 × 682 Shattered Crown basemap.
 * Coordinates: x → east, y → south (origin top-left).
 *
 * Geography (north → south):
 *   Frostvale (glacial north) · Lostfeld (mountain mining) · Farrock (NE headland)
 *   Faerwood (dense western forest) · Eldoria (noble heartland) · Gilgeth (eastern clans)
 *   Twin Cities (central plains) · Eresteron (fertile heartland) · Groth (badlands)
 *   Vilefin (SW rocky coast) · Dur Khadur (southern desert cape) · Glenwood (southeastern forest)
 *   Tidefall (eastern coastal ports) · Dreadwind Isles (offshore archipelago)
 */
export type RegionCoordinate = [number, number];

export type RegionDefinition = {
  id: string;
  name: string;
  description: string;
  coordinates: RegionCoordinate[];
  polygons?: RegionCoordinate[][];
};

/** Pixels: matches the 1024 × 682 Shattered Crown basemap. */
export const MAP_WIDTH = 1024;
export const MAP_HEIGHT = 682;

export const MAP_BOUNDS: [[number, number], [number, number]] = [
  [0, 0],
  [MAP_HEIGHT, MAP_WIDTH],
];

export const regions: RegionDefinition[] = [
  {
    id: 'frostvale',
    name: 'Frostvale',
    description:
      'The Wintermark — frozen highlands and glacial fjord coast crowning the north. High Lord Kaelen Adkison of House Adkison, with Houses McIntosh, Holter, and Duval. Rivers born here flow toward the Twin Cities and the sea.',
    coordinates: [
      [ 48, 212],
      [ 48,  60],
      [348,   8],
      [628,  42],
      [682,  56],
      [738,  86],
      [560, 150],
      [450, 140],
      [300, 180],
      [180, 220],
    ],
  },
  {
    id: 'lostfeld',
    name: 'Lostfeld',
    description:
      'Dwarven holds: forges, vaults, and clan thrones. High Thane Babadu Goldfinger-Duke, Clans Runewarden and Ironmaul. Debts and oaths are carved in stone.',
    coordinates: [
      [180, 220],
      [300, 180],
      [450, 140],
      [560, 150],
      [580, 280],
      [460, 310],
      [330, 310],
      [200, 290],
    ],
  },
  {
    id: 'farrock',
    name: 'Farrock',
    description:
      'Farrock: sole fortress and pass — the Van Cleave line. Professional soldiers who became a state. The Varkuun headland commands the Dreadwind channel.',
    coordinates: [
      [560, 150],
      [738,  86],
      [794, 134],
      [830, 198],
      [858, 275],
      [700, 310],
      [580, 280],
    ],
  },
  {
    id: 'faerwood',
    name: 'Faerwood',
    description:
      'Shadow Court — twilight forest and cragged uplands. Queen Lyathra, Houses Verlorn, Nightborn, and Shadowveil. Infiltration, not open war, is their way.',
    coordinates: [
      [ 35, 162],
      [ 48, 212],
      [180, 220],
      [200, 290],
      [180, 380],
      [140, 450],
      [ 82, 420],
      [ 38, 365],
      [ 34, 308],
    ],
  },
  {
    id: 'eldoria',
    name: 'Eldoria',
    description:
      'Noble and cultural center of the Twin Cities league — House LeFleur, Bower, Binx, and Dale. Courts, alliances, and quiet knives.',
    coordinates: [
      [330, 310],
      [460, 310],
      [580, 280],
      [700, 310],
      [680, 430],
      [560, 440],
      [430, 430],
      [320, 410],
    ],
  },
  {
    id: 'gilgeth',
    name: 'Gilgeth',
    description:
      'Iron Dominion — Clans Blackblood, Ironhide, and Redtusk. Council and hierarchy; Kragor Blackblood at the top. The eastern shield wall against the world.',
    coordinates: [
      [700, 310],
      [858, 275],
      [880, 355],
      [902, 405],
      [820, 450],
      [720, 460],
      [680, 430],
    ],
  },
  {
    id: 'twin_cities',
    name: 'Twin Cities',
    description:
      'Heartland seat of the High Kingdom — House Aurand. The urban crown of the Twin Cities league, where councils gather and trade flows.',
    coordinates: [
      [430, 430],
      [560, 440],
      [540, 530],
      [430, 530],
      [350, 510],
    ],
  },
  {
    id: 'eresteron',
    name: 'Eresteron',
    description:
      "Agricultural heartland — House Braafhart. Feeds the Twin Cities, pays the crown's price, and remembers every levy.",
    coordinates: [
      [560, 440],
      [680, 430],
      [720, 460],
      [700, 540],
      [600, 555],
      [540, 530],
    ],
  },
  {
    id: 'groth',
    name: 'Groth',
    description:
      "Badlands and war-proving ground: Clans Mijid, Ashfang, Syncar. Drogath Mijid's name is earned in blood. Groth has nearly broken the kingdoms before.",
    coordinates: [
      [200, 290],
      [330, 310],
      [320, 410],
      [280, 490],
      [192, 510],
      [135, 490],
      [140, 450],
      [180, 380],
    ],
  },
  {
    id: 'vilefin',
    name: 'Vilefin',
    description:
      'Scrap clans, stone plains, and three-way speakership. Clans Bloodware, Cogtooth, and Rustfang — Grikk holds the word for now. Rocky SW coastal cliffs.',
    coordinates: [
      [280, 490],
      [320, 410],
      [350, 510],
      [340, 580],
      [262, 560],
      [192, 530],
      [192, 510],
    ],
  },
  {
    id: 'dur_khadur',
    name: 'Dur Khadur',
    description:
      'Fortress and crossroads — Trade Prince Seran Gross, Houses Delonious, Galfazzar, and Vercenti. Merchant empire in stone. The Dur Khadur cape juts south as the desert trade chokepoint.',
    coordinates: [
      [700, 540],
      [820, 450],
      [890, 468],
      [865, 535],
      [880, 620],
      [820, 660],
      [672, 652],
      [600, 620],
      [600, 555],
    ],
  },
  {
    id: 'glenwood',
    name: 'Glenwood',
    description:
      'The Greenwood Enclave — Wood Elves under council. Houses Wood, Darkleaf, and Mistafae, with High Sovereign Thalorien. The southeastern old-growth forest, governed by protection, not conquest.',
    coordinates: [
      [600, 555],
      [700, 540],
      [600, 620],
      [508, 600],
      [430, 580],
      [430, 530],
      [540, 530],
    ],
  },
  {
    id: 'tidefall',
    name: 'Tidefall',
    description:
      'Admiralty, harbors, and the broken memory of the Saltborn Crown. Houses Ver Meer, Highland-Dusken, McGowan, and the island House Fish. The eastern coastal ports; sea is law.',
    coordinates: [
      [720, 460],
      [820, 450],
      [902, 405],
      [890, 468],
      [820, 450],
      [820, 450],
      [700, 540],
    ],
  },
  {
    id: 'dreadwind_isles',
    name: 'Dreadwind Isles',
    description:
      'Blacktide, salt, and exile — four islands in the long sea off the Farrock headland. House Blacktide and the deposed line did not beg for the crown: they left with the storm.',
    coordinates: [
      [ 920, 148],
      [1010, 248],
      [ 980, 295],
      [ 902, 208],
    ],
    polygons: [
      [[ 920, 148], [1010, 248], [ 980, 295], [ 902, 208]],
      [[ 935, 308], [1010, 368], [ 980, 400], [ 918, 332]],
      [[ 920, 412], [1015, 458], [ 998, 522], [ 910, 475]],
      [[ 925, 545], [ 988, 582], [ 965, 618], [ 908, 565]],
    ],
  },
];
