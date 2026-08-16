# ─────────────────────────────────────────────────────────────────────────────
#  strategy_state.py  —  LIVE strategy engine   ***  ADD YOUR OWN  ***
#
#  ┌───────────────────────────────────────────────────────────────────────┐
#  │  THIS FILE IS AN EMPTY TEMPLATE ON PURPOSE.                           │
#  │  Add whatever indicators and strategy YOU want.  Nothing about the    │
#  │  author's own logic ships in this repository.                         │
#  └───────────────────────────────────────────────────────────────────────┘
#
#  This is the FAST/LIVE path.  The scanner receives a WebSocket update several
#  times per second per symbol; recomputing a 800-bar DataFrame every time would
#  not keep up.  So instead we keep a small `state` dict per symbol holding just
#  the running values your indicators need, and advance it one candle at a time.
#
#  Batch (`indicators.py`) and incremental (this file) must produce the SAME
#  signals — the incremental one is simply the O(1) version.  Verify that: run
#  `compute_all()` over history, seed a state from the same history, and check
#  the last bar matches. A drift here means live alerts that a chart won't show.
#
#  ── THE CONTRACT ────────────────────────────────────────────────────────────
#  scanner.py uses exactly three functions:
#
#     extract_state(df)             -> dict        seed from history
#     increment_state(state, row)   -> dict        advance by one candle (pure)
#     check_signal_on_tick(state, ohlc) -> list[str]   test the forming candle
#
#  Signal names returned must be the ones in indicators.SIGNAL_COLS, and must
#  start with "BUY" or "SELL" (scanner.py reads direction from that prefix).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations


# ── 1. Seed the state from history ───────────────────────────────────────────
def extract_state(df) -> dict:
    """
    Build the live state from a DataFrame of completed candles
    (columns open/high/low/close/volume, OLDEST -> NEWEST).

    Called once per symbol at startup.  Return a dict holding everything
    `increment_state()` needs to carry forward — running averages, previous
    indicator values, recursive buffers, bar counts, whatever your strategy
    uses.  The scanner treats it as an opaque blob.

    ---------------------------------------------------------------------
    ADD YOUR OWN INDICATORS AND STRATEGY.

        closes = df["close"].to_numpy(float)
        return {
            "close":     closes[-1],
            "prev_fast": ...,      # your indicator values on the last bar
            "prev_slow": ...,
            "window":    closes[-50:].tolist(),   # whatever you must remember
        }
    ---------------------------------------------------------------------
    """
    return {}


# ── 2. Advance the state by exactly one candle ───────────────────────────────
def increment_state(state: dict, row: dict) -> dict:
    """
    Apply one OHLC candle and return a **NEW** state dict.

    `row` = {"open": float, "high": float, "low": float, "close": float}

    MUST be pure — do not mutate `state`.  The scanner relies on that: it calls
    this with the *forming* candle to preview signals (result discarded), and
    again with the *closed* candle to commit (result kept).  Mutating the input
    would corrupt every later bar.

    ---------------------------------------------------------------------
    ADD YOUR OWN INDICATORS AND STRATEGY.

        new = dict(state)                      # copy first — never mutate
        new["prev_fast"] = state.get("fast")   # remember the old values
        new["prev_slow"] = state.get("slow")
        new["fast"] = ...                      # roll your indicators forward
        new["slow"] = ...
        new["close"] = row["close"]
        return new
    ---------------------------------------------------------------------
    """
    return dict(state)


# ── 3. Decide whether anything fires on the forming candle ───────────────────
def check_signal_on_tick(state: dict, ohlc: dict) -> list[str]:
    """
    O(1) signal check for the still-forming candle.  Does NOT mutate `state`.

    `ohlc` = {"open","high","low","close"} of the current forming candle.
    Return a list of signal names that fire right now (empty list = nothing).

    The scanner de-dupes per (symbol, bar, signal name), so returning the same
    name repeatedly while a candle is open only ever alerts once.

    ---------------------------------------------------------------------
    ADD YOUR OWN INDICATORS AND STRATEGY.

        cur  = increment_state(state, ohlc)     # what the bar looks like now
        out  = []
        crossed_up = (state.get("fast", 0) <= state.get("slow", 0)
                      and cur["fast"] > cur["slow"])
        if crossed_up:
            out.append("BUY")
        return out
    ---------------------------------------------------------------------
    """
    return []
