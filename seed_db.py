# ─────────────────────────────────────────────────────────────────────────────
#  seed_db.py  —  CRYPTO scanner
#
#  Fetch the most recent  config.HISTORY_BARS  1H candles for every symbol in
#  symbols.txt and store them in candles.db.  Idempotent — safe to re-run any
#  time (UPSERT by bar open_time).  Run this once before the first scan, and
#  again whenever you add symbols to the watchlist.
#
#  Usage:
#     python seed_db.py                 # all watchlist symbols
#     python seed_db.py BTCUSDT ETHUSDT # only these
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import sys
import time

import config
import binance_data as bd


def run(symbols: list[str] | None = None, bars: int | None = None) -> dict:
    symbols = symbols or config.load_symbols()
    bars = bars or config.HISTORY_BARS
    n = len(symbols)
    print(f"Seeding {n} symbols × {bars} bars ({config.INTERVAL}) -> {config.CANDLES_DB}\n")

    ok = fail = 0
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            wrote = bd.seed_symbol(sym, bars=bars)
            ok += 1
            tag = f"{wrote} bars"
        except Exception as e:                       # noqa: BLE001
            fail += 1
            tag = f"FAIL {type(e).__name__}: {str(e)[:60]}"
        print(f"  [{i:>3}/{n}] {sym:<12} {tag}")
        time.sleep(0.15)                             # gentle on Binance weight limits

    dt = round(time.time() - t0, 1)
    print(f"\nDone in {dt}s — {ok} ok, {fail} failed.")
    return {"ok": ok, "fail": fail, "seconds": dt}


if __name__ == "__main__":
    args = [a.upper() for a in sys.argv[1:]]
    run(symbols=args or None)
