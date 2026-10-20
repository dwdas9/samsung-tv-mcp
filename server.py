#!/usr/bin/env python3
"""samsung-tv-mcp: an MCP server that lets Claude control a Samsung Tizen TV.

Control goes over the TV's local WebSocket API (port 8002, token auth).
Status comes from its REST API (port 8001). YouTube playback uses DIAL
(port 8080), the same path the YouTube phone app uses to cast.
Power-on uses Wake-on-LAN.

Run pair.py once before using this server.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "tv_config.json"
if not CONFIG_FILE.exists():
    sys.exit("tv_config.json not found. Run: python pair.py")

CFG = json.loads(CONFIG_FILE.read_text())
HOST = CFG["host"]
MAC = CFG.get("mac")
BROADCAST = CFG.get("broadcast", "255.255.255.255")
CLIENT_NAME = CFG.get("client_name", "ClaudeMCP")
TOKEN_FILE = str(HERE / "tv-token.txt")
APPS = CFG["apps"]
EXPECTED_BG = {a.lower() for a in CFG.get("expected_background_apps", [])}
YOUTUBE_ID = APPS.get("YouTube", "111299001912")

# Claude Desktop can start MCP servers with proxy env vars set. A proxy can't
# reach your home network, so every call to the TV must skip it.
for _k in ("NO_PROXY", "no_proxy"):
    _extra = [HOST, "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
    os.environ[_k] = ",".join(x for x in [os.environ.get(_k, "")] + _extra if x)
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LAST_ERROR = {"error": None}

mcp = FastMCP("samsung-tv")


# ---------- helpers ----------

def _rest(path: str = "", method: str = "GET", timeout: float = 4):
    req = urllib.request.Request(f"http://{HOST}:8001/api/v2/{path}", method=method)
    with _OPENER.open(req, timeout=timeout) as r:
        body = r.read().decode()
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return {"raw": body}


def _device():
    try:
        return _rest("")["device"]
    except Exception as e:
        LAST_ERROR["error"] = f"{type(e).__name__}: {e}"
        return None


def _power_state() -> str:
    dev = _device()
    return dev.get("PowerState", "unknown") if dev else "unreachable"


def _tv() -> SamsungTVWS:
    return SamsungTVWS(host=HOST, port=8002, token_file=TOKEN_FILE,
                       name=CLIENT_NAME, timeout=8)


def _resolve(app: str) -> str:
    a = app.strip()
    if a.isdigit() or a.startswith("org."):
        return a
    for name, app_id in APPS.items():
        if name.lower() == a.lower():
            return app_id
    for name, app_id in APPS.items():
        if a.lower() in name.lower():
            return app_id
    raise ValueError(f"Unknown app '{app}'. Known apps: {', '.join(APPS)}")


def _app_status(app_id: str):
    try:
        s = _rest(f"applications/{app_id}")
    except Exception:
        return None
    if not isinstance(s, dict) or s.get("code") == 404 or "running" not in s:
        return None
    return s


def _scan_apps():
    out = []
    for name, app_id in APPS.items():
        s = _app_status(app_id)
        if s is not None:
            out.append({"name": s.get("name", name), "id": app_id,
                        "running": bool(s.get("running")),
                        "foreground": bool(s.get("visible")),
                        "version": s.get("version")})
    return out


def _wake(wait_s: int = 25) -> bool:
    if not MAC:
        return False
    for _ in range(3):
        for ip in (BROADCAST, HOST):
            try:
                send_magic_packet(MAC, ip_address=ip)
            except Exception:
                pass
        time.sleep(0.5)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _power_state() == "on":
            return True
        time.sleep(1.5)
    return False


def _ensure_on():
    if _power_state() == "on":
        return None
    if _wake():
        time.sleep(3)  # let Smart Hub settle before launching apps
        return None
    return ("TV didn't wake. Check it's plugged in, on the same network, and that "
            "'Power On with Mobile' is enabled. Wake over Wi-Fi isn't reliable on every model.")


# ---------- tools ----------

@mcp.tool()
def tv_status() -> dict:
    """Get the TV's power state, foreground app, and which known apps are running."""
    dev = _device()
    if not dev:
        return {"power": "unreachable", "error": LAST_ERROR["error"],
                "note": "TV is off (deep standby), unplugged, or not on the network."}
    apps = _scan_apps() if dev.get("PowerState") == "on" else []
    return {
        "power": dev.get("PowerState"),
        "name": dev.get("name"),
        "model": dev.get("modelName"),
        "network": dev.get("networkType"),
        "foreground_app": next((a["name"] for a in apps if a["foreground"]), None),
        "running_apps": [a["name"] for a in apps if a["running"]],
    }


