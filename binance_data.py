# ─────────────────────────────────────────────────────────────────────────────
#  binance_data.py  —  CRYPTO scanner data layer
#
#  Responsibilities:
#     • Fetch 1H OHLCV klines from Binance REST (public, no key).
#     • Persist them to a local SQLite  candles.db  (one table per symbol,
#       candles_1h_<SYMBOL>), UPSERTed by bar open_time so re-seeding is idempotent.
#     • Read them back oldest->newest as a DataFrame for the strategy modules.
#     • UTC hourly bar-boundary helpers (crypto trades 24/7 — no session hours).
#
#  Kline row shape from Binance:
#     [ openTime, open, high, low, close, volume, closeTime, ... ]  (12 fields)
#  We key candles by openTime (ms).  A 1H bar that opened at HH:00:00 UTC is
#  "complete" once wall-clock passes HH:59:59.999 (i.e. the next hour has started).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

import config

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 crypto-scanner"})


# ── table naming ─────────────────────────────────────────────────────────────
def _table(symbol: str) -> str:
    return f"candles_1h_{symbol.upper()}"


def _connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{config.CANDLES_DB}?mode=ro", uri=True, timeout=30)
    else:
        con = sqlite3.connect(config.CANDLES_DB, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
    return con


def _ensure_table(con: sqlite3.Connection, symbol: str) -> None:
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {_table(symbol)} ("
        "  open_time INTEGER PRIMARY KEY,"       # ms since epoch (bar start, UTC)
        "  date      TEXT,"                      # ISO 'YYYY-MM-DD HH:MM:SS' UTC
        "  open      REAL, high REAL, low REAL, close REAL, volume REAL"
        ")"
    )


# ── REST fetch ───────────────────────────────────────────────────────────────
def fetch_klines(symbol: str, interval: str = "1h", limit: int = 1000,
                 end_time: int | None = None, retries: int = 3) -> list[list]:
    """
    Return raw Binance klines (list of lists), oldest->newest.
    `end_time` (ms) fetches bars ending at/before that time (for paging back).
    """
    url = f"{config.REST_BASE}/api/v3/klines"
    params = {"symbol": symbol.upper(), "interval": interval,
              "limit": min(int(limit), 1000)}
    if end_time is not None:
        params["endTime"] = int(end_time)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, params=params, timeout=20)
            if r.status_code == 429 or r.status_code == 418:
                # rate-limited / banned — back off
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:            # noqa: BLE001
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"fetch_klines({symbol}) failed: {last_err}")


def _rows_from_klines(klines: list[list]) -> list[tuple]:
    rows = []
    for k in klines:
        ot = int(k[0])
        dt = datetime.fromtimestamp(ot / 1000, tz=timezone.utc)
        rows.append((
            ot,
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]),
        ))
    return rows


# ── seed / update ────────────────────────────────────────────────────────────
def seed_symbol(symbol: str, bars: int = 1000) -> int:
    """
    Fetch the most recent `bars` completed 1H candles for `symbol` and UPSERT
    into candles.db.  Returns number of rows written.  Idempotent.
    Excludes the still-forming current bar (last kline whose bar hasn't closed).
    """
    klines = fetch_klines(symbol, config.INTERVAL, limit=bars)
    if not klines:
        return 0
    # Drop the final kline if it is the currently-forming (not yet closed) bar.
    now_ms = int(time.time() * 1000)
    if klines and int(klines[-1][6]) > now_ms:      # closeTime in the future
        klines = klines[:-1]
    rows = _rows_from_klines(klines)
    if not rows:
        return 0
    con = _connect()
    try:
        _ensure_table(con, symbol)
        con.executemany(
            f"INSERT INTO {_table(symbol)} "
            "(open_time,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(open_time) DO UPDATE SET "
            "date=excluded.date, open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, volume=excluded.volume",
            rows,
        )
        con.commit()
    finally:
        con.close()
    return len(rows)


def append_completed_bar(symbol: str, open_time_ms: int, o: float, h: float,
                         l: float, c: float, v: float = 0.0) -> None:
    """Persist a single freshly-completed 1H bar (called by the live scanner)."""
    dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
    con = _connect()
    try:
        _ensure_table(con, symbol)
        con.execute(
            f"INSERT INTO {_table(symbol)} "
            "(open_time,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(open_time) DO UPDATE SET "
            "date=excluded.date, open=excluded.open, high=excluded.high, "
            "low=excluded.low, close=excluded.close, volume=excluded.volume",
            (open_time_ms, dt.strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, v),
        )
        con.commit()
    finally:
        con.close()


# ── read back ────────────────────────────────────────────────────────────────
def has_symbol(symbol: str) -> bool:
    con = _connect(readonly=True)
    try:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (_table(symbol),),
        ).fetchone() is not None
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def load_1h(symbol: str, limit: int | None = None) -> pd.DataFrame | None:
    """
    Load 1H candles for `symbol` oldest->newest as a DataFrame indexed by UTC
    datetime with open/high/low/close/volume.  None if missing/empty.
    """
    tbl = _table(symbol)
    con = _connect(readonly=True)
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (tbl,),
        ).fetchone() is None:
            return None
        if limit:
            q = (f"SELECT date,open,high,low,close,volume FROM {tbl} "
                 f"ORDER BY open_time DESC LIMIT {int(limit)}")
            df = pd.read_sql(q, con, parse_dates=["date"])
            df = df.iloc[::-1].reset_index(drop=True)
        else:
            q = f"SELECT date,open,high,low,close,volume FROM {tbl} ORDER BY open_time"
            df = pd.read_sql(q, con, parse_dates=["date"])
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if df is None or df.empty:
        return None
    return df.set_index("date")


def last_open_time(symbol: str) -> int | None:
    """Most recent stored bar open_time (ms), or None."""
    tbl = _table(symbol)
    con = _connect(readonly=True)
    try:
        row = con.execute(f"SELECT MAX(open_time) FROM {tbl}").fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


# ── UTC 1H bar-boundary helpers (24/7) ───────────────────────────────────────
def current_1h_bar_start(dt: datetime | None = None) -> datetime:
    """Start (HH:00:00 UTC) of the 1H bar that `dt` (default now) falls into."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def next_1h_bar_start(bar_start: datetime) -> datetime:
    return bar_start + timedelta(hours=1)


def bar_start_ms(dt: datetime) -> int:
    return int(current_1h_bar_start(dt).timestamp() * 1000)
