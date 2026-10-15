#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "This restores the prototype to its first-run state and deletes all jobs, items, uploaded files, saved mappings, and custom facilities or references."
echo "The two starter facilities and reference fixtures are restored. The original and synthetic sample CSV files are preserved."
read -r -p "Type RESET DEMO to continue: " confirmation
if [[ "$confirmation" != "RESET DEMO" ]]; then
  echo "Reset cancelled."
  exit 1
fi
.venv/bin/python manage.py reset_demo --yes
