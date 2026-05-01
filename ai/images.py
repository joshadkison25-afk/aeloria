import base64
import json
import os
from datetime import datetime

from axiom.world_state.io import (
    BASE_DIR,
    CODEX_IMAGE_JOBS_FILE,
    PORTRAIT_JOBS_FILE,
    _load_image_generation_state,
    _load_portrait_jobs,
    _save_image_generation_state,
    _save_portrait_jobs,
    _slugify_filename,
)

CHARACTER_PORTRAIT_DIR = BASE_DIR / "static" / "illustrations" / "characters"
CODEX_IMAGE_DIR = BASE_DIR / "static" / "illustrations" / "codex"


def _image_generation_day(state):
    return int(state.get("tick") or 0)


def _can_attempt_daily_image(state):
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return False
    throttle = _load_image_generation_state()
    return throttle.get("last_attempt_tick") != _image_generation_day(state)


def _record_daily_image_attempt(state, kind, name, ok, error=""):
    _save_image_generation_state(
        {
            "last_attempt_tick": _image_generation_day(state),
            "last_attempt_at": datetime.now().isoformat(),
            "kind": kind,
            "name": name,
            "status": "completed" if ok else "failed",
            "error": error,
        }
    )


def _generate_character_portrait(character, output_path):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY is not set."

    import requests

    prompt = character.get("portrait_prompt") or (
        f"Portrait of {character.get('name', 'an Aeloria character')}, "
        f"{character.get('faction', 'Aeloria')}."
    )
    prompt = (
        f"{prompt}\n\n"
        "Medieval noble portrait, Crusader Kings 3 style, realistic painted portrait, detailed face, "
        "cinematic lighting, dark background, soft shadows, oil painting style, ultra detailed, "
        "3/4 view, serious expression, historically inspired clothing, muted colors, high realism, depth of field. "
        "No text, no letters, no watermark, no UI frame, no border."
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                "prompt": prompt,
                "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            },
            timeout=180,
        )
        if response.status_code != 200:
            return False, f"OpenAI image generation failed: {response.status_code} {response.text[:300]}"

        payload = response.json()
        image_data = (payload.get("data") or [{}])[0].get("b64_json")
        if not image_data:
            return False, "OpenAI image response did not include b64_json image data."

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _generate_codex_image(prompt, output_path):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return False, "OPENAI_API_KEY is not set."

    import requests

    final_prompt = (
        f"{prompt}\n\n"
        "Style: photorealistic dark fantasy illustration, Crusader Kings / game card cinematic aesthetic. "
        "Rich deep colours - black, dark brown, charcoal, with gold or silver accents. "
        "Dramatic directional lighting with deep shadows. "
        "No text, no letters, no watermark, no logo. "
        "Dark edges suitable for a lore card on a dark UI."
    )

    try:
        response = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
                "prompt": final_prompt,
                "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
            },
            timeout=180,
        )
        if response.status_code != 200:
            return False, f"OpenAI image generation failed: {response.status_code} {response.text[:300]}"

        payload = response.json()
        image_data = (payload.get("data") or [{}])[0].get("b64_json")
        if not image_data:
            return False, "OpenAI image response did not include b64_json image data."

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _ensure_character_portraits(state):
    CHARACTER_PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    jobs = _load_portrait_jobs()
    existing_jobs = {job.get("name"): job for job in jobs if job.get("name")}
    changed = False
    characters = list(state.get("character_updates", []))

    for row in state.get("leadership_state", []):
        ruler = row.get("currentRuler") or {}
        name = (ruler.get("name") or "").strip()
        if not name:
            continue
        characters.append(
            {
                "name": name,
                "faction": row.get("faction", "Unknown"),
                "dynasty": ruler.get("dynasty", "Unknown Dynasty"),
                "status": f"{ruler.get('title', 'Ruler')} of {row.get('faction', 'Aeloria')}",
                "appearance": "",
                "portrait_prompt": (
                    f"Dark fantasy ruler portrait of {ruler.get('title', 'Ruler')} {name}, "
                    f"{row.get('faction', 'Aeloria')}, {ruler.get('dynasty', 'noble dynasty')}, "
                    "lore accurate Aeloria aesthetic, no text, no watermark."
                ),
                "portrait_image": ruler.get("portrait_image", ""),
                "_leadership_row": row,
                "_leadership_ruler": ruler,
            }
        )

    for character in characters:
        name = (character.get("name") or "").strip()
        if not name:
            continue

        slug = _slugify_filename(name)
        image_path = CHARACTER_PORTRAIT_DIR / f"{slug}.png"
        static_path = f"/static/illustrations/characters/{slug}.png"

        if image_path.exists():
            if character.get("portrait_image") != static_path:
                character["portrait_image"] = static_path
                if character.get("_leadership_ruler") is not None:
                    character["_leadership_ruler"]["portrait_image"] = static_path
                changed = True
            continue

        job = existing_jobs.get(name)
        if not job:
            job = {
                "name": name,
                "faction": character.get("faction", "Unknown"),
                "prompt": character.get("portrait_prompt", ""),
                "target_file": str(image_path),
                "static_path": static_path,
                "status": "queued",
                "created_tick": state.get("tick"),
                "created_at": datetime.now().isoformat(),
            }
            jobs.append(job)
            existing_jobs[name] = job

        if _can_attempt_daily_image(state) and job.get("status") != "completed":
            ok, error = _generate_character_portrait(character, image_path)
            job["last_attempt_at"] = datetime.now().isoformat()
            _record_daily_image_attempt(state, "character", name, ok, error)
            if ok:
                job["status"] = "completed"
                job["error"] = ""
                character["portrait_image"] = static_path
                if character.get("_leadership_ruler") is not None:
                    character["_leadership_ruler"]["portrait_image"] = static_path
                changed = True
            else:
                job["status"] = "failed"
                job["error"] = error

    _save_portrait_jobs(jobs)
    return changed


