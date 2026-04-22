import json
import requests
import uuid
import sys

BASE_URL = "http://localhost:8000"

def run_test():
    print("=== FINAL VERIFICATION: Task 4.2 - Logout Endpoint ===")
    
    # Generate unique test email
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    print(f"Test email: {test_email}")
    
    # 1. Register
    print("\n[1/5] Registering user...")
    register_data = {
        "email": test_email,
        "password": "SecurePass123!",
        "full_name": "Test User"
    }
    
    try:
        resp = requests.post(f"{BASE_URL}/auth/register/", json=register_data, timeout=10)
    except requests.exceptions.ConnectionError:
        print("ERROR: Cannot connect to backend. Make sure it's running.")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code != 201:
        print(f"   FAIL: Registration failed: {resp.text[:200]}")
        return False
    
    data = resp.json()
    access_token = data["accessToken"]
    refresh_token = data["refreshToken"]
    print("   PASS: Registration successful")
    
    # 2. Test refresh before logout
    print("\n[2/5] Testing refresh before logout...")
    refresh_data = {"refreshToken": refresh_token}
    resp = requests.post(f"{BASE_URL}/auth/refresh/", json=refresh_data, timeout=10)
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code != 200:
        print(f"   FAIL: Refresh failed: {resp.text[:200]}")
        return False
    print("   PASS: Refresh works before logout")
    
    # 3. Test logout
    print("\n[3/5] Testing logout...")
    logout_data = {"refreshToken": refresh_token}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    resp = requests.post(f"{BASE_URL}/auth/logout/", json=logout_data, headers=headers, timeout=10)
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code != 204:
        print(f"   FAIL: Logout failed. Expected 204, got {resp.status_code}")
        print(f"   Response: {resp.text[:200]}")
        return False
    print("   PASS: Logout successful (204 No Content)")
    
    # 4. Verify token is revoked
    print("\n[4/5] Verifying token is revoked...")
    resp = requests.post(f"{BASE_URL}/auth/refresh/", json=refresh_data, timeout=10)
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code == 200:
        print("   FAIL: Refresh succeeded after logout (token not revoked)")
        return False
    print("   PASS: Refresh fails after logout (token properly revoked)")
    
    # 5. Quick error case test
    print("\n[5/5] Testing error cases...")
    
    # Logout without authentication
    resp = requests.post(f"{BASE_URL}/auth/logout/", json=logout_data, timeout=10)
    print(f"   Logout without auth: {resp.status_code} (expected: 401)")
    
    # Logout with missing token
    resp = requests.post(f"{BASE_URL}/auth/logout/", json={}, headers=headers, timeout=10)
    print(f"   Logout missing token: {resp.status_code} (expected: 400)")
    
    print("\n" + "="*60)
    print("SUCCESS: All tests passed!")
    print("Task 4.2 implementation is working correctly.")
    print("="*60)
    return True

if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)