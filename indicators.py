# ─────────────────────────────────────────────────────────────────────────────
#  indicators.py  —  BATCH strategy engine   ***  ADD YOUR OWN  ***
#
#  ┌───────────────────────────────────────────────────────────────────────┐
#  │  THIS FILE IS AN EMPTY TEMPLATE ON PURPOSE.                           │
#  │  Plug in whatever indicators and entry/exit rules YOU want — moving   │
#  │  averages, RSI, MACD, supertrend, breakouts, order blocks, an ML      │
#  │  model, anything.  The rest of the project (data layer, WebSocket,    │
#  │  dashboard, Telegram, storage) is complete and does not care what     │
#  │  your logic is — it only needs the contract below to be honoured.     │
#  └───────────────────────────────────────────────────────────────────────┘
#
#  This module is the SLOW/BATCH path: it recomputes everything over a whole
#  DataFrame of candles.  It is used for history and for the "replay today"
#  step at startup.  The live path is `strategy_state.py` (O(1) per tick) —
#  implement both, and keep them agreeing with each other.
#
#  ── THE CONTRACT ────────────────────────────────────────────────────────────
#  Anything importing this module uses exactly three names:
#
#     SIGNAL_COLS            list[str]  — the signal names you emit
#     compute_all(df)        DataFrame  — df + one bool column per signal name
#     latest_signals(df)     list[str]  — names True on the newest bar
#
#  Signal names MUST start with "BUY" or "SELL" — the scanner derives the
#  direction from that prefix (see `_direction()` in scanner.py).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import pandas as pd

# ── 1. Name your signals ─────────────────────────────────────────────────────
#  Add as many as you like.  Two is just an example.
#  e.g. ["BUY_BREAKOUT", "SELL_BREAKDOWN", "BUY_PULLBACK", ...]
SIGNAL_COLS: list[str] = ["BUY", "SELL"]


# ── 2. Put your indicators + rules here ──────────────────────────────────────
def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute indicators and signals over a full candle history.

    Parameters
    ----------
    df : DataFrame with columns  open, high, low, close, volume
         indexed by UTC datetime, ordered OLDEST -> NEWEST.

    Returns
    -------
    The same DataFrame with one **boolean column per name in SIGNAL_COLS**
    appended.  A True at row i means "this signal fires on that candle".

    ---------------------------------------------------------------------
    ADD YOUR OWN INDICATORS AND STRATEGY BELOW.

    Sketch of what an implementation looks like:

        c = df["close"]

        fast = c.rolling(20).mean()          # <- your indicators
        slow = c.rolling(50).mean()

        df["BUY"]  = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        df["SELL"] = (fast < slow) & (fast.shift(1) >= slow.shift(1))

        return df

    Rules to respect:
      • No look-ahead: row i may only use data from rows <= i.
      • Every name in SIGNAL_COLS must end up as a column, or the replay
        step silently finds nothing.
      • Return the DataFrame — don't mutate in place and return None.
    ---------------------------------------------------------------------
    """
    df = df.copy()

    # Placeholder so a fresh clone runs end-to-end (and fires nothing).
    # Delete these two lines once you write your own logic.
    for name in SIGNAL_COLS:
        df[name] = False

    return df


# ── 3. Convenience reader (usually no need to change this) ───────────────────
def latest_signals(df: pd.DataFrame) -> list[str]:
    """Return the signal names that are True on the last (newest) bar."""
    if len(df) == 0:
        return []
    last = df.iloc[-1]
    return [s for s in SIGNAL_COLS if bool(last.get(s, False))]