def _daily_image_already_attempted(state):
    throttle = _load_image_generation_state()
    return throttle.get("last_attempt_tick") == _image_generation_day(state)


def _queue_codex_image(jobs, existing_jobs, kind, name, prompt, state):
    slug = _slugify_filename(f"{kind}-{name}")
    image_path = CODEX_IMAGE_DIR / f"{slug}.png"
    static_path = f"/static/illustrations/codex/{slug}.png"

    if image_path.exists():
        return static_path, False

    key = f"{kind}:{name}"
    job = existing_jobs.get(key)
    if not job:
        job = {
            "key": key,
            "kind": kind,
            "name": name,
            "prompt": prompt,
            "target_file": str(image_path),
            "static_path": static_path,
            "status": "queued",
            "created_tick": state.get("tick"),
            "created_at": datetime.now().isoformat(),
        }
        jobs.append(job)
        existing_jobs[key] = job

    if _can_attempt_daily_image(state) and job.get("status") != "completed":
        ok, error = _generate_codex_image(prompt, image_path)
        job["last_attempt_at"] = datetime.now().isoformat()
        _record_daily_image_attempt(state, kind, name, ok, error)
        if ok:
            job["status"] = "completed"
            job["error"] = ""
            return static_path, True
        job["status"] = "failed"
        job["error"] = error

    return "", False


def _ensure_codex_images(state):
    CODEX_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    jobs = _load_portrait_jobs() if CODEX_IMAGE_JOBS_FILE == PORTRAIT_JOBS_FILE else []
    if CODEX_IMAGE_JOBS_FILE.exists():
        try:
            jobs = json.loads(CODEX_IMAGE_JOBS_FILE.read_text(encoding="utf-8"))
            if not isinstance(jobs, list):
                jobs = []
        except Exception:
            jobs = []

    existing_jobs = {job.get("key"): job for job in jobs if job.get("key")}
    changed = False
    images = state.setdefault("codex_images", {})

    for row in state.get("faction_morale", []):
        name = row.get("faction")
        if not name:
            continue
        prompt = f"Faction illustration for {name}: {row.get('reason', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "faction", name, prompt, state)
        if static_path:
            images[f"Factions:{name}"] = static_path
        changed = changed or did_change

    if _daily_image_already_attempted(state):
        CODEX_IMAGE_JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        return changed

    for row in state.get("recent_events", []):
        region = (row.get("region") or "").split("-")[0].strip()
        if not region:
            continue
        prompt = f"Location illustration for {region}: {row.get('text', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "place", region, prompt, state)
        if static_path:
            images[f"Places:{region}"] = static_path
        changed = changed or did_change

    event_sources = [state.get("primary_event"), *state.get("supporting_events", [])]
    for event in [event for event in event_sources if event and event.get("name")]:
        prompt = f"Major lore event illustration for {event.get('name')}: {event.get('summary', '')}"
        static_path, did_change = _queue_codex_image(jobs, existing_jobs, "lore", event.get("name"), prompt, state)
        if static_path:
            images[f"Lore:{event.get('name')}"] = static_path
        changed = changed or did_change

    CODEX_IMAGE_JOBS_FILE.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
    return changed
