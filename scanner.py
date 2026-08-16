# ─────────────────────────────────────────────────────────────────────────────
#  scanner.py  —  CRYPTO 1H Signal Scanner  (Binance kline_1h WebSocket)
#
#  Signals come from YOUR strategy — see indicators.py / strategy_state.py.
#  Whatever names those emit (each must start with BUY or SELL) flow through
#  here untouched; this file knows nothing about the logic behind them.
#
#  Architecture (O(1) per update — uses the incremental strategy engine):
#     • seed_history()  loads each symbol's committed indicator state from
#       candles.db (through the last completed bar), catching up over REST if the
#       DB is stale.
#     • A combined Binance WS delivers  <symbol>@kline_1h  updates.  Each update
#       carries the FORMING bar OHLC and a "closed" flag  (k.x)  — no tick→candle
#       building needed, Binance builds the candle for us.
#     • On every update:  check_signal_on_tick(state, forming)  — O(1), no
#       recompute — emits any NEW signal (deduped per (symbol, bar, name)).
#     • When a bar CLOSES (k.x == True):  state is advanced (increment_state) and
#       the completed bar is persisted to candles.db.
#     • Every emitted signal -> signal_store + Telegram + dashboard callback.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import websocket        # websocket-client

import config
import binance_data as bd
import indicators
import strategy_state as ps
import signal_store
import telegram_notify
import tzfmt

SEED_LIMIT      = config.SEED_LIMIT
CHUNK_SIZE      = 100          # symbols per SUBSCRIBE message
RECONNECT_DELAY = 3
DEBUG_INTERVAL  = 30
CATCHUP_BARS    = 200          # REST bars pulled at startup to close any DB gap

# Milliseconds per bar for the configured interval — used to detect a missed
# bar-close (WS gap / reconnect) so state never silently drifts.
_INTERVAL_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
                "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000,
                "4h": 14_400_000, "6h": 21_600_000, "12h": 43_200_000,
                "1d": 86_400_000}
INTERVAL_MS = _INTERVAL_MS.get(config.INTERVAL, 3_600_000)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _direction(name: str) -> str:
    return "BUY" if name.startswith("BUY") else "SELL"


