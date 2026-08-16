# ─────────────────────────────────────────────────────────────────────────────
#  tunnel.py  —  CRYPTO scanner
#
#  Optional ngrok tunnel so the dashboard is reachable from a device on a
#  DIFFERENT network (LAN binding via config.WEB_HOST only covers same-WiFi).
#
#  Spawns the ngrok agent as a child process and reads the assigned public URL
#  from ngrok's own local API (127.0.0.1:4040) — no pip package needed.
#
#  ⚠  The URL is PUBLIC: anyone holding it can view the dashboard (signals are
#     read-only; no keys or order placement are exposed).  Free-tier URLs are
#     random and change on every restart.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request

import config

_API = "http://127.0.0.1:4040/api/tunnels"
_proc: subprocess.Popen | None = None


def _resolve_binary() -> str | None:
    """config.NGROK_PATH if set, else whatever is on PATH."""
    p = getattr(config, "NGROK_PATH", "") or ""
    if p:
        return p if shutil.which(p) or _exists(p) else None
    return shutil.which("ngrok")


def _exists(p: str) -> bool:
    import os
    return os.path.isfile(p)


def _read_tunnels() -> list[dict] | None:
    """Current tunnels from the local agent API, or None if no agent answers."""
    try:
        with urllib.request.urlopen(_API, timeout=3) as r:
            return json.load(r).get("tunnels", [])
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _serves_port(tunnel: dict, port: int) -> bool:
    """True if this tunnel forwards to OUR local port.

    Critical: one agent can host several endpoints (see ngrok.yml).  Matching on
    'a tunnel exists' would hand back another project's dashboard URL.
    """
    addr = str(tunnel.get("config", {}).get("addr", ""))
    return addr.endswith(f":{port}") or addr == str(port)


def _public_url(port: int, timeout: float = 20.0) -> str | None:
    """Poll the agent API until an https tunnel for `port` shows up."""
    deadline = time.time() + timeout
    while True:
        tunnels = _read_tunnels() or []
        mine = [t for t in tunnels if _serves_port(t, port)]
        for t in mine:                                   # prefer https
            if t.get("proto") == "https" and t.get("public_url"):
                return t["public_url"]
        for t in mine:                                   # http-only fallback
            if t.get("public_url"):
                return t["public_url"]
        if time.time() >= deadline:
            return None
        time.sleep(0.5)


def start(port: int) -> str | None:
    """Launch ngrok for `port`. Returns the public URL, or None on failure.

    The free tier allows only ONE concurrent agent, so we never spawn a second.
    If an agent is already up we use its endpoint for `port` — and if it has no
    endpoint for `port`, we say so instead of returning someone else's URL.
    """
    global _proc

    tunnels = _read_tunnels()
    if tunnels is not None:                              # an agent is already up
        url = _public_url(port, timeout=1.5)
        if url:
            return url
        others = ", ".join(
            str(t.get("config", {}).get("addr", "?")) for t in tunnels
        ) or "none"
        print(f"        ngrok already running, but no endpoint for port {port} "
              f"(it serves: {others}).")
        print("        Free plan = 1 agent AND 1 domain, so only one dashboard")
        print("        can be public at a time.  To hand it to this one:")
        print("            taskkill /IM ngrok.exe /F  &&  ngrok start crypto")
        return None

    exe = _resolve_binary()
    if not exe:
        print("        ngrok not found — set NGROK_PATH in config.py")
        return None

    # Single tunnel only.  `ngrok start --all` looks tempting (ngrok.yml defines
    # a 'crypto' and a 'heatmap' endpoint) but the free plan hands out exactly
    # ONE domain — every endpoint gets that same hostname and they fight over
    # it, leaving whichever loses as a 502.  One port per agent, deliberately.
    try:
        _proc = subprocess.Popen(
            [exe, "http", str(port), "--log=stdout"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"        ngrok failed to start: {e}")
        return None

    atexit.register(stop)

    url = _public_url(port)
    if not url:
        print("        ngrok started but no URL for this port — check  ngrok config check")
    return url


def stop():
    global _proc
    if _proc and _proc.poll() is None:
        try:
            _proc.terminate()
            _proc.wait(timeout=5)
        except Exception:
            try:
                _proc.kill()
            except Exception:
                pass
    _proc = None
