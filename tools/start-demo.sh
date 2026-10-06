#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
if [ -f .venv-data/bin/python ]; then
  PYTHONPATH=src exec .venv-data/bin/python -m persona_lab serve --port 8787
fi
PYTHONPATH=src exec python3 -m persona_lab serve --port 8787
