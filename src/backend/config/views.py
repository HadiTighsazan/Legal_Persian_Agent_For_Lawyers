"""
Health check views for the DocuChat API.
"""
import logging
from datetime import datetime

from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views import View
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

logger = logging.getLogger(__name__)


class HealthCheckView(View):
    """
    Health check endpoint that verifies all critical services.
    """
    
    def get(self, request):
        """Return health status of all services."""
        status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'services': {
                'database': 'unknown',
                'redis': 'unknown',
                'celery': 'unknown',
            },
            'version': '1.0.0',
        }
        
        overall_healthy = True
        
        # Check database
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            status['services']['database'] = 'up'
        except OperationalError as e:
            status['services']['database'] = 'down'
            status['services']['database_error'] = str(e)
            overall_healthy = False
            logger.error(f"Database health check failed: {e}")
        
        # Check Redis
        try:
            redis_url = self._get_redis_url()
            redis_client = Redis.from_url(redis_url, socket_connect_timeout=2)
            redis_client.ping()
            status['services']['redis'] = 'up'
        except (RedisConnectionError, ValueError) as e:
            status['services']['redis'] = 'down'
            status['services']['redis_error'] = str(e)
            overall_healthy = False
            logger.error(f"Redis health check failed: {e}")
        
        # Check Celery (via Redis connection)
        # For now, we assume Celery is up if Redis is up
        # In a more complete implementation, we'd check Celery worker status
        if status['services']['redis'] == 'up':
            status['services']['celery'] = 'up'
        else:
            status['services']['celery'] = 'down'
            overall_healthy = False
        
        # Update overall status
        if not overall_healthy:
            status['status'] = 'unhealthy'
        
        response_status = 200 if overall_healthy else 503
        return JsonResponse(status, status=response_status)
    
    def _get_redis_url(self):
        """Get Redis URL from settings or environment."""
        from django.conf import settings
        return getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')


class ReadyCheckView(View):
    """
    Simple readiness check for load balancers and orchestrators.
    """
    
    def get(self, request):
        """Return simple readiness status."""
        return JsonResponse({
            'status': 'ready',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        })


class LiveCheckView(View):
    """
    Simple liveness check for Kubernetes and Docker.
    """
    
    def get(self, request):
        """Return simple liveness status."""
        return JsonResponse({
            'status': 'alive',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        })