# ============================================================
# Stage 1: Builder — Install dependencies with build tools
# ============================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_NO_CACHE_DIR=1

# Build arguments for pip mirrors (overridable via --build-arg)
ARG PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple
ARG PIP_EXTRA_INDEX_URL=https://pypi.org/simple

# Install build tools needed for compiling Python C extensions
# (psycopg2-binary, PyMuPDF, etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        build-essential \
        libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Configure pip mirrors
RUN pip config set global.index-url ${PIP_INDEX_URL} && \
    pip config set global.extra-index-url ${PIP_EXTRA_INDEX_URL} && \
    pip config set global.trusted-host package-mirror.liara.ir && \
    pip config set global.trusted-host pypi.org && \
    pip config set global.trusted-host files.pythonhosted.org && \
    pip config set global.timeout 60 && \
    pip config set global.retries 5

# Copy and install production dependencies only
COPY src/backend/requirements.txt /tmp/requirements.txt
RUN pip install --user -r /tmp/requirements.txt && \
    rm -rf /root/.cache/pip

# ============================================================
# Stage 2: Runtime — Minimal production image
# ============================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/root/.local/bin:$PATH"

# Copy only installed packages from builder (no build tools, no apt cache)
COPY --from=builder /root/.local /root/.local

WORKDIR /app
COPY src/backend /app/

# Create directories and collect static files
RUN mkdir -p /app/static /app/media && \
    python manage.py collectstatic --noinput && \
    find /root/.local -name "*.pyc" -delete

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
