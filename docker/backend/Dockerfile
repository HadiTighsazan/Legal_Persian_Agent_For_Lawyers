# Django Backend Dockerfile
# Using Iranian PyPI mirror for compliance

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_NO_CACHE_DIR=1

# Set working directory
WORKDIR /app

# Configure Iranian PyPI mirror (fallback mirror)
RUN pip config set global.index-url https://package-mirror.liara.ir/repository/pypi/simple && \
    pip config set global.trusted-host package-mirror.liara.ir && \
    pip config set global.timeout 60 && \
    pip config set global.retries 5

# Copy requirements file
COPY src/backend/requirements.txt /app/requirements.txt

# Install Python dependencies (skip pip upgrade to avoid 402 errors)
RUN pip install -r requirements.txt

# Copy Django project
COPY src/backend /app/

# Create directory for static files
RUN mkdir -p /app/static /app/media

# Expose port
EXPOSE 8000

# Run Gunicorn
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
