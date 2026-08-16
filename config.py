# ─────────────────────────────────────────────────────────────────────────────
#  config.py  —  Crypto 1H Scanner (Binance spot)
#
#  Central settings for the whole pipeline.  No exchange API keys needed —
#  Binance public market data (REST klines + WebSocket streams) is open.
#
#  Secrets (Telegram bot token / chat id) are read from ENVIRONMENT VARIABLES,
#  never hard-coded — see .env.example.  Nothing in this file is a secret, so
#  it is safe to commit.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Load a local .env if python-dotenv is installed (optional convenience).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
except ImportError:
    pass


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


# ── Market / data ────────────────────────────────────────────────────────────
INTERVAL      = "1h"                 # Binance kline interval (your strategy's TF)
HISTORY_BARS  = 1000                 # bars fetched per symbol on seed (~42 days @1h)
SEED_LIMIT    = 800                  # bars loaded from DB for indicator warm-up

WATCHLIST_FILE = os.path.join(HERE, "symbols.txt")
CANDLES_DB     = os.path.join(HERE, "candles.db")     # SQLite (per-symbol tables)

REST_BASE  = "https://api.binance.com"
WS_BASE    = "wss://stream.binance.com:9443"

# ── Signal timing ────────────────────────────────────────────────────────────
#  False -> emit intra-bar the moment your strategy's condition first holds
#           (live; each signal deduped once per bar, but CAN repaint).
#  True  -> only emit when the bar CLOSES (fewer, confirmed, no repaint).
EMIT_ON_CLOSE_ONLY = _env_bool("EMIT_ON_CLOSE_ONLY", False)

# ── Display timezone ─────────────────────────────────────────────────────────
#  ALL internal logic, bar boundaries, DB and dedup stay in UTC (Binance candles
#  are UTC-aligned — never change that).  These only affect how times are SHOWN
#  on the dashboard and in Telegram.  Examples: IST = 330, CET = 60, EST = -300.
DISPLAY_TZ_LABEL   = os.getenv("DISPLAY_TZ_LABEL", "UTC")
DISPLAY_OFFSET_MIN = int(os.getenv("DISPLAY_OFFSET_MIN", "0"))

# ── Web dashboard ────────────────────────────────────────────────────────────
WEB_PORT = int(os.getenv("WEB_PORT", "5010"))
#  "0.0.0.0"   -> reachable from other devices on the same LAN
#  "127.0.0.1" -> this machine only
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")

# ── Remote access (different network) — optional ─────────────────────────────
#  WEB_HOST only covers the same WiFi.  Set NGROK_ENABLED=true to also open an
#  ngrok tunnel so the dashboard is reachable from anywhere.
#  ⚠  That URL is PUBLIC — anyone with the link can view the dashboard.
#  Leave NGROK_PATH empty to use whatever `ngrok` is on PATH.
NGROK_ENABLED = _env_bool("NGROK_ENABLED", False)
NGROK_PATH    = os.getenv("NGROK_PATH", "")

# ── Telegram (optional) ──────────────────────────────────────────────────────
#  Create a bot with @BotFather, then export:
#     TELEGRAM_BOT_TOKEN=123456:ABC...
#     TELEGRAM_CHAT_ID=-1001234567890
#  Alerts are skipped silently if these are unset.
TELEGRAM_ENABLED = _env_bool("TELEGRAM_ENABLED", True)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


# ── Watchlist loader ─────────────────────────────────────────────────────────
def load_symbols() -> list[str]:
    """Read symbols.txt -> list of UPPERCASE Binance symbols (comments skipped)."""
    out: list[str] = []
    seen = set()
    with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip().upper()
            if not s or s.startswith("#"):
                continue
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
