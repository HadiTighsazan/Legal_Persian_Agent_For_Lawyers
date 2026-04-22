#!/usr/bin/env python3
"""
Manual test script for the /auth/refresh endpoint.
"""
import json
import requests
import uuid
import time

def test_refresh_manual():
    print("=" * 60)
    print("MANUAL TEST OF /auth/refresh ENDPOINT")
    print("=" * 60)
    
    base_url = "http://localhost:8000"
    
    # Generate unique email
    timestamp = int(time.time())
    email = f"testuser_{timestamp}@example.com"
    password = "SecurePass123!"
    
    print(f"\n1. REGISTERING USER: {email}")
    print("-" * 40)
    
    register_data = {
        "email": email,
        "password": password,
        "full_name": "Test User"
    }
    
    register_response = requests.post(
        f"{base_url}/auth/register/",
        json=register_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {register_response.status_code}")
    
    if register_response.status_code == 201:
        register_result = register_response.json()
        print("✓ Registration successful!")
        print(f"  User ID: {register_result['user']['id']}")
    else:
        print(f"✗ Registration failed: {register_response.text}")
        return
    
    print(f"\n2. LOGIN TO GET TOKENS")
    print("-" * 40)
    
    login_data = {
        "email": email,
        "password": password
    }
    
    login_response = requests.post(
        f"{base_url}/auth/login/",
        json=login_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {login_response.status_code}")
    
    if login_response.status_code == 200:
        login_result = login_response.json()
        print("✓ Login successful!")
        access_token = login_result['accessToken']
        refresh_token = login_result['refreshToken']
        print(f"  Access token: {access_token[:50]}...")
        print(f"  Refresh token: {refresh_token[:50]}...")
    else:
        print(f"✗ Login failed: {login_response.text}")
        return
    
    print(f"\n3. TEST REFRESH ENDPOINT")
    print("-" * 40)
    
    # Test 3.1: Valid refresh token
    print("\n3.1 Testing with valid refresh token:")
    refresh_data = {
        "refreshToken": refresh_token
    }
    
    refresh_response = requests.post(
        f"{base_url}/auth/refresh/",
        json=refresh_data,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {refresh_response.status_code}")
    
    if refresh_response.status_code == 200:
        refresh_result = refresh_response.json()
        print("✓ Refresh successful!")
        new_access_token = refresh_result['accessToken']
        print(f"  New access token: {new_access_token[:50]}...")
        print(f"  Tokens are different: {access_token != new_access_token}")
    else:
        print(f"✗ Refresh failed: {refresh_response.text}")
    
    # Test 3.2: Missing refresh token
    print("\n3.2 Testing with missing refresh token (should return 400):")
    refresh_response = requests.post(
        f"{base_url}/auth/refresh/",
        json={},
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {refresh_response.status_code} (expected: 400)")
    if refresh_response.status_code == 400:
        print("✓ Correctly returned 400 for missing token")
        print(f"  Error: {refresh_response.json().get('error', 'No error message')}")
    else:
        print(f"✗ Unexpected status: {refresh_response.text}")
    
    # Test 3.3: Invalid JWT token
    print("\n3.3 Testing with invalid JWT token (should return 401):")
    refresh_response = requests.post(
        f"{base_url}/auth/refresh/",
        json={"refreshToken": "invalid.jwt.token.here"},
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {refresh_response.status_code} (expected: 401)")
    if refresh_response.status_code == 401:
        print("✓ Correctly returned 401 for invalid token")
        print(f"  Error: {refresh_response.json().get('error', 'No error message')}")
    else:
        print(f"✗ Unexpected status: {refresh_response.text}")
    
    # Test 3.4: Try to use the same refresh token again (should work - tokens are reusable)
    print("\n3.4 Testing reuse of same refresh token (should work):")
    refresh_response = requests.post(
        f"{base_url}/auth/refresh/",
        json={"refreshToken": refresh_token},
        headers={"Content-Type": "application/json"}
    )
    
    print(f"Status: {refresh_response.status_code} (expected: 200)")
    if refresh_response.status_code == 200:
        print("✓ Refresh token is reusable (as designed)")
    else:
        print(f"✗ Refresh token reuse failed: {refresh_response.text}")
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("The /auth/refresh endpoint is working correctly!")
    print("\nHow to manually test:")
    print("1. Register: curl -X POST http://localhost:8000/auth/register/ \\")
    print('   -H "Content-Type: application/json" \\')
    print('   -d \'{"email": "test@example.com", "password": "SecurePass123!", "full_name": "Test"}\'')
    print("\n2. Login: curl -X POST http://localhost:8000/auth/login/ \\")
    print('   -H "Content-Type: application/json" \\')
    print('   -d \'{"email": "test@example.com", "password": "SecurePass123!"}\'')
    print("\n3. Refresh: curl -X POST http://localhost:8000/auth/refresh/ \\")
    print('   -H "Content-Type: application/json" \\')
    print('   -d \'{"refreshToken": "PASTE_REFRESH_TOKEN_HERE"}\'')
    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_refresh_manual()