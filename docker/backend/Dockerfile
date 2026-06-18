# Django Backend Dockerfile
#
# NOTE: Heavy OCR dependencies (easyocr, opencv, pdf2image, pytesseract,
# pdfplumber, arabic_reshaper, python-bidi, hazm) and their system-level
# dependencies (libgl, libglib, poppler-utils) have been REMOVED in the
# Phase 1 refactoring. PDF text extraction now uses:
#   - PyMuPDF (primary, lightweight)
#   - Qwen3 VL via OpenRouter API (fallback for garbled CMap fonts)

FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV PIP_NO_CACHE_DIR=1

# Set working directory
WORKDIR /app

# Copy requirements file
COPY src/backend/requirements.txt /app/requirements.txt

# Install Python dependencies from official PyPI index
RUN pip install \
-r requirements.txt \
&& rm -rf /root/.cache/pip

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
