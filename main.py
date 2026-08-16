# ─────────────────────────────────────────────────────────────────────────────
#  main.py  —  CRYPTO 1H Scanner  |  entrypoint
#
#  Flow:
#     1. Load watchlist (symbols.txt)
#     2. (default) Refresh candles.db for the watchlist   -> seed_db
#     3. Start web dashboard (port config.WEB_PORT) — loads today's UTC signals
#     4. Replay today's completed 1H bars so already-fired signals are visible
#     5. Seed incremental state and run the live Binance WS scan
#
#  Every signal (live or replayed) is persisted (signal_store), pushed to
#  Telegram, and streamed to the dashboard.  Crypto trades 24/7 — no session/
#  holiday logic; all timestamps are UTC.
#
#  Usage:
#     python main.py                # refresh DB, replay today, then live scan
#     python main.py --no-seed      # skip DB refresh (use existing candles.db)
#     python main.py --replay-only  # replay today's signals, no live WS
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
import binance_data as bd
import seed_db
import signal_store
import indicators as pi
import frontend as fe
import tzfmt
import telegram_notify as tg
from scanner import Scanner, _direction

WEB_PORT = config.WEB_PORT


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ── Replay today's completed 1H bars (surface signals already fired) ─────────
def replay_today(symbols: list[str]) -> int:
    day = _today_utc()
    print(f"\n  Replaying completed 1H bars for {day} (UTC) "
          f"({len(symbols)} symbols)...")
    fe.set_status(f"Replay {day}", scanning=True)
    total = 0
    for i, sym in enumerate(symbols, 1):
        df = bd.load_1h(sym, limit=config.SEED_LIMIT)
        if df is None or len(df) < 90:
            continue
        out = pi.compute_all(df)
        today_rows = out[out.index.date == datetime.now(timezone.utc).date()]
        for ts, row in today_rows.iterrows():
            for name in pi.SIGNAL_COLS:
                if not bool(row.get(name, False)):
                    continue
                bar_iso = str(ts)
                sig = {
                    "symbol": sym, "signal": name, "direction": _direction(name),
                    "ltp": round(float(row["close"]), 8),
                    "time": tzfmt.utc_iso_to_hms(bar_iso),
                    "bar_start": bar_iso,
                    "bar_disp": tzfmt.utc_iso_to_bar(bar_iso),
                    "tz": tzfmt.LABEL,
                }
                if signal_store.add(sig, day=day):
                    fe.add_signal(sig)
                    total += 1
    print(f"  Replay done — {total} signal(s) today.\n")
    return total


def main():
    argv = sys.argv[1:]
    no_seed     = "--no-seed" in argv
    replay_only = "--replay-only" in argv

    print("=" * 64)
    print("  CRYPTO — 1H Signal Scanner (Binance spot)")
    print("=" * 64 + "\n")

    print("  [1/5] Loading watchlist...")
    symbols = config.load_symbols()
    print(f"        {len(symbols)} symbols.\n")

    # Telegram "scanner started" ping — fires before the (slow) DB refresh so the
    # alert lands the moment the process boots.
    tg.notify_startup(len(symbols), mode="replay-only" if replay_only else "live")

    if not no_seed:
        print("  [2/5] Refreshing candles.db (Binance REST klines)...")
        seed_db.run(symbols=symbols)
        print()
    else:
        print("  [2/5] Skipping DB refresh (--no-seed).\n")

    print("  [3/5] Starting dashboard...")
    fe.load_persisted(_today_utc())
    fe.start_server(WEB_PORT)
    fe.open_browser(WEB_PORT)
    print(f"        local  : http://127.0.0.1:{WEB_PORT}/")
    if getattr(config, "WEB_HOST", "127.0.0.1") == "0.0.0.0":
        ip = fe.lan_ip()
        if ip:
            print(f"        network: http://{ip}:{WEB_PORT}/   "
                  f"(other PC / phone on the same WiFi)")
        else:
            print("        network: LAN IP not detected — run  ipconfig")
    if getattr(config, "NGROK_ENABLED", False):
        import tunnel
        url = tunnel.start(WEB_PORT)
        if url:
            print(f"        public : {url}   "
                  f"(any network — PUBLIC link, do not share)")
    print()

    print("  [4/5] Replaying today's signals...")
    replay_today(symbols)

    if replay_only:
        fe.set_status(f"Idle — {_today_utc()} signals loaded", scanning=False)
        print("  --replay-only : dashboard serving. Ctrl+C to exit.")
        _idle()
        return

    print("  [5/5] Seeding live state + starting WS scan...")
    sc = Scanner(symbols, on_signal=fe.add_signal)
    ready = sc.seed_history()
    if ready == 0:
        print("  No symbols had data — run  python seed_db.py  first. Exiting.")
        tg.notify_shutdown("no data — seed candles.db first")
        return

    fe.set_status("Live scanning (1H)", scanning=True)
    try:
        sc.scan()
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sc.stop()
        tg.notify_shutdown("manual stop (Ctrl+C)")
    except Exception as e:
        sc.stop()
        tg.notify_shutdown(f"crash: {type(e).__name__}: {e}")
        raise
    else:
        tg.notify_shutdown("scan loop ended")
    fe.set_status("Stopped — showing today's signals", scanning=False)
    _idle()


def _idle():
    print("\n  Dashboard still serving. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n  Bye.")


if __name__ == "__main__":
    main()
