#!/bin/sh
set -e

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# If a command is passed (e.g., celery worker/beat), execute it
# Otherwise, default to starting Gunicorn
if [ $# -gt 0 ]; then
    echo "Executing command: $@"
    exec "$@"
else
    echo "Starting Gunicorn..."
    # --timeout 120: RAG pipeline (embedding + search + LLM call) can exceed
    #   the default 30s timeout, especially for large Persian legal documents.
    # --max-requests 1000 / --max-requests-jitter 100: Periodically recycle
    #   workers to prevent memory leaks from accumulating.
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120 \
        --max-requests 1000 \
        --max-requests-jitter 100
fi
