#!/bin/bash

echo "=== Testing Authentication Flow with Logout ==="
echo ""

# Test 1: Register a new user
echo "1. Registering a new user..."
REGISTER_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/register/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test_logout@example.com", "password": "SecurePass123!", "full_name": "Test Logout User"}')

echo "Register Response: $REGISTER_RESPONSE"
USER_ID=$(echo $REGISTER_RESPONSE | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
ACCESS_TOKEN=$(echo $REGISTER_RESPONSE | grep -o '"accessToken":"[^"]*"' | cut -d'"' -f4)
REFRESH_TOKEN=$(echo $REGISTER_RESPONSE | grep -o '"refreshToken":"[^"]*"' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ] || [ -z "$REFRESH_TOKEN" ]; then
    echo "ERROR: Failed to register user or get tokens"
    exit 1
fi

echo "✓ User registered successfully"
echo "  User ID: $USER_ID"
echo "  Access Token: ${ACCESS_TOKEN:0:20}..."
echo "  Refresh Token: ${REFRESH_TOKEN:0:20}..."
echo ""

# Test 2: Test the refresh endpoint works
echo "2. Testing refresh endpoint with valid token..."
REFRESH_RESPONSE=$(curl -s -X POST http://localhost:8000/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}")

echo "Refresh Response: $REFRESH_RESPONSE"
NEW_ACCESS_TOKEN=$(echo $REFRESH_RESPONSE | grep -o '"accessToken":"[^"]*"' | cut -d'"' -f4)

if [ -n "$NEW_ACCESS_TOKEN" ]; then
    echo "✓ Refresh endpoint works correctly"
    echo "  New Access Token: ${NEW_ACCESS_TOKEN:0:20}..."
else
    echo "✗ Refresh endpoint failed"
fi
echo ""

# Test 3: Test logout endpoint
echo "3. Testing logout endpoint..."
LOGOUT_RESPONSE=$(curl -s -i -X POST http://localhost:8000/auth/logout/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}")

HTTP_STATUS=$(echo "$LOGOUT_RESPONSE" | head -1 | cut -d' ' -f2)
echo "Logout HTTP Status: $HTTP_STATUS"

if [ "$HTTP_STATUS" = "204" ]; then
    echo "✓ Logout successful (204 No Content)"
else
    echo "✗ Logout failed with status: $HTTP_STATUS"
    echo "Response: $LOGOUT_RESPONSE"
fi
echo ""

# Test 4: Verify token is revoked (refresh should fail)
echo "4. Verifying token is revoked (refresh should fail)..."
REFRESH_AFTER_LOGOUT=$(curl -s -X POST http://localhost:8000/auth/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}")

echo "Refresh after logout: $REFRESH_AFTER_LOGOUT"

if echo "$REFRESH_AFTER_LOGOUT" | grep -q "revoked\|invalid\|unauthorized"; then
    echo "✓ Token successfully revoked (refresh fails as expected)"
else
    echo "✗ Token still works after logout - security issue!"
fi
echo ""

# Test 5: Test logout without authentication
echo "5. Testing logout without authentication (should fail)..."
LOGOUT_NO_AUTH=$(curl -s -i -X POST http://localhost:8000/auth/logout/ \
  -H "Content-Type: application/json" \
  -d "{\"refreshToken\": \"$REFRESH_TOKEN\"}")

NO_AUTH_STATUS=$(echo "$LOGOUT_NO_AUTH" | head -1 | cut -d' ' -f2)
echo "Logout without auth HTTP Status: $NO_AUTH_STATUS"

if [ "$NO_AUTH_STATUS" = "401" ]; then
    echo "✓ Logout correctly requires authentication"
else
    echo "✗ Logout should require authentication but got: $NO_AUTH_STATUS"
fi
echo ""

# Test 6: Test logout with missing refresh token
echo "6. Testing logout with missing refresh token (should fail)..."
LOGOUT_NO_TOKEN=$(curl -s -i -X POST http://localhost:8000/auth/logout/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -d "{}")

NO_TOKEN_STATUS=$(echo "$LOGOUT_NO_TOKEN" | head -1 | cut -d' ' -f2)
echo "Logout without token HTTP Status: $NO_TOKEN_STATUS"

if [ "$NO_TOKEN_STATUS" = "400" ]; then
    echo "✓ Logout correctly requires refresh token"
else
    echo "✗ Logout should require refresh token but got: $NO_TOKEN_STATUS"
fi

echo ""
echo "=== Integration Test Complete ==="