#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Este instalador es para macOS. Consulta README.md para Linux."
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Necesitas Python 3.10 o superior"'
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  .venv/bin/python scripts/configure.py
fi
mkdir -p logs data
chmod 700 data
chmod 600 .env
.venv/bin/python scripts/launch_agent.py install
echo "Servicio instalado. En Telegram: /ps5 y /estado."
echo "Logs: $project_dir/logs/bot.log"
