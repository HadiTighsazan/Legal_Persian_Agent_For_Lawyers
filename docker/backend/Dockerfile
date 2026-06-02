# Django Backend Dockerfile
# Using Iranian PyPI mirror for compliance

FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_NO_CACHE_DIR=1

# Install system dependencies for EasyOCR, OpenCV, and pdf2image
# Using Iranian Debian mirrors for reliable access
RUN sed -i 's|deb.debian.org/debian|mirror.arvancloud.ir/debian|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org/debian|mirror.arvancloud.ir/debian|g' /etc/apt/sources.list && \
    sed -i 's|deb.debian.org/debian-security|mirror.arvancloud.ir/debian-security|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org/debian-security|mirror.arvancloud.ir/debian-security|g' /etc/apt/sources.list && \
    apt-get update -o Acquire::Check-Valid-Until=false && \
    apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Configure Runflare PyPI mirror with official PyPI as fallback
RUN pip config set global.index-url https://mirror-pypi.runflare.com/simple && \
pip config set global.trusted-host mirror-pypi.runflare.com


# Copy requirements file
COPY src/backend/requirements.txt /app/requirements.txt

# Install Python dependencies (skip pip upgrade to avoid 402 errors)
RUN pip install -r requirements.txt && \
    rm -rf /root/.cache/pip

# Copy Django project
COPY src/backend /app/

# Copy entrypoint script (outside /app to survive volume mount)
COPY docker/backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directory for static files
RUN mkdir -p /app/static /app/media

# Expose port
EXPOSE 8000

# Use entrypoint to run migrations before starting Gunicorn
ENTRYPOINT ["/entrypoint.sh"]
