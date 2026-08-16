# ─────────────────────────────────────────────────────────────────────────────
#  frontend.py  —  CRYPTO 1H Dashboard  (Flask + Server-Sent Events)
#
#  • Light theme.  Signals grouped into per-set cards (2 / 3 / 4), each holding
#    that set's BUY and SELL signals.
#  • Live signals pushed via SSE (no refresh).
#  • On startup loads TODAY's (UTC) persisted signals so they survive restarts.
#  • Single time column, shown in the display TZ (IST).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import queue
import socket
import threading
import time
import webbrowser
from datetime import datetime, timezone

from flask import Flask, Response, jsonify

import config
import signal_store
import tzfmt

_signals: list[dict] = []
_subscribers: list[queue.Queue] = []
_status = {"text": "Starting...", "scanning": False}
_lock = threading.Lock()

app = Flask(__name__)
app.config["ENV"] = "production"


def load_persisted(day: str | None = None):
    day = day or datetime.now(timezone.utc).date().isoformat()
    with _lock:
        _signals.clear()
        _signals.extend(signal_store.load_day(day))


@app.route("/")
def index():
    return _HTML.replace("__TZLABEL__", tzfmt.LABEL)


@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify(_status)


@app.route("/api/stream")
def api_stream():
    def generate():
        q = queue.Queue()
        with _lock:
            _subscribers.append(q)
            existing = list(_signals)
            cur_status = dict(_status)
        try:
            yield f"data: {json.dumps({'type': 'status', **cur_status})}\n\n"
            for sig in existing:
                payload = dict(sig)
                payload["type"] = "signal"
                yield f"data: {json.dumps(payload)}\n\n"
            while True:
                try:
                    item = q.get(timeout=25)
                    yield f"data: {json.dumps(item)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            with _lock:
                try:
                    _subscribers.remove(q)
                except ValueError:
                    pass
    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def add_signal(signal: dict):
    with _lock:
        _signals.append(signal)
        payload = dict(signal)
        payload["type"] = "signal"
        for q in list(_subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass


def set_status(text: str, scanning: bool = False):
    with _lock:
        _status["text"] = text
        _status["scanning"] = scanning
        payload = {"type": "status", "text": text, "scanning": scanning}
        for q in list(_subscribers):
            try:
                q.put_nowait(payload)
            except Exception:
                pass


def lan_ip() -> str | None:
    """This machine's LAN IP (the one other devices on the network can reach).

    Uses a UDP socket to a public address — no packet is actually sent, it just
    makes the OS pick the outbound interface, which is the one the router NATs.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def start_server(port: int = 5010, host: str | None = None):
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    host = host or getattr(config, "WEB_HOST", "127.0.0.1")

    def _run():
        app.run(host=host, port=port, debug=False, use_reloader=False,
                threaded=True)
    threading.Thread(target=_run, daemon=True).start()
    time.sleep(1.0)


def open_browser(port: int = 5010):
    try:
        webbrowser.open(f"http://127.0.0.1:{port}/")
    except Exception:
        pass


_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>CRYPTO — 1H Signals</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 *{box-sizing:border-box;margin:0;padding:0}
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f1f5f9;color:#0f172a;padding:20px;line-height:1.4}
 h1{font-size:1.2rem;font-weight:700;margin-bottom:2px}
 .sub{color:#64748b;font-size:.8rem;margin-bottom:16px}
 .bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:18px}
 .pill{padding:6px 12px;border-radius:20px;font-size:.8rem;font-weight:600;background:#fff;border:1px solid #e2e8f0;color:#334155}
 .dot{width:9px;height:9px;border-radius:50%;background:#94a3b8;display:inline-block;margin-right:6px}
 .dot.live{background:#22c55e;box-shadow:0 0 8px #22c55e}
 .cnt-buy{color:#16a34a}.cnt-sell{color:#dc2626}
 input{background:#fff;border:1px solid #cbd5e1;color:#0f172a;padding:7px 11px;border-radius:8px;font-size:.85rem;min-width:180px}
 input:focus{outline:none;border-color:#3b82f6}
 .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px;align-items:start}
 .card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(15,23,42,.06)}
 .card-head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #eef2f7;font-weight:700;font-size:.95rem}
 .card-head .tag{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:6px}
 .tag.buy{background:#dcfce7;color:#15803d}.tag.sell{background:#fee2e2;color:#b91c1c}
 .card-head .n{margin-left:auto;font-size:.78rem;font-weight:600;color:#64748b;background:#f1f5f9;padding:3px 10px;border-radius:20px}
 table{width:100%;border-collapse:collapse}
 th{background:#f8fafc;text-align:left;padding:9px 13px;font-size:.68rem;text-transform:uppercase;color:#64748b;letter-spacing:.04em;font-weight:600;white-space:nowrap}
 td{padding:9px 13px;border-top:1px solid #f1f5f9;font-size:.85rem;white-space:nowrap}
 tr:hover td{background:#f8fafc}
 .badge{padding:3px 9px;border-radius:6px;font-size:.72rem;font-weight:700;letter-spacing:.02em}
 .badge.buy{background:#dcfce7;color:#15803d;border:1px solid #bbf7d0}
 .badge.sell{background:#fee2e2;color:#b91c1c;border:1px solid #fecaca}
 .sym{font-weight:600}
 .num{color:#475569;font-variant-numeric:tabular-nums;font-size:.82rem}
 a.chart{padding:3px 10px;border-radius:6px;background:#eff6ff;color:#2563eb;font-size:.75rem;font-weight:600;text-decoration:none;border:1px solid #dbeafe}
 a.chart:hover{background:#dbeafe}
 .empty td{color:#94a3b8;padding:16px;font-size:.83rem}
</style></head><body>
<h1>CRYPTO · 1-Hour Signals</h1>
<div class="sub">Binance spot · live via WebSocket · times in __TZLABEL__</div>
<div class="bar">
 <span class="pill"><span id="dot" class="dot"></span><span id="status">Starting...</span></span>
 <span class="pill">BUY <span id="cnt-buy" class="cnt-buy">0</span></span>
 <span class="pill">SELL <span id="cnt-sell" class="cnt-sell">0</span></span>
 <span class="pill">Total <span id="cnt-all">0</span></span>
 <input id="filter" placeholder="filter symbol...">
</div>
<div class="cards" id="cards"></div>
<script>
const SETS=['2','3','4'];
const cardsEl=document.getElementById('cards');
// Build the three cards
SETS.forEach(function(s){
 const card=document.createElement('div'); card.className='card';
 card.innerHTML=`<div class="card-head">Set ${s}
   <span class="tag buy">BUY${s}</span><span class="tag sell">SELL${s}</span>
   <span class="n" id="n-${s}">0</span></div>
  <table><thead><tr><th>Signal</th><th>Symbol</th><th>Price</th><th>Time (__TZLABEL__)</th><th>Chart</th></tr></thead>
  <tbody id="body-${s}"><tr class="empty"><td colspan="5">No signals yet…</td></tr></tbody></table>`;
 cardsEl.appendChild(card);
});
let buy=0,sell=0,all=0;
function setOf(sig){ const n=(sig.signal||'').replace(/[^0-9]/g,''); return SETS.includes(n)?n:'2'; }
function addRow(sig){
 const set=setOf(sig);
 const body=document.getElementById('body-'+set);
 const e=body.querySelector('.empty'); if(e)e.remove();
 all++; if(sig.direction==='BUY')buy++; if(sig.direction==='SELL')sell++;
 document.getElementById('cnt-buy').textContent=buy;
 document.getElementById('cnt-sell').textContent=sell;
 document.getElementById('cnt-all').textContent=all;
 const d=(sig.direction||'').toLowerCase();
 const t=sig.bar_disp||(sig.bar_start||'').slice(5,16)||(sig.time||'');
 const tv='https://www.tradingview.com/chart/?symbol=BINANCE%3A'+encodeURIComponent(sig.symbol||'')+'&interval=60';
 const tr=document.createElement('tr'); tr.dataset.symbol=(sig.symbol||'').toLowerCase();
 tr.innerHTML=`<td><span class="badge ${d}">${sig.signal||sig.direction}</span></td>
  <td class="sym">${sig.symbol}</td>
  <td class="num">${sig.ltp!=null?sig.ltp:''}</td>
  <td class="num">${t}</td>
  <td><a class="chart" href="${tv}" target="_blank" rel="noopener">Chart</a></td>`;
 body.insertBefore(tr,body.firstChild);
 document.getElementById('n-'+set).textContent=body.querySelectorAll('tr').length;
}
document.getElementById('filter').addEventListener('input',function(){
 const q=this.value.toLowerCase();
 document.querySelectorAll('tbody tr').forEach(function(tr){
  if(tr.classList.contains('empty'))return;
  tr.style.display=(!q||(tr.dataset.symbol||'').includes(q))?'':'none';
 });
});
function setStatus(t,scan){ document.getElementById('status').textContent=t;
 document.getElementById('dot').className='dot'+(scan?' live':''); }
const es=new EventSource('/api/stream');
es.onmessage=function(ev){ const d=JSON.parse(ev.data);
 if(d.type==='status'){ setStatus(d.text,d.scanning); return; }
 if(d.type==='signal'||d.direction){ addRow(d); } };
</script></body></html>"""
