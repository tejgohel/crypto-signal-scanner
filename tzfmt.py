# ─────────────────────────────────────────────────────────────────────────────
#  tzfmt.py  —  display-only timezone formatting
#
#  The scanner works entirely in UTC (bar boundaries, DB, dedup keys).  These
#  helpers convert UTC instants to the configured DISPLAY timezone (default IST)
#  purely for what the user SEES on the dashboard / Telegram.  Nothing here feeds
#  back into indicator logic.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config

_OFFSET = timedelta(minutes=getattr(config, "DISPLAY_OFFSET_MIN", 330))
LABEL   = getattr(config, "DISPLAY_TZ_LABEL", "IST")


def now_hms() -> str:
    """Current wall-clock in the display TZ as HH:MM:SS."""
    return (datetime.now(timezone.utc) + _OFFSET).strftime("%H:%M:%S")


def now_stamp() -> str:
    """Current wall-clock in the display TZ as 'YYYY-MM-DD HH:MM:SS'."""
    return (datetime.now(timezone.utc) + _OFFSET).strftime("%Y-%m-%d %H:%M:%S")


def _parse_utc(iso_utc: str) -> datetime:
    return datetime.strptime(iso_utc[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def utc_iso_to_hms(iso_utc: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> 'HH:MM:SS' in the display TZ."""
    return (_parse_utc(iso_utc) + _OFFSET).strftime("%H:%M:%S")


def utc_iso_to_bar(iso_utc: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> 'MM-DD HH:MM' in the display TZ (bar label)."""
    return (_parse_utc(iso_utc) + _OFFSET).strftime("%m-%d %H:%M")
