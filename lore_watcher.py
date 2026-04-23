import json
import logging
import os
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
PENDING_LORE_FILE = BASE_DIR / "pending_lore.json"
LORE_DIR = BASE_DIR / "lore"

_observer = None


class LoreHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in (".md", ".txt"):
            self._absorb(path)

    def _absorb(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return

            pending = _load_pending()
            pending.append({
                "text": text,
                "source_file": path.name,
                "received_at": datetime.now().isoformat(),
            })
            _save_pending(pending)
            logger.info(f"Lore absorbed from {path.name} ({len(text)} chars)")
        except Exception as e:
            logger.error(f"Failed to absorb lore from {path}: {e}")


def _load_pending() -> list:
    if PENDING_LORE_FILE.exists():
        with open(PENDING_LORE_FILE) as f:
            return json.load(f)
    return []


def _save_pending(items: list):
    with open(PENDING_LORE_FILE, "w") as f:
        json.dump(items, f, indent=2)


def start_watcher():
    global _observer
    LORE_DIR.mkdir(exist_ok=True)
    _observer = Observer()
    _observer.schedule(LoreHandler(), str(LORE_DIR), recursive=False)
    _observer.start()
    logger.info(f"Lore watcher started on {LORE_DIR}")


def stop_watcher():
    global _observer
    if _observer and _observer.is_alive():
        _observer.stop()
        _observer.join()
        logger.info("Lore watcher stopped.")
