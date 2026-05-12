#!/bin/sh
set -e

echo "Running database migrations..."
# First attempt: normal migrate
if python manage.py migrate --noinput; then
    echo "Migrations applied successfully."
else
    echo "WARNING: Migration failed. Attempting to recover by faking remaining migrations..."
    echo "This can happen when the database schema was modified outside of Django migrations."
    python manage.py migrate --fake --noinput || {
        echo "ERROR: Could not recover migrations automatically."
        echo "Try: docker-compose exec backend python manage.py migrate --fake"
        exit 1
    }
    echo "Migrations recovered successfully (faked)."
fi

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
    # --worker-class gthread --threads 4: Use threaded workers so that
    #   StreamingHttpResponse (SSE) can stream tokens incrementally instead
    #   of buffering the entire response (sync workers buffer all output).
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:8000 \
        --worker-class gthread \
        --threads 4 \
        --workers 3 \
        --timeout 120 \
        --max-requests 1000 \
        --max-requests-jitter 100
fi
