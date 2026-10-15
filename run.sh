#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
.venv/bin/python manage.py run_import_worker &
worker_pid=$!
trap 'kill "$worker_pid" 2>/dev/null || true' EXIT
.venv/bin/python manage.py runserver 127.0.0.1:8000
