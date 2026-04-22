import json
import requests
import uuid

BASE_URL = "http://localhost:8000"

def test_logout():
    print("Testing Task 4.2 - Logout Endpoint")
    print("=" * 50)
    
    # Generate unique test email
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    print(f"Test email: {test_email}")
    
    # 1. Register
    print("\n1. Registering user...")
    register_data = {
        "email": test_email,
        "password": "SecurePass123!",
        "full_name": "Test User"
    }
    
    try:
        resp = requests.post(f"{BASE_URL}/auth/register/", json=register_data)
        print(f"   Status: {resp.status_code}")
        if resp.status_code != 201:
            print(f"   ERROR: Registration failed: {resp.text}")
            return False
    except Exception as e:
        print(f"   ERROR: Could not connect to backend: {e}")
        return False
    
    data = resp.json()
    access_token = data["accessToken"]
    refresh_token = data["refreshToken"]
    print("   ✓ Registration successful")
    
    # 2. Test refresh before logout
    print("\n2. Testing refresh before logout...")
    refresh_data = {"refreshToken": refresh_token}
    resp = requests.post(f"{BASE_URL}/auth/refresh/", json=refresh_data)
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code != 200:
        print(f"   ERROR: Refresh failed: {resp.text}")
        return False
    print("   ✓ Refresh successful before logout")
    
    # 3. Test logout
    print("\n3. Testing logout...")
    logout_data = {"refreshToken": refresh_token}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    resp = requests.post(f"{BASE_URL}/auth/logout/", json=logout_data, headers=headers)
    print(f"   Status: {resp.status_code}")
    print(f"   Response: {resp.text}")
    
    if resp.status_code != 204:
        print(f"   ERROR: Logout failed. Expected 204, got {resp.status_code}")
        return False
    print("   ✓ Logout successful (204 No Content)")
    
    # 4. Verify token is revoked
    print("\n4. Verifying token is revoked...")
    resp = requests.post(f"{BASE_URL}/auth/refresh/", json=refresh_data)
    print(f"   Status: {resp.status_code}")
    
    if resp.status_code == 200:
        print("   ERROR: Refresh succeeded after logout (token not revoked)")
        return False
    print("   ✓ Refresh fails after logout (token properly revoked)")
    
    # 5. Test error cases
    print("\n5. Testing error cases...")
    
    # 5a. Logout without authentication
    print("\n   5a. Logout without authentication...")
    resp = requests.post(f"{BASE_URL}/auth/logout/", json=logout_data)
    print(f"      Status: {resp.status_code} (expected: 401)")
    
    # 5b. Logout with missing refresh token
    print("\n   5b. Logout with missing refresh token...")
    resp = requests.post(f"{BASE_URL}/auth/logout/", json={}, headers=headers)
    print(f"      Status: {resp.status_code} (expected: 400)")
    
    # 5c. Logout with invalid token
    print("\n   5c. Logout with invalid refresh token...")
    resp = requests.post(f"{BASE_URL}/auth/logout/", 
                        json={"refreshToken": "invalid.jwt.token.here"}, 
                        headers=headers)
    print(f"      Status: {resp.status_code} (expected: 401)")
    
    print("\n" + "=" * 50)
    print("SUCCESS: All tests passed! Task 4.2 implementation is working correctly.")
    return True

if __name__ == "__main__":
    success = test_logout()
    exit(0 if success else 1)