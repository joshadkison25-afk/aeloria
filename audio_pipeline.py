import logging
import os
import re
from datetime import datetime
from pathlib import Path

import pdfplumber
import requests

from aeloria_llm import complete_chat_anthropic_format

logger = logging.getLogger(__name__)

WEEKLY_STORIES_DIR = Path(__file__).parent / "weekly_stories"


def _load_pdf(filepath: Path) -> str:
    texts = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)
    return "\n\n".join(texts)


def _load_lore_docs() -> tuple[str, str]:
    lore_path = os.getenv("LORE_DOCS_PATH", "")
    style_name = os.getenv("STYLE_GUIDE_NAME", "eryndor adventure").lower()

    if not lore_path or not Path(lore_path).exists():
        logger.warning(f"LORE_DOCS_PATH not found: {lore_path}")
        return "", ""

    lore_texts = []
    style_text = ""

    for filename in os.listdir(lore_path):
        if not filename.lower().endswith(".pdf"):
            continue
        filepath = Path(lore_path) / filename
        if style_name in filename.lower():
            style_text = _load_pdf(filepath)
        else:
            lore_texts.append(_load_pdf(filepath))

    return "\n\n".join(lore_texts), style_text


def _clean_for_tts(text: str) -> str:
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'_+', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _generate_script(world_state: dict, lore: str, style_guide: str) -> str:
    events = world_state.get("recent_events", [])
    event_text = "\n".join(f"- [{e['region']}] {e['text']}" for e in events)
    tensions = "\n".join(f"- {t['factions']}: {t['description']}" for t in world_state.get("active_tensions", []))
    whispers = "\n".join(f"- {w['text']} ({w['region']})" for w in world_state.get("whispers", []))

    world_context = f"World Date: {world_state.get('world_date', 'Unknown')}\n\nRecent Events:\n{event_text}"
    if tensions:
        world_context += f"\n\nActive Tensions:\n{tensions}"
    if whispers:
        world_context += f"\n\nWhispers:\n{whispers}"

    lore_section = f"--- AELORIA LORE ---\n{lore}\n--- END LORE ---\n\n" if lore else ""
    style_section = f"--- WRITING STYLE (match this voice exactly) ---\n{style_guide}\n--- END STYLE ---\n\n" if style_guide else ""

    prompt = f"""You are writing for a dark, cinematic YouTube fantasy lore channel set in the world of Aeloria.

{lore_section}{style_section}This week in Aeloria, the following unfolded:

{world_context}

Write an original, character-driven story set during or inspired by these events. You may invent original characters that fit naturally within the world — names, backgrounds, and motivations must be lore-accurate to Aeloria.

Do not include titles, part numbers, chapter headings, or introductions. Begin immediately with the first line of narration.

Style:
- sounds like a person telling a story, not a narrator reading one
- raw, emotional, imperfect — like someone who lived through it
- short sentences. fragments for impact. then longer ones that breathe.
- use "..." for natural hesitation, "—" for sudden breaks in thought
- no flowery language, no over-written descriptions
- vary the rhythm constantly so it never settles into a pattern
- never sound like an AI, a documentary, or an audiobook

Structure:
- strong hook
- character-driven narrative
- rising tension tied to the character's fate
- powerful, memorable ending
"""

    return complete_chat_anthropic_format(
        system=None,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        openai_continuity="Continuity: match the style constraints above; same gritty spoken-story voice.",
    )


def _generate_voice(script_text: str, output_path: Path):
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "xi-api-key": os.getenv("ELEVENLABS_API_KEY", ""),
        "Content-Type": "application/json",
    }
    data = {
        "text": script_text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.15,
            "similarity_boost": 0.85,
            "style": 0.7,
            "use_speaker_boost": True,
        },
    }

    response = requests.post(url, json=data, headers=headers, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text}")

    with open(output_path, "wb") as f:
        f.write(response.content)


def generate_weekly_story(world_state: dict):
    WEEKLY_STORIES_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    story_dir = WEEKLY_STORIES_DIR / date_str
    story_dir.mkdir(exist_ok=True)

    logger.info("Loading lore docs for weekly story...")
    lore, style_guide = _load_lore_docs()

    logger.info("Generating weekly story script...")
    script = _generate_script(world_state, lore, style_guide)

    script_path = story_dir / "script.txt"
    script_path.write_text(script, encoding="utf-8")
    logger.info(f"Script saved to {script_path}")

    audio_path = story_dir / "narration.mp3"
    logger.info("Generating voice narration...")
    _generate_voice(_clean_for_tts(script), audio_path)
    logger.info(f"Weekly story saved to {story_dir}")
    return story_dir
