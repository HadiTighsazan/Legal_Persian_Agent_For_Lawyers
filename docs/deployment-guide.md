# Deployment Guide - Production Setup

This guide covers deploying DocuChat to a production environment.

## Production Architecture

### Recommended Stack
- **Container Orchestration**: Docker Compose (single server) or Kubernetes (multi-server)
- **Reverse Proxy**: Nginx with SSL termination
- **Database**: PostgreSQL with pgvector (managed service or self-hosted)
- **Cache/Message Broker**: Redis (managed service or self-hosted)
- **File Storage**: Local storage or cloud storage (S3-compatible)
- **Monitoring**: Prometheus + Grafana (optional)
- **Logging**: ELK Stack or Loki + Grafana (optional)

## Production Docker Compose Configuration

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: docuchat-postgres-prod
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    command: >
      postgres -c shared_preload_libraries=vector
               -c max_connections=200
               -c shared_buffers=256MB
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: docuchat-redis-prod
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: ./docker/backend
      dockerfile: Dockerfile.prod
    container_name: docuchat-backend-prod
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://redis:6379/0
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - DJANGO_DEBUG=False
      - DJANGO_ALLOWED_HOSTS=${DJANGO_ALLOWED_HOSTS}
      - DJANGO_CSRF_TRUSTED_ORIGINS=${DJANGO_CSRF_TRUSTED_ORIGINS}
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - MEDIA_ROOT=/app/media
      - STATIC_ROOT=/app/static
    volumes:
      - media_volume:/app/media
      - static_volume:/app/static
    command: >
      sh -c "
        python manage.py collectstatic --noinput &&
        python manage.py migrate &&
        gunicorn docuchat.wsgi:application --bind 0.0.0.0:8000 --workers 4 --worker-class gthread --threads 2 --access-logfile -
      "

  celery_worker:
    build:
      context: ./docker/backend
      dockerfile: Dockerfile.prod
    container_name: docuchat-celery-worker-prod
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://redis:6379/0
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - DJANGO_DEBUG=False
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - MEDIA_ROOT=/app/media
    volumes:
      - media_volume:/app/media
    command: celery -A docuchat worker --loglevel=info --concurrency=4

  celery_beat:
    build:
      context: ./docker/backend
      dockerfile: Dockerfile.prod
    container_name: docuchat-celery-beat-prod
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://redis:6379/0
      - DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
      - DJANGO_DEBUG=False
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    command: celery -A docuchat beat --loglevel=info

  frontend:
    build:
      context: ./docker/frontend
      dockerfile: Dockerfile.prod
    container_name: docuchat-frontend-prod
    restart: unless-stopped
    environment:
      - VITE_API_BASE_URL=${VITE_API_BASE_URL}
    volumes:
      - frontend_static:/app/dist

  nginx:
    image: nginx:alpine
    container_name: docuchat-nginx-prod
    restart: unless-stopped
    depends_on:
      - backend
      - frontend
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/nginx/nginx.prod.conf:/etc/nginx/nginx.conf:ro
      - ./docker/nginx/ssl:/etc/nginx/ssl:ro
      - static_volume:/static:ro
      - media_volume:/media:ro
      - frontend_static:/frontend:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/health/"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  postgres_data:
  redis_data:
  media_volume:
  static_volume:
  frontend_static:
```

## Production Environment Variables

Create `.env.prod`:

```bash
# Database
POSTGRES_DB=docuchat_prod
POSTGRES_USER=docuchat_user
POSTGRES_PASSWORD=your_secure_password_here

# Django
DJANGO_SECRET_KEY=your_django_secret_key_here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Redis
REDIS_URL=redis://redis:6379/0

# OpenAI
OPENAI_API_KEY=your_openai_api_key_here

# Frontend
VITE_API_BASE_URL=https://yourdomain.com/api

# Optional: Email (for password reset, notifications)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=DocuChat <noreply@yourdomain.com>
```

## Production Dockerfiles

### Backend Dockerfile (Dockerfile.prod)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set Iranian PyPI mirrors
RUN pip config set global.index-url https://mirror-pypi.runflare.com/simple
RUN pip config set global.extra-index-url https://package-mirror.liara.ir/repository/pypi/simple

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/backend/ .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Run as non-root user
EXPOSE 8000
```

### Frontend Dockerfile (Dockerfile.prod)
```dockerfile
FROM node:20-alpine as builder

WORKDIR /app

# Set Iranian npm registry
RUN npm config set registry https://mirror-npm.runflare.com

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci --only=production

# Copy source code
COPY src/frontend/ .

# Build application
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
```

## Nginx Production Configuration

Create `docker/nginx/nginx.prod.conf`:

