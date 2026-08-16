# Crypto Signal Scanner — Binance Spot

A complete, production-shaped **live scanner skeleton** for Binance USDT spot
pairs. Everything around a trading strategy is already built and battle-tested —
data feed, candle storage, WebSocket engine, de-duplication, a live web
dashboard, and Telegram alerts.

**The strategy itself is intentionally left empty. You add your own.**

> Bring any logic you like — moving averages, RSI, MACD, supertrend, breakouts,
> order blocks, an ML model. Fill in two files and the whole pipeline runs it
> live, 24/7.

---

## What you get for free

| | |
|---|---|
| **Data** | Binance public REST klines + combined WebSocket. No API key, no account. |
| **Storage** | SQLite (`candles.db`), one table per symbol, idempotent re-seeding. |
| **Live engine** | O(1) per update — no re-computing history on every tick. |
| **Gap healing** | WebSocket drops across a candle close are backfilled over REST, so indicator state never silently drifts. Safe to run for weeks on a VPS. |
| **De-dup** | Each `(symbol, candle, signal)` alerts exactly once, persisted per UTC day. |
| **Dashboard** | Flask + Server-Sent Events, live updating, LAN- or internet-reachable. |
| **Telegram** | Start / stop / signal alerts with a chart link. |
| **Timezone** | Internals stay UTC; display converts to whatever you configure. |

## What you must write

Exactly two files, both shipped as commented templates:

| File | Role |
|---|---|
| [`indicators.py`](indicators.py) | **Batch** path — compute signals over a full history DataFrame. Used for backfill and the "replay today" step. |
| [`strategy_state.py`](strategy_state.py) | **Live** path — the same logic as an O(1) incremental state machine, advanced one candle at a time. |

Both files spell out their contract in detail, with a worked sketch. Clone and
run it before writing anything: the placeholders fire no signals, so you get a
working dashboard and a live feed immediately, then fill in the logic.

### Why two files?

The scanner receives WebSocket updates several times per second per symbol.
Recomputing an 800-row DataFrame each time would never keep up, so the live path
keeps a small rolling `state` dict per symbol instead. The batch path exists for
history and as the reference you validate the incremental one against.

**They must agree.** Seed a state from history, run `compute_all()` over the same
history, and check the last candle matches. A drift there means live alerts your
chart won't confirm.

---

## Quick start

```bash
git clone <your-fork-url>
cd crypto-signal-scanner

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env        # then edit .env (all of it is optional)

python seed_db.py           # fetch history for everything in symbols.txt
python main.py              # dashboard on http://127.0.0.1:5010/
```

Now open [`indicators.py`](indicators.py) and [`strategy_state.py`](strategy_state.py)
and add your own indicators and strategy.

### Command reference

```bash
python seed_db.py                  # all watchlist symbols
python seed_db.py BTCUSDT ETHUSDT  # only these

python main.py                     # refresh DB -> dashboard -> replay -> live
python main.py --no-seed           # skip the DB refresh
python main.py --replay-only       # today's signals only, no live WebSocket

python scanner.py                  # scanner alone, no dashboard
```

---

## How it fits together

```
symbols.txt ─► seed_db.py ─► candles.db (SQLite, OHLCV per symbol)
                                  │
                                  ▼
                      indicators.py      (batch  — history / replay)   ← YOU
                      strategy_state.py  (live   — O(1) per update)    ← YOU
                                  │
Binance kline WebSocket ──►   scanner.py  ──► signal_store (JSON, per UTC day)
                                  │                ├─► telegram_notify
                                  │                └─► frontend.py  (SSE dashboard)
                                  ▼
                              main.py  (orchestration)
```

Binance's `@kline_<interval>` stream delivers the forming candle **with a
`closed` flag**, so there is no tick→candle building to get wrong — the exchange
builds the candle. When a candle closes, the incremental state advances by one
step and the completed candle is written to `candles.db`.

## Configuration

Everything lives in [`config.py`](config.py), with secrets read from the
environment (see [`.env.example`](.env.example)).

| Setting | Meaning |
|---|---|
| `INTERVAL` | Kline timeframe (`1h` default — any Binance interval works). |
| `HISTORY_BARS` | Candles fetched per symbol on seed (1000 ≈ 42 days at 1h). |
| `SEED_LIMIT` | Candles loaded from the DB to warm up your indicators. |
| `EMIT_ON_CLOSE_ONLY` | `false` = alert intra-candle (live, can repaint). `true` = alert only on close. |
| `WEB_PORT` / `WEB_HOST` | Dashboard. `0.0.0.0` exposes it to your LAN. |
| `DISPLAY_TZ_LABEL` / `DISPLAY_OFFSET_MIN` | Display timezone (minutes from UTC). Display only. |
| `TELEGRAM_*` | Bot token and chat/channel id. Unset = alerts silently skipped. |
| `NGROK_*` | Optional public tunnel for the dashboard. |

**Watchlist** — [`symbols.txt`](symbols.txt), one Binance USDT spot symbol per
line (uppercase, `#` for comments). Add symbols, re-run `seed_db.py`.

### Viewing from your phone (same WiFi)

Set `WEB_HOST=0.0.0.0`; `main.py` prints the LAN URL on startup. On Windows you
may need a one-time firewall rule (elevated PowerShell):

```powershell
New-NetFirewallRule -DisplayName "Crypto Scanner Dashboard" `
  -Direction Inbound -Protocol TCP -LocalPort 5010 -Action Allow -Profile Private
```

Run the scanner on **one** machine only — other devices just open the URL. A
browser connecting late still receives the whole day, because the SSE stream
replays everything accumulated since startup.

### Viewing from anywhere — ngrok

Set `NGROK_ENABLED=true` and `main.py` opens the tunnel itself, printing the
public URL. The tunnel is matched to *this* dashboard's port — if an ngrok agent
is already running for something else, you get a clear warning rather than
somebody else's URL.

> ⚠️ That URL is **public**. Anyone with the link sees your dashboard. Only
> read-only signals are exposed — no keys, no order placement — but treat the
> link as a secret.

---

## Notes and gotchas

- **Intra-candle signals repaint.** With `EMIT_ON_CLOSE_ONLY=false` a condition
  can hold mid-candle, alert, then reverse before the close. That's inherent to
  any live scanner, not a bug. The closed candle is authoritative. Set it to
  `true` for confirmed-only alerts.
- **Everything internal is UTC.** Candle boundaries, the database, and de-dup
  keys are all UTC-aligned, matching Binance. Only what you *see* is converted.
  Don't change that — it's the thing that keeps restarts idempotent.
- **Restarts are self-healing.** Every start re-seeds from continuous history
  and replays the current UTC day, so a crash or reboot loses nothing.
- **Replayed signals don't re-alert on Telegram.** On restart, signals that
  already fired earlier today appear on the dashboard but are not re-sent, so a
  restart loop can't spam your phone.
- **No API keys anywhere.** This reads public market data and never places an
  order. There is no trading, no key handling, and no custody of funds.

## Protecting your own strategy

If you fork this and add real logic, the [`.gitignore`](.gitignore) already
blocks the usual leaks — `.env`, `candles.db`, and `__pycache__` (a committed
`.pyc` is decompilable and would hand over your logic). To keep your filled-in
strategy files out of git while still tracking upstream:

```bash
git update-index --skip-worktree indicators.py strategy_state.py
```

## Disclaimer

For research and education. This produces **signals, not trades, and not
financial advice**. Markets carry real risk of loss — validate any strategy
yourself before risking money.

## License

MIT — see [LICENSE](LICENSE).