@mcp.tool()
def tv_health_check() -> dict:
    """Check the TV is healthy: reachable, responsive, remote control authorized,
    and no unwanted apps running in the background. Use when asked whether the TV
    is running properly or what is running on it."""
    report = {"issues": []}
    t0 = time.time()
    dev = _device()
    report["api_latency_ms"] = round((time.time() - t0) * 1000)
    if not dev:
        report["power"] = "unreachable"
        report["issues"].append("TV not reachable on the network.")
        report["error"] = LAST_ERROR["error"]
        report["proxy_env"] = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
        return report
    report["power"] = dev.get("PowerState")
    report["network"] = dev.get("networkType")
    if report["api_latency_ms"] > 1500:
        report["issues"].append(f"Slow response ({report['api_latency_ms']} ms). Wi-Fi signal may be weak.")
    if report["power"] != "on":
        report["issues"].append("TV is in standby. App checks skipped.")
        return report

    try:
        tv = _tv()
        tv.open()
        tv.close()
        report["remote_control"] = "authorized"
    except Exception as e:
        report["remote_control"] = f"failed: {e}"
        report["issues"].append("Remote control connection failed. Run pair.py again.")

    apps = _scan_apps()
    report["installed_known_apps"] = [a["name"] for a in apps]
    report["foreground_app"] = next((a["name"] for a in apps if a["foreground"]), None)
    bg = [a["name"] for a in apps
          if a["running"] and not a["foreground"] and a["name"].lower() not in EXPECTED_BG]
    report["background_apps"] = bg
    if bg:
        report["issues"].append(
            f"Running in background: {', '.join(bg)}. Close with tv_close_background_apps.")
    report["healthy"] = not report["issues"]
    report["limits"] = ("Only apps in tv_config.json are checked. The TV API doesn't "
                        "expose CPU, memory, or a full process list.")
    return report


@mcp.tool()
def tv_power(state: str) -> str:
    """Turn the TV 'on' or 'off'."""
    state = state.lower().strip()
    current = _power_state()
    if state == "on":
        if current == "on":
            return "TV is already on."
        return "TV is on." if _wake() else "Sent wake signal, but the TV didn't respond within 25s."
    if state == "off":
        if current != "on":
            return f"TV is already off ({current})."
        _tv().send_key("KEY_POWER")
        return "TV turned off."
    return "state must be 'on' or 'off'."


@mcp.tool()
def tv_launch_app(app: str) -> str:
    """Open an app by name (e.g. 'YouTube', 'Netflix', 'Prime Video') or Tizen app ID.
    Turns the TV on first if needed."""
    err = _ensure_on()
    if err:
        return err
    app_id = _resolve(app)
    _tv().run_app(app_id)
    return f"Launched {app} ({app_id})."


