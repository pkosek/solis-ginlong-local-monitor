#!/bin/sh
set -e

echo "=== Solar Monitor ==="
echo "Starting collector and dashboard..."

# Start the collector in the background
python collector.py &
COLLECTOR_PID=$!
echo "Collector started (PID $COLLECTOR_PID)"

# Start the dashboard (gunicorn) in the foreground
# WEB_HOST/WEB_PORT default to 0.0.0.0:5000 if not set (see config.py)
HOST=${WEB_HOST:-0.0.0.0}
PORT=${WEB_PORT:-5000}
exec gunicorn \
    --bind "${HOST}:${PORT}" \
    --workers 2 \
    --timeout 30 \
    --access-logfile - \
    --error-logfile - \
    dashboard:app
