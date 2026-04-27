#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python manage.py migrate --noinput
python manage.py qcluster &
QCLUSTER_PID=$!
trap "kill $QCLUSTER_PID 2>/dev/null || true" EXIT
exec python manage.py runserver 0.0.0.0:5000 --noreload