@mcp.tool()
def tv_play_youtube(video: str) -> str:
    """Play a YouTube video or live stream on the TV. Pass a video ID or any YouTube URL.
    To play a song, show, channel, or topic by name, first find a matching YouTube
    video with web search, then pass its URL here. For a channel's live stream, use
    the video URL from https://www.youtube.com/channel/<CHANNEL_ID>/live.
    Turns the TV on first if needed."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", video)
    vid = m.group(1) if m else video.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        return f"Couldn't find a YouTube video ID in '{video}'."
    err = _ensure_on()
    if err:
        return err
    # DIAL launch. Works even when YouTube is already open. The TV returns 403
    # unless the request carries an Origin header.
    req = urllib.request.Request(
        f"http://{HOST}:8080/ws/apps/YouTube", data=f"v={vid}".encode(), method="POST",
        headers={"Origin": "https://www.youtube.com",
                 "Content-Type": "text/plain; charset=utf-8"})
    try:
        with _OPENER.open(req, timeout=10) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        code = f"error {e}"
    if code in (200, 201):
        return f"Playing https://youtu.be/{vid} on the TV."
    # Fallback: Tizen deep link. YouTube ignores this if it's already open.
    _tv().run_app(YOUTUBE_ID, app_type="DEEP_LINK", meta_tag=f"v={vid}")
    return f"DIAL returned {code}. Tried deep link fallback for https://youtu.be/{vid}."


@mcp.tool()
def tv_close_app(app: str) -> str:
    """Close a running app by name or app ID."""
    app_id = _resolve(app)
    s = _app_status(app_id)
    if not s or not s.get("running"):
        return f"{app} isn't running."
    try:
        _rest(f"applications/{app_id}", method="DELETE")
    except Exception as e:
        return f"Close failed for {app}: {e}"
    time.sleep(1)
    s = _app_status(app_id)
    return f"Closed {app}." if not (s and s.get("running")) else f"{app} still reports running."


@mcp.tool()
def tv_close_background_apps() -> dict:
    """Close every known app running in the background. Leaves the foreground app open."""
    closed, failed = [], []
    for a in _scan_apps():
        if a["running"] and not a["foreground"] and a["name"].lower() not in EXPECTED_BG:
            try:
                _rest(f"applications/{a['id']}", method="DELETE")
                closed.append(a["name"])
            except Exception as e:
                failed.append(f"{a['name']}: {e}")
    return {"closed": closed, "failed": failed}


@mcp.tool()
def tv_key(key: str, times: int = 1) -> str:
    """Send a remote-control key. Examples: KEY_HOME, KEY_RETURN, KEY_ENTER, KEY_UP,
    KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_PLAY, KEY_PAUSE, KEY_STOP, KEY_FF, KEY_REWIND,
    KEY_SOURCE, KEY_HDMI1, KEY_HDMI2, KEY_MENU, KEY_CHUP, KEY_CHDOWN."""
    key = key.upper().strip()
    if not key.startswith("KEY_"):
        key = "KEY_" + key
    if _power_state() != "on":
        return "TV is off. Use tv_power('on') first."
    n = max(1, min(times, 30))
    _tv().send_key(key, times=n)
    return f"Sent {key} x{n}."


@mcp.tool()
def tv_volume(action: str, steps: int = 1) -> str:
    """Change volume: action is 'up', 'down', or 'mute' (toggles mute)."""
    keys = {"up": "KEY_VOLUP", "down": "KEY_VOLDOWN", "mute": "KEY_MUTE"}
    k = keys.get(action.lower().strip())
    if not k:
        return "action must be 'up', 'down', or 'mute'."
    if _power_state() != "on":
        return "TV is off."
    n = 1 if k == "KEY_MUTE" else max(1, min(steps, 30))
    _tv().send_key(k, times=n)
    return f"Volume {action} x{n}."


@mcp.tool()
def tv_open_url(url: str) -> str:
    """Open a web page in the TV's browser."""
    err = _ensure_on()
    if err:
        return err
    _tv().open_browser(url)
    return f"Opened {url}."


@mcp.tool()
def tv_list_apps() -> list:
    """List the known apps installed on the TV, with running state."""
    if _power_state() != "on":
        return [{"note": "TV must be on to check apps."}]
    return _scan_apps()


if __name__ == "__main__":
    mcp.run()
