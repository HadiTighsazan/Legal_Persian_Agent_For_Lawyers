#!/usr/bin/env python3
"""
Integration test for the logout endpoint (Task 4.2).
Tests the complete authentication flow: register → login → refresh → logout → verify revocation.
"""
import json
import requests
import sys
import uuid

BASE_URL = "http://localhost:8000"
# BASE_URL = "http://localhost/api"  # If using Nginx proxy

def print_step(step):
    print(f"\n{'='*60}")
    print(f"STEP: {step}")
    print(f"{'='*60}")

def test_logout_endpoint():
    """Test the complete logout flow."""
    
    # Generate unique test data
    test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    test_password = "SecurePass123!"
    test_full_name = "Test User"
    
    print(f"Testing with email: {test_email}")
    
    # 1. Register a new user
    print_step("1. Register new user")
    register_data = {
        "email": test_email,
        "password": test_password,
        "full_name": test_full_name
    }
    
    try:
        register_response = requests.post(
            f"{BASE_URL}/auth/register/",
            json=register_data,
            headers={"Content-Type": "application/json"}
        )
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to {BASE_URL}. Make sure backend is running.")
        print("Try: docker-compose up -d backend")
        return False
    
    print(f"Register Response Status: {register_response.status_code}")
    print(f"Register Response Body: {register_response.text}")
    
    if register_response.status_code != 201:
        print("ERROR: User registration failed")
        return False
    
    register_json = register_response.json()
    access_token = register_json.get("accessToken")
    refresh_token = register_json.get("refreshToken")
    
    if not access_token or not refresh_token:
        print("ERROR: Tokens not received in registration response")
        return False
    
    print(f"✓ User registered successfully")
    print(f"  Access Token: {access_token[:50]}...")
    print(f"  Refresh Token: {refresh_token[:50]}...")
    
    # 2. Login (optional, but good to test)
    print_step("2. Login with registered user")
    login_data = {
        "email": test_email,
        "password": test_password
    }
    
    login_response = requests.post(
        f"{BASE_URL}/auth/login/",
        json=login_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Login Response Status: {login_response.status_code}")
    
    if login_response.status_code != 200:
        print("ERROR: Login failed")
        return False
    
    login_json = login_response.json()
    login_access_token = login_json.get("accessToken")
    login_refresh_token = login_json.get("refreshToken")
    
    print(f"✓ Login successful")
    print(f"  New Access Token: {login_access_token[:50]}...")
    print(f"  New Refresh Token: {login_refresh_token[:50]}...")
    
    # Use the tokens from login (they should be fresh)
    access_token = login_access_token
    refresh_token = login_refresh_token
    
    # 3. Test refresh endpoint
    print_step("3. Test refresh endpoint (before logout)")
    refresh_data = {
        "refreshToken": refresh_token
    }
    
    refresh_response = requests.post(
        f"{BASE_URL}/auth/refresh/",
        json=refresh_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Refresh Response Status: {refresh_response.status_code}")
    print(f"Refresh Response Body: {refresh_response.text}")
    
    if refresh_response.status_code != 200:
        print("ERROR: Refresh failed before logout")
        return False
    
    new_access_token = refresh_response.json().get("accessToken")
    print(f"✓ Refresh successful before logout")
    print(f"  New Access Token: {new_access_token[:50]}...")
    
    # 4. Test logout endpoint
    print_step("4. Test logout endpoint")
    logout_data = {
        "refreshToken": refresh_token
    }
    
    logout_response = requests.post(
        f"{BASE_URL}/auth/logout/",
        json=logout_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    )
    
    print(f"Logout Response Status: {logout_response.status_code}")
    print(f"Logout Response Body: {logout_response.text}")
    
    if logout_response.status_code != 204:
        print(f"ERROR: Logout failed. Expected 204, got {logout_response.status_code}")
        return False
    
    print(f"✓ Logout successful (204 No Content)")
    
    # 5. Verify token is revoked (refresh should fail)
    print_step("5. Verify token is revoked (refresh should fail)")
    refresh_after_logout_response = requests.post(
        f"{BASE_URL}/auth/refresh/",
        json=refresh_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Refresh After Logout Response Status: {refresh_after_logout_response.status_code}")
    print(f"Refresh After Logout Response Body: {refresh_after_logout_response.text}")
    
    if refresh_after_logout_response.status_code == 200:
        print("ERROR: Refresh succeeded after logout (token not properly revoked)")
        return False
    
    print(f"✓ Refresh properly fails after logout (token revoked)")
    
    # 6. Test error cases
    print_step("6. Test logout error cases")
    
    # 6a. Test logout without authentication
    print("\n6a. Test logout without authentication header")
    logout_no_auth_response = requests.post(
        f"{BASE_URL}/auth/logout/",
        json=logout_data,
        headers={"Content-Type": "application/json"}
        # No Authorization header
    )
    
    print(f"Logout without auth Status: {logout_no_auth_response.status_code}")
    if logout_no_auth_response.status_code != 401:
        print(f"WARNING: Expected 401 for unauthenticated logout, got {logout_no_auth_response.status_code}")
    else:
        print(f"✓ Correctly returns 401 for unauthenticated request")
    
    # 6b. Test logout with missing refresh token
    print("\n6b. Test logout with missing refresh token")
    logout_missing_token_response = requests.post(
        f"{BASE_URL}/auth/logout/",
        json={},  # Empty JSON, no refreshToken
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    )
    
    print(f"Logout missing token Status: {logout_missing_token_response.status_code}")
    if logout_missing_token_response.status_code != 400:
        print(f"WARNING: Expected 400 for missing refresh token, got {logout_missing_token_response.status_code}")
    else:
        print(f"✓ Correctly returns 400 for missing refresh token")
    
    # 6c. Test logout with invalid refresh token
    print("\n6c. Test logout with invalid refresh token")
    logout_invalid_token_response = requests.post(
        f"{BASE_URL}/auth/logout/",
        json={"refreshToken": "invalid.jwt.token.here"},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    )
    
    print(f"Logout invalid token Status: {logout_invalid_token_response.status_code}")
    if logout_invalid_token_response.status_code != 401:
        print(f"WARNING: Expected 401 for invalid refresh token, got {logout_invalid_token_response.status_code}")
    else:
        print(f"✓ Correctly returns 401 for invalid refresh token")
    
    # 6d. Test logout with already revoked token (try again)
    print("\n6d. Test logout with already revoked token")
    logout_already_revoked_response = requests.post(
        f"{BASE_URL}/auth/logout/",
        json=logout_data,  # Same token we already revoked
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    )
    
    print(f"Logout already revoked Status: {logout_already_revoked_response.status_code}")
    if logout_already_revoked_response.status_code != 401:
        print(f"WARNING: Expected 401 for already revoked token, got {logout_already_revoked_response.status_code}")
    else:
        print(f"✓ Correctly returns 401 for already revoked token")
    
    print_step("TEST COMPLETE")
    print("All integration tests passed! ✅")
    return True

if __name__ == "__main__":
    print("Starting integration test for Task 4.2 - Logout Endpoint")
    print(f"Testing against: {BASE_URL}")
    
    success = test_logout_endpoint()
    
    if success:
        print("\n" + "="*60)
        print("SUCCESS: Task 4.2 implementation is working correctly!")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("FAILURE: Task 4.2 implementation has issues!")
        print("="*60)
        sys.exit(1)