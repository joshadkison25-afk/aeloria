"""
Global LLM backend for Aeloria (ticks, Seer, chronicle/synopsis, optional API chat).

- AELORIA_LLM_PROVIDER: "claude" (default) or "openai"
- If unset, SEER_PROVIDER is accepted as a legacy alias so one variable can still switch everything.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def resolve_aeloria_llm_provider() -> str:
    p = (os.getenv("AELORIA_LLM_PROVIDER") or os.getenv("SEER_PROVIDER") or "claude").strip().lower()
    if p in ("openai", "oai", "gpt"):
        return "openai"
    if p in ("claude", "anthropic", "sonnet"):
        return "claude"
    logger.warning("Unknown LLM provider %r; using claude", p)
    return "claude"


def openai_model_name() -> str:
    return (
        (os.getenv("OPENAI_TICK_MODEL") or "").strip()
        or (os.getenv("SEER_OPENAI_MODEL") or "").strip()
        or "gpt-4o"
    )


def claude_model_name() -> str:
    return (os.getenv("API_MODEL") or "claude-sonnet-4-6").strip()


def complete_chat_anthropic_format(
    *,
    system: str | None,
    messages: list[dict[str, Any]],
    max_tokens: int,
    openai_continuity: str | None = None,
) -> str:
    """
    One assistant reply. Same logical prompt for both providers: optional system, then `messages` (user/assistant turns only).
    For OpenAI only, `openai_continuity` is appended to the last user message when present.
    """
    prov = resolve_aeloria_llm_provider()
    if prov == "openai":
        from openai import OpenAI

        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        oai_messages: list[dict[str, str]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for i, m in enumerate(messages):
            last_user = i == len(messages) - 1 and m.get("role") == "user"
            content = m.get("content", "")
            if last_user and openai_continuity:
                content = f"{content}\n\n{openai_continuity}"
            oai_messages.append({"role": m["role"], "content": content})
        client = OpenAI(api_key=api_key)
        r = client.chat.completions.create(
            model=openai_model_name(),
            max_tokens=max_tokens,
            messages=oai_messages,
        )
        return (r.choices[0].message.content or "").strip()

    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    kwargs: dict[str, Any] = {
        "model": claude_model_name(),
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return (response.content[0].text or "").strip()
