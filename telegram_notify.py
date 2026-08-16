# ─────────────────────────────────────────────────────────────────────────────
#  telegram_notify.py  —  CRYPTO scanner Telegram alerts
#
#  Credentials come from the environment via config.py (TELEGRAM_BOT_TOKEN /
#  TELEGRAM_CHAT_ID).  Never raises — a telegram hiccup must never crash the
#  scanner, and an unconfigured bot is a silent no-op.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import requests

import config
import tzfmt

def _emoji(signal_name: str) -> str:
    """Green for anything BUY*, red for anything SELL* — works with whatever
    names your strategy defines in indicators.SIGNAL_COLS."""
    if signal_name.upper().startswith("BUY"):
        return "🟢"
    if signal_name.upper().startswith("SELL"):
        return "🔴"
    return "⚪"


def send(message: str) -> None:
    """Send a raw HTML message.  Silent no-op if disabled/unconfigured/offline."""
    if not getattr(config, "TELEGRAM_ENABLED", False):
        return
    token = config.BOT_TOKEN
    chat = config.CHAT_ID
    if not token or not chat:          # not configured — stay quiet
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": message, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=5,
        )
    except Exception:
        pass


def notify_startup(n_symbols: int, mode: str = "live") -> None:
    """Ping the channel the moment the scanner boots up."""
    send(
        f"🚀 <b>CRYPTO Scanner STARTED</b>\n"
        f"Mode    : {mode}\n"
        f"Symbols : <b>{n_symbols}</b>  ·  TF {config.INTERVAL.upper()}\n"
        f"Time    : {tzfmt.now_stamp()} {tzfmt.LABEL}"
    )


def notify_shutdown(reason: str = "manual stop") -> None:
    """Ping the channel when the scanner goes down."""
    send(
        f"🛑 <b>CRYPTO Scanner STOPPED</b>\n"
        f"Reason  : {reason}\n"
        f"Time    : {tzfmt.now_stamp()} {tzfmt.LABEL}"
    )


def notify_signal(sig: dict) -> None:
    """
    Push one scanner signal.  `sig` keys: symbol, signal, direction, ltp,
    time (HH:MM:SS UTC), bar_start.
    """
    name = sig.get("signal", "")
    emoji = _emoji(name)
    direction = sig.get("direction", "")
    sym = sig.get("symbol", "")
    tz = sig.get("tz", "IST")
    bar = sig.get("bar_disp") or str(sig.get("bar_start", ""))[:16]
    tv = f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}&interval=60"
    send(
        f"{emoji} <b>{name}</b> · {direction}\n"
        f"Symbol : <b>{sym}</b>\n"
        f"Price  : {sig.get('ltp')}\n"
        f"Time   : {bar} {tz}\n"
        f"<a href=\"{tv}\">📈 Chart</a>"
    )
