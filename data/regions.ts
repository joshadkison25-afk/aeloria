export type RegionCoordinate = [number, number];

export type RegionDefinition = {
  id: string;
  name: string;
  description: string;
  coordinates: RegionCoordinate[];
};

export const MAP_WIDTH = 2048;
export const MAP_HEIGHT = 1536;
export const MAP_BOUNDS: [[number, number], [number, number]] = [
  [0, 0],
  [MAP_HEIGHT, MAP_WIDTH],
];

export const regions: RegionDefinition[] = [
  {
    id: 'faerwood',
    name: 'Faerwood',
    description:
      'An ancient, oppressive woodland where shadowed paths, hidden courts, and old oaths are said to outlive kings.',
    coordinates: [
      [395, 610],
      [470, 515],
      [585, 468],
      [700, 505],
      [845, 620],
      [885, 840],
      [790, 1025],
      [655, 1065],
      [520, 990],
      [430, 865],
    ],
  },
  {
    id: 'eldoria',
    name: 'Eldoria',
    description:
      'The rich southern half of the Twin Cities sphere, a cultivated heartland of banners, roads, and ambitious nobles.',
    coordinates: [
      [835, 1125],
      [915, 995],
      [1090, 995],
      [1230, 1045],
      [1335, 1185],
      [1285, 1380],
      [1110, 1445],
      [930, 1395],
      [840, 1275],
    ],
  },
  {
    id: 'glenhaven',
    name: 'Glenhaven',
    description:
      'A green realm of silverwood groves and hidden courts, guarded by watchful rangers and old elven memory.',
    coordinates: [
      [760, 1335],
      [735, 1530],
      [820, 1730],
      [990, 1770],
      [1140, 1705],
      [1275, 1585],
      [1260, 1415],
      [1105, 1295],
      [905, 1265],
    ],
  },
  {
    id: 'eresteron',
    name: 'Eresteron',
    description:
      'A fortified river city at the center of power, where walls, councils, and intrigue converge at the crossings.',
    coordinates: [
      [760, 1110],
      [830, 1040],
      [940, 1035],
      [1035, 1100],
      [1050, 1215],
      [960, 1285],
      [855, 1280],
      [770, 1205],
    ],
  },
  {
    id: 'tidefall',
    name: 'Tidefall',
    description:
      'A harbor city of cliffs, ships, and storm-battered stone, where sea power speaks louder than any inland crown.',
    coordinates: [
      [1185, 1110],
      [1260, 1055],
      [1385, 1085],
      [1470, 1160],
      [1460, 1285],
      [1380, 1350],
      [1265, 1335],
      [1180, 1250],
    ],
  },
  {
    id: 'groth',
    name: 'Groth',
    description:
      'A hard mountain dominion in the north-east, scarred by war paths, raider holds, and the constant threat of winter.',
    coordinates: [
      [290, 1470],
      [260, 1660],
      [315, 1845],
      [470, 1780],
      [565, 1605],
      [515, 1445],
    ],
  },
  {
    id: 'lostfeld',
    name: 'Lostfeld',
    description:
      'A stern dwarven stronghold among broken ridges and old tunnels, famed for its forges and feared for what lies beneath.',
    coordinates: [
      [430, 1215],
      [390, 1365],
      [500, 1495],
      [655, 1450],
      [720, 1300],
      [640, 1170],
      [520, 1145],
    ],
  },
  {
    id: 'frostvale',
    name: 'Frostvale',
    description:
      'A cold northern settlement hidden among glacier roads, watch fires, and passes where messages arrive late or not at all.',
    coordinates: [
      [80, 860],
      [120, 990],
      [230, 1045],
      [330, 1000],
      [350, 850],
      [250, 760],
      [130, 770],
    ],
  },
  {
    id: 'dragonscar_peaks',
    name: 'Dragonscar Peaks',
    description:
      'The brutal mountain spine of the north-east, where dragon dominion, old ice, and broken passes shape every road below.',
    coordinates: [
      [170, 1210],
      [125, 1510],
      [260, 1850],
      [470, 1900],
      [575, 1650],
      [520, 1320],
      [335, 1150],
    ],
  },
  {
    id: 'rock_plains',
    name: 'Rock Plains',
    description:
      'A hard, exposed borderland of goblin markets, war tracks, stone shrines, and open ground where armies are seen early.',
    coordinates: [
      [620, 1375],
      [565, 1645],
      [695, 1870],
      [900, 1795],
      [930, 1495],
      [805, 1325],
    ],
  },
  {
    id: 'dreadwind_isles',
    name: 'Dreadwind Isles',
    description:
      'A storm-lashed pirate exile kingdom scattered across western islands, sea lanes, and hidden coves.',
    coordinates: [
      [1185, 215],
      [1080, 465],
      [1205, 700],
      [1435, 715],
      [1510, 445],
      [1395, 230],
    ],
  },
  {
    id: 'dur_khadur',
    name: 'Dur Khadur',
    description:
      'A far-eastern power of desert wealth and disciplined retinues, often arriving as trade before becoming pressure.',
    coordinates: [
      [310, 1770],
      [300, 1940],
      [455, 1995],
      [565, 1870],
      [510, 1730],
    ],
  },
  {
    id: 'farrock',
    name: 'Farrock',
    description:
      'A fortified eastern port and cliff settlement, watching the sea lanes where commerce, raids, and warnings converge.',
    coordinates: [
      [690, 1765],
      [655, 1935],
      [800, 2010],
      [935, 1905],
      [890, 1740],
    ],
  },
  {
    id: 'gilgeth',
    name: 'Gilgeth',
    description:
      'An orc stronghold in the southern ridges, bound by hard roads, old grievances, and the cost of surviving near rivals.',
    coordinates: [
      [1115, 1390],
      [1085, 1525],
      [1195, 1625],
      [1325, 1570],
      [1350, 1415],
      [1230, 1345],
    ],
  },
  {
    id: 'groth_stronghold',
    name: 'Groth Stronghold',
    description:
      'The southern redoubt of Groth power, a hard orc hold watching the same ridges as Gilgeth with little trust.',
    coordinates: [
      [1100, 1640],
      [1075, 1835],
      [1215, 1950],
      [1375, 1870],
      [1350, 1660],
      [1215, 1580],
    ],
  },
  {
    id: 'stonebreak',
    name: 'Stonebreak Monastery',
    description:
      'A druid monastery near the broken southern roads, where instruction, warning, and sacred observation become political acts.',
    coordinates: [
      [890, 1310],
      [845, 1430],
      [925, 1530],
      [1045, 1495],
      [1080, 1365],
      [995, 1280],
    ],
  },
];
