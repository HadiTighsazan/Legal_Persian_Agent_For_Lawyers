#!/usr/bin/env python
"""
Verification script for MT-09: Initialize Django Project Structure
This script checks that all required components are in place.
"""
import os
import sys
import subprocess

def check_file_exists(path, description):
    """Check if a file exists and print status."""
    if os.path.exists(path):
        print(f"[OK] {description}: {path}")
        return True
    else:
        print(f"[FAIL] {description}: {path} - NOT FOUND")
        return False

def check_directory_exists(path, description):
    """Check if a directory exists and print status."""
    if os.path.exists(path) and os.path.isdir(path):
        print(f"[OK] {description}: {path}")
        return True
    else:
        print(f"[FAIL] {description}: {path} - NOT FOUND")
        return False

def check_file_content(path, search_string, description):
    """Check if a file contains specific content."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            if search_string in content:
                print(f"[OK] {description}: Found '{search_string}' in {path}")
                return True
            else:
                print(f"[FAIL] {description}: '{search_string}' NOT FOUND in {path}")
                return False
    except Exception as e:
        print(f"[FAIL] {description}: Error reading {path}: {e}")
        return False

def main():
    print("=" * 70)
    print("MT-09 Verification: Django Project Structure")
    print("=" * 70)
    
    # Get project root directory (one level up from scripts directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)  # Go up one level to project root
    backend_dir = os.path.join(base_dir, 'src', 'backend')
    
    all_checks_passed = True
    
    # 1. Check critical files exist
    print("\n1. Checking critical files:")
    files_to_check = [
        (os.path.join(backend_dir, 'config', 'settings.py'), 'Django settings'),
        (os.path.join(backend_dir, 'config', 'celery.py'), 'Celery configuration'),
        (os.path.join(backend_dir, 'config', '__init__.py'), 'Celery app export'),
        (os.path.join(backend_dir, 'config', 'urls.py'), 'URL configuration'),
        (os.path.join(backend_dir, 'core', 'views.py'), 'Core app views'),
        (os.path.join(backend_dir, 'users', 'models.py'), 'User models'),
        (os.path.join(backend_dir, 'documents', 'models.py'), 'Document models'),
        (os.path.join(backend_dir, 'conversations', 'models.py'), 'Conversation models'),
        (os.path.join(backend_dir, 'tasks', 'models.py'), 'Task models'),
        (os.path.join(backend_dir, 'requirements.txt'), 'Python requirements'),
    ]
    
    for path, desc in files_to_check:
        if not check_file_exists(path, desc):
            all_checks_passed = False
    
    # 2. Check directories exist
    print("\n2. Checking critical directories:")
    dirs_to_check = [
        (os.path.join(backend_dir, 'core'), 'Core app'),
        (os.path.join(backend_dir, 'users'), 'Users app'),
        (os.path.join(backend_dir, 'documents'), 'Documents app'),
        (os.path.join(backend_dir, 'conversations'), 'Conversations app'),
        (os.path.join(backend_dir, 'tasks'), 'Tasks app'),
        (os.path.join(backend_dir, 'api_keys'), 'API Keys app'),
    ]
    
    for path, desc in dirs_to_check:
        if not check_directory_exists(path, desc):
            all_checks_passed = False
    
    # 3. Check settings.py content
    print("\n3. Checking settings.py configuration:")
    settings_path = os.path.join(backend_dir, 'config', 'settings.py')
    
    checks = [
        ("'core'", "Core app in INSTALLED_APPS"),
        ("AUTH_USER_MODEL = 'users.User'", "Custom User model"),
        ("CELERY_BROKER_URL", "Celery broker configuration"),
        ("os.makedirs(LOGS_DIR, exist_ok=True)", "Logs directory creation"),
        ("env.db('DATABASE_URL'", "Database environment variable"),
    ]
    
    for search_str, desc in checks:
        if not check_file_content(settings_path, search_str, desc):
            all_checks_passed = False
    
    # 4. Check urls.py for health endpoints
    print("\n4. Checking URL configuration:")
    urls_path = os.path.join(backend_dir, 'config', 'urls.py')
    
    url_checks = [
        ("path('health/',", "Health endpoint"),
        ("from core.views import", "Core views import"),
    ]
    
    for search_str, desc in url_checks:
        if not check_file_content(urls_path, search_str, desc):
            all_checks_passed = False
    
    # 5. Check core views
    print("\n5. Checking core app views:")
    core_views_path = os.path.join(backend_dir, 'core', 'views.py')
    
    view_checks = [
        ("class HealthCheckView", "HealthCheckView class"),
        ("JsonResponse", "JSON response"),
        ("'status': 'ok'", "Status OK response"),
    ]
    
    for search_str, desc in view_checks:
        if not check_file_content(core_views_path, search_str, desc):
            all_checks_passed = False
    
    # 6. Check docker-compose health check
    print("\n6. Checking Docker configuration:")
    docker_compose_path = os.path.join(base_dir, 'docker-compose.yml')
    
    if check_file_exists(docker_compose_path, 'docker-compose.yml'):
        docker_checks = [
            ("test: [\"CMD-SHELL\", \"python -c", "Health check in docker-compose"),
            ("http://localhost:8000/health/", "Health endpoint in docker-compose"),
            ("backend:", "Backend service"),
            ("celery_worker:", "Celery worker service"),
        ]
        
        for search_str, desc in docker_checks:
            if not check_file_content(docker_compose_path, search_str, desc):
                all_checks_passed = False
    
    # 7. Check .env file
    print("\n7. Checking environment configuration:")
    env_path = os.path.join(base_dir, '.env')
    if check_file_exists(env_path, '.env file'):
        env_checks = [
            ("DJANGO_SECRET_KEY", "Django secret key"),
            ("DATABASE_URL", "Database URL"),
            ("REDIS_URL", "Redis URL"),
        ]
        
        for search_str, desc in env_checks:
            if not check_file_content(env_path, search_str, desc):
                all_checks_passed = False
    else:
        print("[WARN] .env file not found (may be in .gitignore)")
    
    # Summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    if all_checks_passed:
        print("[PASS] MT-09: Django Project Structure - ALL CHECKS PASSED")
        print("\nThe Django project structure is complete and ready for:")
        print("1. Docker deployment with docker-compose")
        print("2. Health checks at /health/ endpoint")
        print("3. Database migrations")
        print("4. Celery integration with Redis")
        print("\nNext step: MT-10 - Initialize Frontend Project Structure")
        return 0
    else:
        print("[FAIL] MT-09: Some checks failed")
        print("\nPlease review the failed checks above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())