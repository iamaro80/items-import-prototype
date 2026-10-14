#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "This deletes ALL prototype import jobs, their uploaded files, Service Items, and demo references."
echo "The original supplied CSV and synthetic demo CSV are preserved."
read -r -p "Type RESET DEMO to continue: " confirmation
if [[ "$confirmation" != "RESET DEMO" ]]; then
  echo "Reset cancelled."
  exit 1
fi
.venv/bin/python manage.py reset_demo --yes
