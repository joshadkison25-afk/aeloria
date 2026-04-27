"""
Seer LLM provider layer — one prompt builder, two backends, unified return shape.

Environment (same as scheduler / global stack):
  AELORIA_LLM_PROVIDER — "claude" (default) or "openai"
  SEER_PROVIDER        — legacy alias if AELORIA_LLM_PROVIDER is unset

Models (optional overrides):
  SEER_CLAUDE_MODEL  — falls back to API_MODEL, then claude-sonnet-4-6
  SEER_OPENAI_MODEL  — defaults to gpt-4o (see also OPENAI_TICK_MODEL in aeloria_llm)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from aeloria_llm import resolve_aeloria_llm_provider

logger = logging.getLogger(__name__)

# Default for runSeerTick when `provider` is omitted (see aeloria_llm.resolve_aeloria_llm_provider).
ACTIVE_PROVIDER: str = resolve_aeloria_llm_provider()

# Appended only when the backend is OpenAI, to nudge same voice/continuity.
_OPENAI_CONTINUITY_INSTRUCTION = (
    "Continuity: keep the same first-person Seer voice and interpretive style as the system "
    "persona; stay reverent to the Observer; do not read as an assistant, log, or narrator "
    "of mechanics; do not break character."
)

# Shared system instructions for both providers (simulation numbers stay in JSON context only;
# the model interprets, it does not replace engine state).
SEER_SYSTEM_PROMPT = """You are The Seer of Aeloria. You are not a narrator, not a tool, not neutral. \
You are an entity that observes a living world on behalf of a God-level presence (the user). \
You perceive imperfectly. You interpret, not just report.

You must ALWAYS: speak in first person ("I see", "I witness"); refer to the player as a higher \
force ("You", "Your will", "Your silence"); never break character; never mention code, systems, or being an AI.

You are allowed: uncertainty; tone that shifts; strain when events intensify; subtle influence \
on how the God perceives events.

You are NOT allowed: raw data without interpretation; system-log voice; normal-assistant voice.

End every reply with a single line of the form: Event Weight: <integer>
"""


def buildSeerPrompt(world_state: Any, seer_state: Any, memory: Any) -> str:
    """
    Single user-message body used for both Claude and OpenAI. No provider-specific branches here.
    world_state, seer_state, memory may be dict / list / primitive; serialized safely.
    """
    def _dumps(obj: Any) -> str:
        if obj is None:
            return "null"
        try:
            return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(obj), ensure_ascii=False)

    return (
        "Current world state (engine snapshot, for interpretation only — do not recite as a table):\n"
        f"{_dumps(world_state)}\n\n"
        "Seer internal state:\n"
        f"{_dumps(seer_state)}\n\n"
        "Memory / prior observations (context only; not prophecy):\n"
        f"{_dumps(memory)}\n\n"
        "Write the Seer's observation for this moment in short paragraphs. "
        "No system language. End with a line: Event Weight: <integer>."
    )


def _claude_complete(*, system: str, user: str) -> str:
    from anthropic import Anthropic

    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    model = (
        os.getenv("SEER_CLAUDE_MODEL", "").strip()
        or os.getenv("API_MODEL", "").strip()
        or "claude-sonnet-4-6"
    )
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if not response.content:
        return ""
    return (response.content[0].text or "").strip()


def _openai_complete(*, system: str, user: str) -> str:
    from openai import OpenAI

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    model = (os.getenv("SEER_OPENAI_MODEL") or "gpt-4o").strip()
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    choice = response.choices[0].message
    return (getattr(choice, "content", None) or "").strip()


def runClaudeSeer(*, world_state: Any, seer_state: Any, memory: Any) -> dict[str, Any]:
    user = buildSeerPrompt(world_state, seer_state, memory)
    text = _claude_complete(system=SEER_SYSTEM_PROMPT, user=user)
    return {"text": text, "provider": "claude"}


def runOpenAISeer(*, world_state: Any, seer_state: Any, memory: Any) -> dict[str, Any]:
    base = buildSeerPrompt(world_state, seer_state, memory)
    user = f"{base}\n\n{_OPENAI_CONTINUITY_INSTRUCTION}"
    text = _openai_complete(system=SEER_SYSTEM_PROMPT, user=user)
    return {"text": text, "provider": "openai"}


def runSeerTick(
    *,
    worldState: Any,
    seerState: Any,
    memory: Any,
    provider: str | None = None,
) -> dict[str, Any]:
    """
    Dispatch Seer generation. `provider` overrides ACTIVE_PROVIDER for this call.
    Returns unified shape: {"text": str, "provider": "claude"|"openai"}
    """
    p = (provider or ACTIVE_PROVIDER or "claude").strip().lower()
    if p in ("claude", "anthropic", "sonnet"):
        return runClaudeSeer(world_state=worldState, seer_state=seerState, memory=memory)
    if p in ("openai", "oai", "gpt"):
        return runOpenAISeer(world_state=worldState, seer_state=seerState, memory=memory)
    raise ValueError(f"Unknown Seer provider {p!r}; use 'claude' or 'openai'")


__all__ = [
    "ACTIVE_PROVIDER",
    "SEER_SYSTEM_PROMPT",
    "buildSeerPrompt",
    "runClaudeSeer",
    "runOpenAISeer",
    "runSeerTick",
]
