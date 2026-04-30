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


def _build_chronicle_context(state: dict) -> dict:
    """Extract structured engine outputs for narration. Pure function — no LLM calls."""
    tick = int(state.get("tick", 0) or 0)
    world_date = str(state.get("world_date") or f"Day {tick}")

    primary = state.get("primary_event") or {}
    if not isinstance(primary, dict):
        primary = {}

    supporting = [
        e for e in (state.get("supporting_events") or [])
        if isinstance(e, dict) and e.get("name")
    ][:3]

    ledger = state.get("causality_ledger") or []
    tick_causes = sorted(
        [r for r in ledger if isinstance(r, dict) and int(r.get("tick", -1) or -1) == tick],
        key=lambda r: int(r.get("severity", 1) or 1),
        reverse=True,
    )[:6]

    council = state.get("council_report") or {}
    top_risks = [
        r for r in (council.get("top_risks") or [])
        if isinstance(r, dict) and r.get("title")
    ][:4]

    dominant_beliefs = []
    for row in (state.get("faction_beliefs") or [])[:4]:
        if not isinstance(row, dict):
            continue
        faction = str(row.get("faction") or "").strip()
        candidates = [b for b in (row.get("beliefs") or []) if isinstance(b, dict)]
        if faction and candidates:
            top = max(candidates, key=lambda b: float(b.get("confidence", 0) or 0))
            dominant_beliefs.append({
                "faction": faction,
                "claim": str(top.get("claim") or ""),
                "confidence": float(top.get("confidence", 0) or 0),
            })

    active_events = [
        e for e in (state.get("active_events") or [])
        if isinstance(e, dict) and e.get("name")
    ][:4]

    return {
        "tick": tick,
        "world_date": world_date,
        "primary_event": primary,
        "supporting_events": supporting,
        "tick_causes": tick_causes,
        "top_risks": top_risks,
        "dominant_beliefs": dominant_beliefs,
        "active_events": active_events,
    }


def _format_chronicle_prompt(ctx: dict) -> str:
    """Build the narration prompt from a chronicle context dict."""
    lines = [
        f"You are the narrator of Aeloria, a living fantasy world. This is {ctx['world_date']} (tick {ctx['tick']}).",
        "",
        "Write 2-3 paragraphs of literary prose narrating what happened today.",
        "Past tense. Dark, cinematic tone. Specific names. No bullet points.",
        "Narrate from the engine truth below — do not invent events that contradict it.",
        "",
    ]

    primary = ctx["primary_event"]
    if primary.get("name"):
        lines.append(f"PRIMARY EVENT: {primary['name']}")
        if primary.get("summary"):
            lines.append(f"  {primary['summary']}")
        lines.append("")

    if ctx["supporting_events"]:
        lines.append("SUPPORTING EVENTS:")
        for e in ctx["supporting_events"]:
            lines.append(f"  - {e.get('summary') or e.get('name', '')}")
        lines.append("")

    if ctx["tick_causes"]:
        lines.append("CAUSAL RECORD (what happened and why):")
        for c in ctx["tick_causes"]:
            actor = c.get("actor", "Unknown")
            decision = str(c.get("decision") or "acted").replace("_", " ")
            outcome = c.get("outcome", "")
            pressure = c.get("pressure", "")
            parts = [f"{actor} {decision}"]
            if pressure:
                parts.append(f"under {pressure}")
            if outcome:
                parts.append(f"— {outcome}")
            lines.append(f"  - {' '.join(parts)}")
        lines.append("")

    if ctx["top_risks"]:
        lines.append("COUNCIL CONCERNS:")
        for r in ctx["top_risks"]:
            lines.append(f"  - {r['title']}: {r.get('summary', '')}")
        lines.append("")

    if ctx["dominant_beliefs"]:
        lines.append("WHAT FACTIONS BELIEVE (shapes their choices, may be wrong):")
        for b in ctx["dominant_beliefs"]:
            lines.append(f"  - {b['faction']}: {b['claim']}")
        lines.append("")

    return "\n".join(lines)


def _format_synopsis_prompt(state: dict, chronicle_context: str) -> str:
    """Build the synopsis prompt from engine outputs."""
    tick = int(state.get("tick", 0) or 0)
    world_date = str(state.get("world_date") or f"Day {tick}")

    council = state.get("council_report") or {}
    top_risks = [
        r for r in (council.get("top_risks") or [])
        if isinstance(r, dict) and r.get("title")
    ][:5]
    risk_text = "\n".join(f"- {r['title']}: {r.get('summary', '')}" for r in top_risks)

    active_events = [
        e for e in (state.get("active_events") or [])
        if isinstance(e, dict) and e.get("name")
    ][:5]
    event_text = "\n".join(
        f"- {e['name']} (severity {e.get('severity', '?')}): {e.get('summary', '')}"
        for e in active_events
    )

    return (
        f"You are the narrator of Aeloria, a living fantasy world now in tick {tick} ({world_date}).\n\n"
        f"RECENT CHRONICLE ENTRIES:\n{chronicle_context}\n\n"
        f"ENGINE TOP RISKS:\n{risk_text or '(none)'}\n\n"
        f"ACTIVE EVENTS:\n{event_text or '(none)'}\n\n"
        "Write a 2-3 paragraph narrative synopsis capturing the main story arc as it stands now.\n"
        "Find the narrative spine: the core conflict, the key players, the question the world is asking.\n"
        "Dark, literary, present-tense voice. End on the defining tension of this moment."
    )


def _generate_narrative_synopsis(state):
    try:
        chronicles = []
        if HISTORY_DIR.exists():
            for file in sorted(HISTORY_DIR.glob("chronicle_*.txt"))[-5:]:
                chronicles.append(file.read_text(encoding="utf-8"))
        chronicle_context = "\n\n---\n\n".join(chronicles) if chronicles else ""

        prompt = _format_synopsis_prompt(state, chronicle_context)
        text = _llm_prose_user_message(prompt, 800)
        SYNOPSIS_FILE.write_text(text, encoding="utf-8")
        logger.info("Narrative synopsis updated for tick %s", state.get("tick", 0))
        return text
    except Exception as exc:
        logger.error("Narrative synopsis generation failed: %s", exc)
        return ""


def _generate_chronicle(state):
    try:
        ctx = _build_chronicle_context(state)
        prompt = _format_chronicle_prompt(ctx)
        text = _llm_prose_user_message(prompt, 1200)
        HISTORY_DIR.mkdir(exist_ok=True)
        chronicle_path = HISTORY_DIR / f"chronicle_{state['tick']}.txt"
        chronicle_path.write_text(text, encoding="utf-8")
        logger.info("Chronicle written for tick %s", state["tick"])
        return text
    except Exception as exc:
        logger.error("Chronicle generation failed: %s", exc)
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
