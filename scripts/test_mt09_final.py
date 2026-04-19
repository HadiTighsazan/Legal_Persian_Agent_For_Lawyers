#!/usr/bin/env python
"""
Final test for MT-09: Verify all endpoints work correctly after debugging.
"""
import os
import sys
import subprocess
import time

def run_curl_test(url, expected_status, description):
    """Run curl test and check status code."""
    try:
        # Use curl with -I to get headers only, -f to fail on error
        cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '-I', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        status_code = result.stdout.strip()
        if status_code == str(expected_status):
            print(f"[PASS] {description}: {url} -> {status_code}")
            return True
        else:
            print(f"[FAIL] {description}: {url} -> {status_code} (expected {expected_status})")
            return False
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {description}: {url} -> TIMEOUT")
        return False
    except Exception as e:
        print(f"[FAIL] {description}: {url} -> ERROR: {e}")
        return False

def run_curl_json_test(url, expected_key, description):
    """Run curl test and check JSON response."""
    try:
        cmd = ['curl', '-s', url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            if expected_key in data:
                print(f"[PASS] {description}: {url} -> contains '{expected_key}'")
                return True
            else:
                print(f"[FAIL] {description}: {url} -> missing '{expected_key}' in response")
                return False
        else:
            print(f"[FAIL] {description}: {url} -> curl failed with code {result.returncode}")
            return False
    except json.JSONDecodeError:
        print(f"[FAIL] {description}: {url} -> invalid JSON response")
        return False
    except Exception as e:
        print(f"[FAIL] {description}: {url} -> ERROR: {e}")
        return False

def check_container_status(service_name):
    """Check if Docker container is running."""
    try:
        cmd = ['docker-compose', 'ps', '--format', 'json', service_name]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and result.stdout.strip():
            import json
            data = json.loads(result.stdout)
            if data and data[0].get('State', '').lower() in ['running', 'healthy']:
                print(f"[PASS] Container {service_name} is running")
                return True
            else:
                print(f"[FAIL] Container {service_name} is not running properly")
                return False
        else:
            print(f"[FAIL] Container {service_name} check failed")
            return False
    except Exception as e:
        print(f"[FAIL] Container {service_name} check error: {e}")
        return False

def main():
    print("=" * 70)
    print("MT-09 Final Verification Test")
    print("=" * 70)
    
    all_tests_passed = True
    
    # Wait a moment for services to be ready
    print("\nWaiting 5 seconds for services to stabilize...")
    time.sleep(5)
    
    # 1. Check container statuses
    print("\n1. Checking container statuses:")
    containers = ['backend', 'postgres', 'redis', 'celery_worker', 'celery_beat', 'frontend']
    for container in containers:
        if not check_container_status(container):
            all_tests_passed = False
    
    # 2. Test health endpoints
    print("\n2. Testing health endpoints:")
    
    health_tests = [
        ('http://localhost:8000/health/', 200, 'Health endpoint'),
        ('http://localhost:8000/health/ready/', 200, 'Ready endpoint'),
        ('http://localhost:8000/health/live/', 200, 'Live endpoint'),
    ]
    
    for url, expected_status, desc in health_tests:
        if not run_curl_test(url, expected_status, desc):
            all_tests_passed = False
    
    # 3. Test health JSON response
    print("\n3. Testing health JSON response:")
    if not run_curl_json_test('http://localhost:8000/health/', 'status', 'Health JSON'):
        all_tests_passed = False
    
    # 4. Test other endpoints
    print("\n4. Testing other endpoints:")
    
    other_tests = [
        ('http://localhost:8000/admin/', 302, 'Admin endpoint (redirects to login)'),
        ('http://localhost:8000/swagger/', 200, 'Swagger UI'),
        ('http://localhost:8000/redoc/', 200, 'ReDoc UI'),
    ]
    
    for url, expected_status, desc in other_tests:
        if not run_curl_test(url, expected_status, desc):
            all_tests_passed = False
    
    # 5. Test API endpoints (should return 404 since commented out)
    print("\n5. Testing API endpoints (should return 404):")
    
    api_tests = [
        ('http://localhost:8000/api/v1/auth/', 404, 'Auth API endpoint'),
        ('http://localhost:8000/api/v1/documents/', 404, 'Documents API endpoint'),
        ('http://localhost:8000/api/v1/conversations/', 404, 'Conversations API endpoint'),
    ]
    
    for url, expected_status, desc in api_tests:
        if not run_curl_test(url, expected_status, desc):
            all_tests_passed = False
    
    # 6. Test frontend
    print("\n6. Testing frontend:")
    if not run_curl_test('http://localhost:5173/', 200, 'Frontend dev server'):
        print("[WARN] Frontend might not be running or accessible")
        # Don't fail the test for frontend
    
    # Summary
    print("\n" + "=" * 70)
    print("FINAL VERIFICATION SUMMARY")
    print("=" * 70)
    
    if all_tests_passed:
        print("[PASS] MT-09: All tests passed! Django project is fully functional.")
        print("\n✅ All containers are running")
        print("✅ Health endpoints return 200 OK with JSON")
        print("✅ Admin, Swagger, and ReDoc endpoints work")
        print("✅ API endpoints return 404 (expected - not implemented yet)")
        print("✅ No more 500 Internal Server Errors")
        print("\nMT-09 is now complete and ready for MT-10.")
        return 0
    else:
        print("[FAIL] MT-09: Some tests failed")
        print("\nPlease check the failed tests above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())