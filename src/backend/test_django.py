#!/usr/bin/env python
"""
Simple test script to verify Django project can start.
"""
import os
import sys
import django
from django.core.wsgi import get_wsgi_application

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_django_startup():
    """Test if Django can start successfully."""
    print("Testing Django project startup...")
    
    try:
        # Set Django settings module
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        
        # Initialize Django
        django.setup()
        
        print("✅ Django initialized successfully!")
        
        # Test database connection
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            print(f"✅ Database connection test: {result}")
        
        # Test if apps are loaded
        from django.apps import apps
        app_configs = apps.get_app_configs()
        print(f"✅ Loaded {len(app_configs)} Django apps")
        
        # List our custom apps
        custom_apps = ['users', 'documents', 'conversations', 'tasks', 'api_keys']
        for app in custom_apps:
            try:
                apps.get_app_config(app)
                print(f"  ✅ {app} app loaded")
            except LookupError:
                print(f"  ❌ {app} app NOT loaded")
        
        # Test if models are registered
        from users.models import User
        print(f"✅ User model imported: {User}")
        
        print("\n[DONE] Django project startup test PASSED!")
        return True
        
    except Exception as e:
        print(f"\n[FAILED] Django project startup test FAILED!")
        print(f"Error: {type(e).__name__}: {e}")
        # Don't print full traceback for missing dependencies
        if "ModuleNotFoundError" in str(type(e).__name__):
            print(f"Note: Missing dependency - install requirements.txt")
        return False

def test_health_endpoint():
    """Test if health endpoint view can be instantiated."""
    print("\nTesting health endpoint...")
    
    try:
        from config.views import HealthCheckView, ReadyCheckView, LiveCheckView
        
        # Test view instantiation
        health_view = HealthCheckView()
        ready_view = ReadyCheckView()
        live_view = LiveCheckView()
        
        print("✅ Health check views instantiated successfully")
        print(f"  ✅ HealthCheckView: {health_view}")
        print(f"  ✅ ReadyCheckView: {ready_view}")
        print(f"  ✅ LiveCheckView: {live_view}")
        
        return True
        
    except Exception as e:
        print(f"❌ Health endpoint test FAILED!")
        print(f"Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("DocuChat Django Project Test")
    print("=" * 60)
    
    success = True
    
    # Test 1: Django startup
    if not test_django_startup():
        success = False
    
    # Test 2: Health endpoints
    if not test_health_endpoint():
        success = False
    
    print("\n" + "=" * 60)
    if success:
        print("✅ ALL TESTS PASSED - Django project is ready!")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED - Check errors above")
        sys.exit(1)