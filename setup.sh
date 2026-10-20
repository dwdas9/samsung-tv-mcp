#!/bin/bash
# One-time install. Run: bash setup.sh [TV_IP]
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
PY="$(command -v python3)"
"$PY" -c 'import sys; assert sys.version_info >= (3,10), "Need Python 3.10+, found " + sys.version'
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f tv_config.json ] || [ ! -f tv-token.txt ]; then
  .venv/bin/python pair.py "$@"
fi
.venv/bin/python -c "import server; print('TV status:', server.tv_status())"

cat <<MSG

Done. Add this inside "mcpServers" in Claude Desktop's config
(Settings > Developer > Edit Config), then quit and reopen Claude Desktop:

    "samsung-tv": {
      "command": "$DIR/.venv/bin/python",
      "args": ["$DIR/server.py"]
    }

For Claude Code:

    claude mcp add --scope user samsung-tv -- "$DIR/.venv/bin/python" "$DIR/server.py"
MSG
