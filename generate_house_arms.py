"""Generate individual coat of arms images for each noble house."""
import os, base64, time, requests
from pathlib import Path

API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
MODEL   = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
SIZE    = "1024x1024"
OUT_DIR = Path(__file__).parent / "static" / "illustrations" / "ui" / "house-arms"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STYLE = (
    "Dark fantasy heraldic coat of arms card. Classic pointed shield shape centered on a near-black background. "
    "Style: painterly digital oil painting, cinematic dark fantasy, richly detailed aged illumination. "
    "The shield has ornate tarnished gold trim and decorative corner flourishes. "
    "Inside the shield: the house sigil rendered in deep rich colors with heavy shadow and texture — "
    "worn leather, etched metal, carved stone, brushed velvet depending on the house theme. "
    "The background behind the shield is dark charcoal or near-black with subtle vignette. "
    "Lighting is dramatic and moody — single directional light source, deep blacks, rich saturated midtones. "
    "No text, no letters, no words, no watermark, no motto ribbon. "
    "Centered composition, square format, high detail."
)

HOUSES = [
    {
        "slug": "house-adkison",
        "prompt": (
            "Coat of arms for House Adkison. A bold upright sword thrust through a fractured shield, "
            "deep crimson and iron-grey colour scheme, jagged angular lines suggesting aggression and ambition. "
            "The sword is dominant and sharp. Dark red and black tones. " + STYLE
        ),
    },
    {
        "slug": "house-aurand",
        "prompt": (
            "Coat of arms for House Aurand. A royal crown above a fleur-de-lis enclosed in a laurel wreath, "
            "rich gold on deep navy blue. Regal and legitimate, the heraldry of a ruling bloodline. "
            "Gold filigree and royal blue tones. " + STYLE
        ),
    },
    {
        "slug": "house-binx",
        "prompt": (
            "Coat of arms for House Binx. A great horned owl with wings spread wide, a crescent moon above it, "
            "deep purple and shadow-black colour scheme. Mysterious and watchful. "
            "A single gemstone at the crest, violet and obsidian tones. " + STYLE
        ),
    },
    {
        "slug": "house-dale",
        "prompt": (
            "Coat of arms for House Dale. A stone tower with battlements flanked by two eight-pointed stars, "
            "silver and charcoal grey on a dark earth-brown field. Ancient, enduring, rooted. "
            "Silver-grey and brown tones, worn stonework texture. " + STYLE
        ),
    },
    {
        "slug": "house-darkleaf",
        "prompt": (
            "Coat of arms for House Darkleaf. A great gnarled tree with roots spreading wide, a sword hidden vertically "
            "within the trunk. Forest green and shadow-black, the sigil of rangers and spymasters. "
            "Dark emerald green and black tones, bark texture. " + STYLE
        ),
    },
    {
        "slug": "house-fish",
        "prompt": (
            "Coat of arms for House Fish. A large leaping fish on a deep teal-green field, surrounded by water motifs. "
            "Old, patient, quiet power from the depths. Teal, sea-green, and dark blue tones, scales texture. " + STYLE
        ),
    },
    {
        "slug": "house-gross",
        "prompt": (
            "Coat of arms for House Gross. A balanced scale with heavy gold pans, deep burgundy and tarnished gold. "
            "The sigil of merchants, mediators, and dealers of influence. "
            "Dark wine-red and brass-gold tones. " + STYLE
        ),
    },
    {
        "slug": "house-highland",
        "prompt": (
            "Coat of arms for House Highland. Jagged mountain peaks with a small fortress silhouette at the base, "
            "slate grey and ice-white on a dark storm-blue field. Enduring, ancient, carved by wind. "
            "Slate-grey, stormy blue, and white tones. " + STYLE
        ),
    },
    {
        "slug": "house-van-cleave",
        "prompt": (
            "Coat of arms for House Van Cleave. Three swords arranged in a triangle pointing downward, "
            "silver-blue and iron-grey, the heraldry of discipline and martial tradition. "
            "The swords are precise and symmetrical. Steel-blue and silver tones. " + STYLE
        ),
    },
    {
        "slug": "house-ver-meer",
        "prompt": (
            "Coat of arms for House Ver Meer. A sea dragon or serpentine seahorse rearing up on a deep ocean-blue field, "
            "teal and sea-green scales, the lords of the tides. "
            "Ocean blue, teal, and dark aquamarine tones. " + STYLE
        ),
    },
    {
        "slug": "clan-ironmaul",
        "prompt": (
            "Coat of arms for Clan Ironmaul, a dwarven clan. A massive war-hammer crossed with a pickaxe "
            "on a field of dark granite grey, forge-orange glow in the background suggesting a great furnace. "
            "Iron, stone, and ember-orange tones, dwarven rune border. " + STYLE
        ),
    },
    {
        "slug": "goldfinger-duke-clan",
        "prompt": (
            "Coat of arms for the Goldfinger-Duke Clan, a dwarven clan. A gauntleted fist holding gold coins "
            "above a set of scales, rich gold and dark bronze tones on a deep brown field. "
            "Dwarven mercantile house, wealth and craft. Gold, bronze, and earth-brown tones. " + STYLE
        ),
    },
    {
        "slug": "runewardens-clan",
        "prompt": (
            "Coat of arms for the Runewardens Clan, a dwarven clan. An ancient rune stone with glowing carved "
            "symbols on a field of deep slate, silver-blue runic glow emanating from the stone. "
            "Guardians of ancient knowledge. Slate-grey, silver, and cold blue rune-glow tones. " + STYLE
        ),
    },
]


def generate(house):
    out = OUT_DIR / f"{house['slug']}.png"
    if out.exists():
        print(f"  SKIP  {house['slug']} (already exists)")
        return

    print(f"  GEN   {house['slug']} ...", end=" ", flush=True)
    try:
        r = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": MODEL, "prompt": house["prompt"], "size": SIZE},
            timeout=180,
        )
        if r.status_code != 200:
            print(f"FAIL ({r.status_code}) {r.text[:120]}")
            return
        data = (r.json().get("data") or [{}])[0].get("b64_json")
        if not data:
            print("FAIL (no b64_json)")
            return
        out.write_bytes(base64.b64decode(data))
        print("OK")
    except Exception as e:
        print(f"ERROR {e}")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        raise SystemExit(1)

    print(f"Generating {len(HOUSES)} house coat of arms into {OUT_DIR}\n")
    for i, house in enumerate(HOUSES):
        generate(house)
        if i < len(HOUSES) - 1:
            time.sleep(2)  # avoid rate limits

    print("\nDone.")
