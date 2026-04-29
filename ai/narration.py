import json
import logging
import os
import re
from pathlib import Path

import requests

from aeloria_llm import openai_model_name, resolve_aeloria_llm_provider

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
HISTORY_DIR = BASE_DIR / "history"
SYNOPSIS_FILE = BASE_DIR / "narrative_synopsis.txt"
AUDIO_DIR = BASE_DIR / "static" / "audio"

def _llm_prose_user_message(prompt: str, max_tokens: int) -> str:
    """
    Chronicle and synopsis: one user message, no system prompt. Same `prompt` for both providers;
    OpenAI gets a short continuity line appended to preserve voice.
    """
    prov = resolve_aeloria_llm_provider()
    if prov == "openai":
        from openai import OpenAI

        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        client = OpenAI(api_key=api_key)
        p = (
            prompt
            + "\n\nContinuity: keep the same dark literary Aeloria narrative voice; no meta-commentary, no preface, no out-of-world framing."
        )
        response = client.chat.completions.create(
            model=openai_model_name(),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": p}],
        )
        return (response.choices[0].message.content or "").strip()

    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=os.getenv("API_MODEL", "claude-sonnet-4-6"),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return (response.content[0].text or "").strip()


def _generate_narrative_synopsis(state):
    try:
        chronicles = []
        if HISTORY_DIR.exists():
            for file in sorted(HISTORY_DIR.glob("chronicle_*.txt"))[-5:]:
                chronicles.append(file.read_text(encoding="utf-8"))

        chronicle_context = "\n\n---\n\n".join(chronicles) if chronicles else ""
        current_tick = state.get("tick", 0)
        world_date = state.get("world_date", "")
        tensions = state.get("active_tensions", [])
        tension_text = "\n".join(
            f"- {item.get('factions', item.get('faction', '?'))}: {item.get('description', item.get('summary', str(item)))}"
            for item in tensions if isinstance(item, dict)
        )

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

        text = _llm_prose_user_message(prompt, 800)
        SYNOPSIS_FILE.write_text(text, encoding="utf-8")
        logger.info(f"Narrative synopsis updated for tick {current_tick}")
        return text
    except Exception as exc:
        logger.error(f"Narrative synopsis generation failed: {exc}")
        return ""


def _generate_chronicle(state):
    try:
        prompt = (
            "You are the narrator of Aeloria. Write 2-3 evocative paragraphs describing what happened "
            "this day in the world. Write in past tense, literary prose, as if narrating an epic fantasy novel. "
            f"Draw from these events: {json.dumps(state, indent=2)}. "
            "Do not use bullet points. Be specific with character names and place names. "
            "Write in a dark, cinematic tone."
        )
        text = _llm_prose_user_message(prompt, 1200)
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
