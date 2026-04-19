"""
Core views for the DocuChat system.
"""
from datetime import datetime

from django.http import JsonResponse
from django.views import View


class HealthCheckView(View):
    """
    Simple health check endpoint for Docker and load balancers.
    Returns 200 OK with basic status information.
    """
    
    def get(self, request):
        """Return basic health status."""
        return JsonResponse({
            'status': 'ok',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'service': 'docuchat-api',
            'version': '1.0.0',
        })


class ReadyCheckView(View):
    """
    Readiness check for Kubernetes and orchestrators.
    """
    
    def get(self, request):
        """Return readiness status."""
        return JsonResponse({
            'status': 'ready',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        })


class LiveCheckView(View):
    """
    Liveness check for Kubernetes and Docker.
    """
    
    def get(self, request):
        """Return liveness status."""
        return JsonResponse({
            'status': 'alive',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        })