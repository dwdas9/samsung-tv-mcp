# samsung-tv-mcp

Control a Samsung smart TV from Claude. Ask Claude on your phone to play BBC News, and it plays on your TV.

This is a small MCP server. It talks to the TV over your home network. No Samsung account, no SmartThings, no cloud.

## What Claude can do

| Tool | What it does |
|---|---|
| `tv_play_youtube` | Play any YouTube video or live stream. Claude finds the video, you get it on the TV. |
| `tv_power` | Turn the TV on (Wake-on-LAN) or off. |
| `tv_launch_app` | Open YouTube, Netflix, Prime Video, Disney+ and others. |
| `tv_health_check` | Check the TV is reachable, responsive and authorized, and flag apps running in the background. |
| `tv_close_background_apps` | Close apps running in the background. |
| `tv_close_app` | Close one app. |
| `tv_status` | Power state, foreground app, running apps. |
| `tv_key` | Send any remote key: Home, Back, arrows, Play, Pause, HDMI1. |
| `tv_volume` | Volume up, down, mute. |
| `tv_open_url` | Open a web page in the TV browser. |
| `tv_list_apps` | Installed apps the server knows about. |

## Requirements

- A Samsung Tizen TV, 2016 or newer. Tested on a 2020 UN50TU7000 (firmware T-KTSU2AKUC-2743.0).
- A Mac or Linux machine on the same network as the TV. Windows should work but isn't tested.
- Python 3.10 or newer.
- Claude Desktop or Claude Code.

## Prepare the TV

1. Enable **Settings > General > Network > Expert Settings > Power On with Mobile**. Claude needs this to turn the TV on.
2. Give the TV a fixed IP. A DHCP reservation on your router is best. If you set it by hand on the TV, use your router's IP for both Gateway and DNS, or the TV says the gateway is invalid.
3. Optional. Stop Samsung from opening apps at startup: **Settings > General > Smart Features**, then disable Autorun Samsung TV Plus, Autorun Smart Hub and Autorun Last App.

## Install

Keep the TV on and the remote in hand.

```bash
git clone https://github.com/dwdas9/samsung-tv-mcp.git
cd samsung-tv-mcp
bash setup.sh                 # finds the TV on your network
# or
bash setup.sh 192.168.1.50    # if you know its IP
```

The TV shows an **Allow** prompt. Accept it. The script saves an auth token in `tv-token.txt` and your TV details in `tv_config.json`. Both are git-ignored.

At the end, the script prints the config you need.

**Claude Desktop:** open Settings > Developer > Edit Config. Add the `samsung-tv` entry *inside* your existing `mcpServers` block. Quit and reopen Claude Desktop.

```json
{
  "mcpServers": {
    "samsung-tv": {
      "command": "/path/to/samsung-tv-mcp/.venv/bin/python",
      "args": ["/path/to/samsung-tv-mcp/server.py"]
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add --scope user samsung-tv -- /path/to/samsung-tv-mcp/.venv/bin/python /path/to/samsung-tv-mcp/server.py
```

## Use it from your phone

Claude on your phone reaches local MCP servers through your computer. So:

- Link the chat to your computer.
- Keep the computer awake with Claude Desktop open. On a Mac: System Settings > Battery > Options > Prevent automatic sleeping when the display is off.

Then ask things like:

- "Play BBC News live on my TV"
- "Is my TV running OK?"
- "Close background apps on the TV"
- "Turn off the TV"

## Gotchas I hit

These cost me the most time. None of them were in the docs I found.

**1. Claude Desktop's proxy breaks LAN calls.** Claude Desktop can start MCP servers with proxy environment variables. Python's `urllib` honours them and sends `http://192.168.x.x` to a proxy that can't reach your home network. The call fails in about 20 ms and looks like the TV is off. The server now bypasses proxies for all TV calls.

**2. macOS Local Network permission.** Since macOS Sequoia, every app needs permission to talk to devices on your LAN. Terminal had it. My browser didn't. If something can't reach the TV, check System Settings > Privacy & Security > Local Network.

**3. YouTube ignores deep links when it's already open.** The Tizen `run_app` deep link (`v=VIDEO_ID`) only works on a cold start. If YouTube is open, or sitting on the "Who's watching?" profile screen, the link is dropped. The fix is DIAL, the same path the YouTube phone app uses to cast: `POST http://TV:8080/ws/apps/YouTube` with body `v=VIDEO_ID`.

**4. DIAL returns 403 without an Origin header.** Add `Origin: https://www.youtube.com` and it returns 200.

**5. `mcp` 2.x renamed FastMCP.** `from mcp.server.fastmcp import FastMCP` fails on 2.x. This repo pins `mcp<2`.

**6. Nested `mcpServers`.** If Claude Desktop says *"entries ... are not valid MCP server configurations and were skipped: mcpServers"*, you pasted a whole `"mcpServers": {...}` block inside the existing one. Keep one level.

**7. The TV won't list installed apps.** The `ed.installedApp.get` WebSocket call hangs on my 2020 firmware. So the server checks apps by ID from `tv_config.json`. Add any app you care about there. A 404 means it isn't installed.

## Health check limits

The TV API reports power state and, per app, whether it's running and visible. It doesn't report CPU, memory or a full process list. `tv_health_check` only knows about apps listed in `tv_config.json`. Samsung's own built-ins are hard to cover because their IDs vary by model and region.

## Security

- `tv-token.txt` lets anything on your network control the TV. Keep it private.
- The TV's REST API on port 8001 has no auth. Anyone on your Wi-Fi can read its status. That's Samsung's design, not this server's.
- The server only talks to the TV's IP. It doesn't open any port.

## How it works

| Port | Used for |
|---|---|
| 8001 | REST. Device info, power state, app status, close app. No auth. |
| 8002 | Secure WebSocket. Remote keys, launch apps, open browser. Token auth. |
| 8080 | DIAL. Cast a video into YouTube. |
| UDP 9 | Wake-on-LAN magic packet. |

Built on [samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api) and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## License

MIT
