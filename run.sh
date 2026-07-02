#!/usr/bin/env bash
# Cron entrypoint: run all prompts x engines, then regenerate the dashboard.
# Example weekly cron (Monday 6am):
#   0 6 * * 1 /path/to/una-citation-tracker/run.sh >> /path/to/una-citation-tracker/run.log 2>&1
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

python3 src/runner.py
python3 src/dashboard.py
