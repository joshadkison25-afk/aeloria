"""
_manual_tick.py
Advances the current world_state.json by N ticks, then
optionally copies the result into a worlds/ slot.

Usage:
    python _manual_tick.py           # 2 ticks, saves back to world_state.json only
    python _manual_tick.py 3         # 3 ticks
"""
import sys
import json
import shutil
from pathlib import Path

# Load .env BEFORE importing anything from the project so the API key is present
from dotenv import load_dotenv
load_dotenv()

from scheduler import run_tick  # noqa: E402  (needs dotenv loaded first)

WORLD_STATE = Path("world_state.json")
WORLDS_DIR  = Path("worlds")
TARGET_SLOT = "Run 1.json"  # set to None to skip slot copy

n_ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 2

# ── Print starting state ──────────────────────────────────────────────────────
with open(WORLD_STATE, encoding="utf-8") as f:
    start = json.load(f)
print(f"Starting: tick {start.get('tick')} | {start.get('world_date')}")

# ── Run ticks ─────────────────────────────────────────────────────────────────
for i in range(1, n_ticks + 1):
    print(f"\nRunning tick {i}/{n_ticks}...")
    world = run_tick()
    print(f"  -> tick {world.get('tick')} | {world.get('world_date')}")
    ev = world.get("primary_event")
    if isinstance(ev, dict):
        ev = ev.get("name") or ev.get("summary") or ""
    print(f"     {str(ev)[:80]}")

# ── Copy result to slot ───────────────────────────────────────────────────────
if TARGET_SLOT:
    dest = WORLDS_DIR / TARGET_SLOT
    shutil.copy2(WORLD_STATE, dest)
    print(f"\nCopied current world -> worlds/{TARGET_SLOT}")

print("\nDone.")