```nginx
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging
    access_log /var/log/nginx/access.log;
    error_log /var/log/nginx/error.log;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/xml+rss application/json;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/s;

    # Backend upstream
    upstream backend {
        server backend:8000;
    }

    # Frontend upstream
    upstream frontend {
        server frontend:80;
    }

    server {
        listen 80;
        server_name yourdomain.com www.yourdomain.com;
        
        # Redirect HTTP to HTTPS
        return 301 https://$server_name$request_uri;
    }

    server {
        listen 443 ssl http2;
        server_name yourdomain.com www.yourdomain.com;

        # SSL certificates (replace with your paths)
        ssl_certificate /etc/nginx/ssl/yourdomain.crt;
        ssl_certificate_key /etc/nginx/ssl/yourdomain.key;
        
        # SSL configuration
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
        ssl_prefer_server_ciphers off;
        ssl_session_cache shared:SSL:10m;
        ssl_session_timeout 10m;

        # Health check endpoint
        location /health/ {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        # Static files (Django)
        location /static/ {
            alias /static/;
            expires 1y;
            add_header Cache-Control "public, immutable";
        }

        # Media files
        location /media/ {
            alias /media/;
            expires 7d;
            add_header Cache-Control "public";
        }

        # Frontend static files
        location / {
            root /frontend;
            try_files $uri $uri/ /index.html;
            expires 1h;
            add_header Cache-Control "public";
        }

        # API endpoints
        location /api/ {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Rate limiting for API
            limit_req zone=api burst=20 nodelay;
            
            # Timeouts
            proxy_connect_timeout 30s;
            proxy_send_timeout 30s;
            proxy_read_timeout 30s;
        }

        # Admin interface
        location /admin/ {
            proxy_pass http://backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Rate limiting for admin
            limit_req zone=auth burst=10 nodelay;
        }
    }
}
```

## Deployment Steps

### 1. Prepare Server
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker and Docker Compose
sudo apt install -y docker.io docker-compose

# Add user to docker group
sudo usermod -aG docker $USER

# Logout and login again for group changes to take effect
```

### 2. Clone and Configure
```bash
# Clone repository
git clone <repository-url> /opt/docuchat
cd /opt/docuchat

# Copy production environment file
cp .env.example .env.prod

# Edit .env.prod with your production values
nano .env.prod

# Generate Django secret key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Set up SSL certificates (Let's Encrypt)
# Place certificates in docker/nginx/ssl/
```

### 3. Build and Deploy
```bash
# Build and start services
docker-compose -f docker-compose.prod.yml up --build -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Check service status
docker-compose -f docker-compose.prod.yml ps
```

### 4. Initial Setup
```bash
# Create superuser (if needed)
docker-compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser

# Run initial migrations (already done in startup command)
# Check database connection
docker-compose -f docker-compose.prod.yml exec backend python manage.py check --database default
```

### 5. Monitoring and Maintenance
```bash
# View logs
docker-compose -f docker-compose.prod.yml logs -f backend
docker-compose -f docker-compose.prod.yml logs -f nginx

# Backup database
docker-compose -f docker-compose.prod.yml exec postgres pg_dump -U docuchat_user docuchat_prod > backup_$(date +%Y%m%d).sql

# Update application
git pull
docker-compose -f docker-compose.prod.yml up --build -d

# Scale services (if needed)
docker-compose -f docker-compose.prod.yml up -d --scale celery_worker=3
```

## Security Considerations

### 1. **SSL/TLS**
- Use Let's Encrypt for free SSL certificates
- Enable HTTP/2 for better performance
- Set strong SSL cipher suites

### 2. **Database Security**
- Use strong passwords for database users
- Enable SSL for database connections
- Regular backups and monitoring

### 3. **Django Security**
- Set `DEBUG=False` in production
- Configure `ALLOWED_HOSTS` properly
- Use secure session and CSRF settings
- Enable HTTPS redirects

### 4. **Container Security**
- Run containers as non-root users
- Use read-only filesystems where possible
- Regular security updates for base images

### 5. **Network Security**
- Use firewall to restrict access to necessary ports only
- Consider using a VPN for admin access
- Implement rate limiting

## Performance Tuning

### Database
```sql
-- PostgreSQL tuning for pgvector
ALTER SYSTEM SET shared_buffers = '256MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
ALTER SYSTEM SET maintenance_work_mem = '64MB';
ALTER SYSTEM SET checkpoint_completion_target = 0.9;
ALTER SYSTEM SET wal_buffers = '16MB';
ALTER SYSTEM SET default_statistics_target = 100;
```

### Redis
- Set appropriate maxmemory policy
- Enable persistence with AOF
- Monitor memory usage

### Django/Gunicorn
- Adjust worker count based on CPU cores
- Use appropriate worker class (gthread for I/O bound)
- Enable connection pooling for database

### Nginx
- Enable gzip compression
- Configure caching for static files
- Set appropriate buffer sizes

## Backup Strategy

### Daily Backups
```bash
#!/bin/bash
# backup.sh
DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/docuchat"

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup database
docker-compose -f /opt/docuchat/docker-compose.prod.yml exec -T postgres \
    pg_dump -U docuchat_user docuchat_prod > $BACKUP_DIR/db_backup_$DATE.sql