class Scanner:
    def __init__(self, symbols: list[str], on_signal=None):
        self.symbols     = [s.upper() for s in symbols]
        self._on_signal  = on_signal

        self._state:   dict[str, dict] = {}     # committed state @ last closed bar
        self._committed_ot: dict[str, int] = {} # open_time (ms) of that last closed bar
        self._emitted: set[tuple] = set()       # (symbol, bar_iso, name)

        self._lock       = threading.Lock()
        self._stop_event = threading.Event()
        self._ws         = None
        self._ws_done    = threading.Event()
        self._msg_count  = 0
        self._seen       = set()
        self._last_dbg   = time.time()
        self._emit_on_close = getattr(config, "EMIT_ON_CLOSE_ONLY", False)

    # ── Phase 1: seed committed state from DB (+ REST catch-up) ───────────────
    def seed_history(self) -> int:
        print(f"\n  Seeding 1H state for {len(self.symbols)} symbols "
              f"(DB: {os.path.basename(config.CANDLES_DB)}) ...")
        t0 = time.time()
        ready = skip = 0
        for i, sym in enumerate(self.symbols, 1):
            st = self._load_and_catchup(sym)
            if st is None:
                skip += 1
            else:
                self._state[sym] = st["state"]
                self._committed_ot[sym] = st["last_ot"]
                ready += 1
            if i % 25 == 0 or i == len(self.symbols):
                print(f"  [{round(time.time()-t0,1)}s] {i}/{len(self.symbols)}  "
                      f"ready:{ready}  skip:{skip}")
        print(f"  State ready in {round(time.time()-t0,1)}s "
              f"({ready} ready, {skip} without data — run seed_db.py)\n")
        return ready

    def _load_and_catchup(self, sym: str) -> dict | None:
        df = bd.load_1h(sym, limit=SEED_LIMIT)
        if df is None or len(df) < 90:
            return None
        try:
            state = ps.extract_state(df)
        except Exception:
            return None
        last_ot = bd.last_open_time(sym)
        if last_ot is None:
            return None

        # Catch up over REST: advance state through any completed bars newer than
        # the DB's last bar (handles a scanner started long after seed_db).
        try:
            kl = bd.fetch_klines(sym, config.INTERVAL, limit=CATCHUP_BARS)
            now_ms = int(time.time() * 1000)
            for k in kl:
                ot = int(k[0])
                if ot <= last_ot or int(k[6]) > now_ms:   # old, or still forming
                    continue
                o, h, l, c, v = (float(k[1]), float(k[2]), float(k[3]),
                                 float(k[4]), float(k[5]))
                state = ps.increment_state(state, {"open": o, "high": h,
                                                   "low": l, "close": c})
                bd.append_completed_bar(sym, ot, o, h, l, c, v)
                last_ot = ot
        except Exception as e:                       # noqa: BLE001
            print(f"  WARN catch-up {sym}: {str(e)[:60]}")
        return {"state": state, "last_ot": last_ot}

    # ── Phase 2: live scan ────────────────────────────────────────────────────
    def scan(self):
        mode = "close-confirmed" if self._emit_on_close else "intra-bar (live)"
        print("=" * 64)
        print(f"  CRYPTO 1H SCANNING  {len(self._state)} symbols  [{_now_utc()} UTC]")
        print(f"  Signals: {'  '.join(indicators.SIGNAL_COLS)}  |  emit mode: {mode}")
        print("=" * 64 + "\n")

        while not self._stop_event.is_set():
            self._ws_done.clear()
            self._connect()
            while not self._ws_done.is_set() and not self._stop_event.is_set():
                time.sleep(0.5)
            if self._stop_event.is_set():
                break
            print(f"  [{_now_utc()}] WS dropped — reconnecting in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)

    def stop(self):
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # ── Signal emit ───────────────────────────────────────────────────────────
    def _emit(self, sym: str, name: str, ltp: float, bar_iso: str):
        key = (sym, bar_iso, name)
        if key in self._emitted:
            return
        self._emitted.add(key)
        sig = {
            "symbol": sym, "signal": name, "direction": _direction(name),
            "ltp": ltp,
            "time": tzfmt.now_hms(),                 # display TZ (IST) HH:MM:SS
            "bar_start": bar_iso,                    # UTC — dedup key + internal
            "bar_disp": tzfmt.utc_iso_to_bar(bar_iso),  # display TZ (IST) bar label
            "tz": tzfmt.LABEL,
        }
        newly = signal_store.add(sig)
        print(f"  >>> [{sig['time']} {tzfmt.LABEL}] {name:<6} {sym:<12} "
              f"@ {ltp}  (bar {sig['bar_disp']})")
        if newly:
            telegram_notify.notify_signal(sig)
            if self._on_signal:
                try:
                    self._on_signal(sig)
                except Exception as e:
                    print(f"  WARN on_signal: {e}")

    # ── WS internals ──────────────────────────────────────────────────────────
    def _stream_url(self) -> str:
        # Combined-stream base; we SUBSCRIBE by message after connect so the URL
        # stays short regardless of watchlist size.
        return f"{config.WS_BASE}/stream"

    def _connect(self):
        ws = websocket.WebSocketApp(
            self._stream_url(),
            on_open=self._on_open, on_message=self._on_message,
            on_error=self._on_error, on_close=self._on_close)
        self._ws = ws
        threading.Thread(
            target=ws.run_forever,
            kwargs={"ping_interval": 180, "ping_timeout": 10},
            daemon=True,
        ).start()

    def _on_open(self, ws):
        syms = list(self._state.keys())
        print(f"  [{_now_utc()}] WS connected — subscribing {len(syms)} kline_1h streams...")
        req_id = 1
        for i in range(0, len(syms), CHUNK_SIZE):
            chunk = syms[i:i + CHUNK_SIZE]
            params = [f"{s.lower()}@kline_{config.INTERVAL}" for s in chunk]
            ws.send(json.dumps({"method": "SUBSCRIBE", "params": params, "id": req_id}))
            req_id += 1
        print(f"  [{_now_utc()}] Subscribed — watching...\n")

    def _on_message(self, ws, message):
        now = time.time()
        if now - self._last_dbg >= DEBUG_INTERVAL:
            self._last_dbg = now
            print(f"  [{_now_utc()}] ALIVE — {self._msg_count} msgs | "
                  f"{len(self._seen)}/{len(self._state)} symbols | "
                  f"emitted:{len(self._emitted)}")
            self._msg_count = 0
        try:
            payload = json.loads(message)
        except Exception:
            return
        data = payload.get("data")
        if not data or data.get("e") != "kline":
            return          # subscription ack / non-kline
        self._msg_count += 1
        self._on_kline(data.get("s", "").upper(), data["k"])

    def _on_error(self, ws, error):
        print(f"  [{_now_utc()}] WS error: {error}")

    def _on_close(self, ws, code, msg):
        print(f"  [{_now_utc()}] WS closed (code={code})")
        self._ws_done.set()

    # ── Gap fill (missed bar-close across a WS drop) ──────────────────────────
    def _fill_gap(self, sym: str, upto_ot: int):
        """
        We received a forming bar whose open_time is >1 interval ahead of the
        last committed bar — i.e. one or more bar-CLOSE events were missed while
        the socket was down.  Fetch those completed bars over REST and commit
        them (increment_state + persist) so the incremental state never drifts.
        """
        committed = self._committed_ot.get(sym)
        if committed is None:
            return
        try:
            kl = bd.fetch_klines(sym, config.INTERVAL, limit=CATCHUP_BARS)
        except Exception as e:                       # noqa: BLE001
            print(f"  WARN gap-fill {sym}: {str(e)[:60]}")
            return
        now_ms = int(time.time() * 1000)
        filled = 0
        for kk in kl:
            o_t = int(kk[0])
            if o_t <= committed or o_t >= upto_ot:   # already have it, or it's the forming bar
                continue
            if int(kk[6]) > now_ms:                  # not yet closed
                continue
            o, h, l, c, v = (float(kk[1]), float(kk[2]), float(kk[3]),
                             float(kk[4]), float(kk[5]))
            with self._lock:
                self._state[sym] = ps.increment_state(
                    self._state[sym], {"open": o, "high": h, "low": l, "close": c})
                self._committed_ot[sym] = o_t
            bd.append_completed_bar(sym, o_t, o, h, l, c, v)
            committed = o_t
            filled += 1
        if filled:
            print(f"  [{_now_utc()}] gap-fill {sym}: committed {filled} missed bar(s)")

    # ── Kline handler ─────────────────────────────────────────────────────────
    def _on_kline(self, sym: str, k: dict):
        if self._stop_event.is_set() or sym not in self._state:
            return
        self._seen.add(sym)
        ot = int(k["t"])
        committed_ot = self._committed_ot.get(sym)
        if committed_ot is not None and ot <= committed_ot:
            return          # this bar already committed — ignore late updates
        # Missed one or more bar-closes (WS reconnect / gap) — backfill via REST
        # before evaluating, so indicators stay exact.
        if committed_ot is not None and ot - committed_ot > INTERVAL_MS:
            self._fill_gap(sym, ot)
            committed_ot = self._committed_ot.get(sym)

        o = float(k["o"]); h = float(k["h"]); l = float(k["l"])
        c = float(k["c"]); v = float(k["v"])
        closed = bool(k["x"])
        bar_iso = _iso(ot)
        forming = {"open": o, "high": h, "low": l, "close": c}

        with self._lock:
            state = self._state[sym]

        # ── evaluate your strategy on the forming bar (O(1), no mutation) ─────
        if not self._emit_on_close or closed:
            try:
                sigs = ps.check_signal_on_tick(state, forming)
            except Exception as e:
                print(f"  WARN check {sym}: {str(e)[:60]}")
                sigs = []
            for name in sigs:
                self._emit(sym, name, c, bar_iso)

        # ── commit on close: advance state + persist the completed bar ────────
        if closed:
            with self._lock:
                self._state[sym] = ps.increment_state(self._state[sym], forming)
                self._committed_ot[sym] = ot
            bd.append_completed_bar(sym, ot, o, h, l, c, v)


# ── standalone entry (scan only; no dashboard) ───────────────────────────────
if __name__ == "__main__":
    syms = config.load_symbols()
    sc = Scanner(syms)
    if sc.seed_history() == 0:
        print("No symbols had data — run  python seed_db.py  first.")
        sys.exit(1)
    try:
        sc.scan()
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sc.stop()
