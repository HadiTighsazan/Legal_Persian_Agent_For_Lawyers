#!/usr/bin/env python3
"""
Test script for the /auth/refresh endpoint.
"""
import json
import requests
import uuid
import sys

def test_refresh_endpoint():
    print("=== Testing POST /auth/refresh endpoint ===\n")
    
    base_url = "http://localhost:8000"
    
    # Test 1: Empty request (should return 400)
    print("1. Testing empty request (should return 400):")
    try:
        response = requests.post(
            f"{base_url}/auth/refresh/",
            json={},
            headers={"Content-Type": "application/json"}
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 2: Invalid token (should return 401)
    print("2. Testing with invalid token (should return 401):")
    try:
        response = requests.post(
            f"{base_url}/auth/refresh/",
            json={"refreshToken": "invalid.jwt.token"},
            headers={"Content-Type": "application/json"}
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 3: Full flow - register, login, then refresh
    print("3. Testing full flow (register → login → refresh):")
    
    # Register a user
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"
    
    print(f"   Registering user: {email}")
    register_response = requests.post(
        f"{base_url}/auth/register/",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User"
        },
        headers={"Content-Type": "application/json"}
    )
    
    if register_response.status_code != 201:
        print(f"   Registration failed: {register_response.status_code}")
        print(f"   Response: {register_response.text}")
        return
    
    register_data = register_response.json()
    print(f"   Registration successful! User ID: {register_data['user']['id']}")
    
    # Login to get tokens
    print(f"   Logging in...")
    login_response = requests.post(
        f"{base_url}/auth/login/",
        json={"email": email, "password": password},
        headers={"Content-Type": "application/json"}
    )
    
    if login_response.status_code != 200:
        print(f"   Login failed: {login_response.status_code}")
        print(f"   Response: {login_response.text}")
        return
    
    login_data = login_response.json()
    refresh_token = login_data['refreshToken']
    access_token = login_data['accessToken']
    print(f"   Login successful! Got refresh token (length: {len(refresh_token)})")
    
    # Now test refresh
    print(f"   Testing refresh endpoint...")
    refresh_response = requests.post(
        f"{base_url}/auth/refresh/",
        json={"refreshToken": refresh_token},
        headers={"Content-Type": "application/json"}
    )
    
    print(f"   Refresh status: {refresh_response.status_code}")
    print(f"   Refresh response: {refresh_response.text}")
    
    if refresh_response.status_code == 200:
        refresh_data = refresh_response.json()
        new_access_token = refresh_data['accessToken']
        print(f"   Success! Got new access token (length: {len(new_access_token)})")
        print(f"   Tokens are different: {access_token != new_access_token}")
    else:
        print(f"   Refresh failed with status: {refresh_response.status_code}")
    
    print("\n" + "="*50 + "\n")
    
    # Test 4: Missing refreshToken field
    print("4. Testing with missing refreshToken field (should return 400):")
    try:
        response = requests.post(
            f"{base_url}/auth/refresh/",
            json={"wrongField": "some_value"},
            headers={"Content-Type": "application/json"}
        )
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")

if __name__ == "__main__":
    test_refresh_endpoint()