# Compress backup
gzip $BACKUP_DIR/db_backup_$DATE.sql

# Backup media files (if any)
tar -czf $BACKUP_DIR/media_backup_$DATE.tar.gz -C /opt/docuchat/media .

# Keep backups for 30 days
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_DIR/db_backup_$DATE.sql.gz"
```

### Automated Backups with Cron
```bash
# Add to crontab (crontab -e)
0 2 * * * /opt/docuchat/scripts/backup.sh
```

### Restore from Backup
```bash
# Restore database
gunzip -c db_backup_20250420.sql.gz | docker-compose -f docker-compose.prod.yml exec -T postgres \
    psql -U docuchat_user docuchat_prod

# Restore media files
tar -xzf media_backup_20250420.tar.gz -C /opt/docuchat/media
```

## Monitoring

### Health Checks
- **Application**: `https://yourdomain.com/health/`
- **API**: `https://yourdomain.com/api/health/`
- **Database**: `docker-compose exec postgres pg_isready -U docuchat_user`
- **Redis**: `docker-compose exec redis redis-cli ping`

### Log Monitoring
```bash
# View all logs
docker-compose -f docker-compose.prod.yml logs --tail=100

# View specific service logs
docker-compose -f docker-compose.prod.yml logs --tail=50 backend
docker-compose -f docker-compose.prod.yml logs --tail=50 nginx

# Follow logs in real-time
docker-compose -f docker-compose.prod.yml logs -f
```

### Resource Monitoring
```bash
# Check container resource usage
docker stats

# Check disk usage
df -h

# Check memory usage
free -h
```

## Troubleshooting Production Issues

### 1. **Database Connection Issues**
```bash
# Check if PostgreSQL is running
docker-compose -f docker-compose.prod.yml ps postgres

# Check logs
docker-compose -f docker-compose.prod.yml logs postgres

# Test connection
docker-compose -f docker-compose.prod.yml exec backend python manage.py check --database default
```

### 2. **Application Not Starting**
```bash
# Check backend logs
docker-compose -f docker-compose.prod.yml logs backend

# Check if migrations are applied
docker-compose -f docker-compose.prod.yml exec backend python manage.py showmigrations

# Check environment variables
docker-compose -f docker-compose.prod.yml exec backend env | grep DJANGO
```

### 3. **Nginx Issues**
```bash
# Check nginx configuration
docker-compose -f docker-compose.prod.yml exec nginx nginx -t

# Check nginx logs
docker-compose -f docker-compose.prod.yml logs nginx

# Check if nginx is serving traffic
curl -I https://yourdomain.com/health/
```

### 4. **Redis/Celery Issues**
```bash
# Check Redis connection
docker-compose -f docker-compose.prod.yml exec redis redis-cli ping

# Check Celery worker status
docker-compose -f docker-compose.prod.yml exec backend celery -A docuchat status

# Check Celery task queue
docker-compose -f docker-compose.prod.yml exec backend celery -A docuchat inspect active
```

## Scaling Considerations

### Vertical Scaling
- Increase CPU/RAM for database server
- Add more workers to Gunicorn
- Increase Redis memory limit

### Horizontal Scaling
1. **Database**: Use read replicas for queries
2. **Backend**: Add more backend instances behind load balancer
3. **Celery**: Add more worker instances
4. **Redis**: Use Redis Cluster for high availability

### Load Balancer Configuration
```nginx
# Example: Multiple backend instances
upstream backend {
    server backend1:8000;
    server backend2:8000;
    server backend3:8000;
    least_conn;  # Load balancing method
}
```

## Maintenance Procedures

### Regular Maintenance
1. **Weekly**: Check logs for errors, monitor disk space
2. **Monthly**: Update Docker images, review security patches
3. **Quarterly**: Review performance metrics, optimize queries

### Update Procedure
```bash
# 1. Pull latest code
cd /opt/docuchat
git pull

# 2. Backup current state
./scripts/backup.sh

# 3. Update and restart
docker-compose -f docker-compose.prod.yml up --build -d

# 4. Verify
docker-compose -f docker-compose.prod.yml ps
curl -f https://yourdomain.com/health/
```

### Rollback Procedure
```bash
# 1. Stop current services
docker-compose -f docker-compose.prod.yml down

# 2. Restore from backup
./scripts/restore.sh backup_20250420

# 3. Start previous version
git checkout v1.0.0
docker-compose -f docker-compose.prod.yml up -d
```

## Conclusion

This deployment guide provides a comprehensive setup for running Docuchat in production. The architecture is designed for reliability, security, and scalability. Regular monitoring, backups, and maintenance are essential for production stability.

For additional support:
- Check the `docs/` directory for more documentation
- Review logs for troubleshooting
- Monitor resource usage regularly
- Keep dependencies updated for security

**Next Steps:**
1. Set up monitoring and alerting
2. Configure automated backups
3. Implement CI/CD pipeline
4. Set up staging environment for testing
