# Django Backend Dockerfile
# Using V2Ray proxy for all package downloads
# Pass HOST_IP as build arg (e.g., --build-arg HOST_IP=192.168.1.112)

ARG HOST_IP=host.docker.internal

FROM python:3.11-slim-bookworm

ARG HOST_IP

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_NO_CACHE_DIR=1

# Proxy environment variables for apt-get and pip
# Uses HOST_IP build arg (defaults to host.docker.internal for runtime)
ENV HTTP_PROXY=http://${HOST_IP}:10808
ENV HTTPS_PROXY=http://${HOST_IP}:10808
ENV http_proxy=http://${HOST_IP}:10808
ENV https_proxy=http://${HOST_IP}:10808

# Install system dependencies for EasyOCR, OpenCV, and pdf2image
# Proxy is used via the HTTP_PROXY env vars above
RUN apt-get update -o Acquire::Check-Valid-Until=false && \
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

# Copy requirements file
COPY src/backend/requirements.txt /app/requirements.txt

# Install Python dependencies (skip pip upgrade to avoid 402 errors)
# Proxy is used via the HTTP_PROXY env vars set above
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
