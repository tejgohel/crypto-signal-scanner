# ─────────────────────────────────────────────────────────────────────────────
#  signal_store.py  —  CRYPTO scanner
#
#  Durable, per-UTC-day store of every 1H signal that fired.  Written to disk as
#  it happens so signals stay visible across restarts / browser refreshes.
#
#  One JSON file per day:  signal_store/signals_YYYY-MM-DD.json  (UTC date).
#  De-dup key = (symbol, bar_start, signal_name).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.path.join(_HERE, "signal_store")
os.makedirs(STORE_DIR, exist_ok=True)

_lock = threading.Lock()


def _path(day: str) -> str:
    return os.path.join(STORE_DIR, f"signals_{day}.json")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_day(day: str | None = None) -> list[dict]:
    """Return all stored signals for `day` (default today UTC), oldest-first."""
    day = day or _today()
    p = _path(day)
    if not os.path.exists(p):
        return []
    with _lock:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []


def _dedup_key(sig: dict) -> tuple:
    return (str(sig.get("symbol")),
            str(sig.get("bar_start")),
            str(sig.get("signal")))


def add(sig: dict, day: str | None = None) -> bool:
    """Persist a signal. True if newly added, False if duplicate."""
    day = day or _today()
    p = _path(day)
    with _lock:
        existing = []
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
        keys = {_dedup_key(s) for s in existing}
        if _dedup_key(sig) in keys:
            return False
        existing.append(sig)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
