#!/usr/bin/env python3
import sys
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_access_token

client = TestClient(app)

# Generate token for rider
payload = {
    "sub": "9b412961-32cc-482c-bb8f-4cc7efea61f6",
    "email": "rider@amicor.local",
    "role": "rider",
    "organization_id": "ca8d0c7c-1fff-4465-99d7-75a1fc5154 3e"
}
token = create_access_token(payload)
print(f"TOKEN = {token}")

# Test the endpoint with the token
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

payload_data = {
    "rider_name": "Test Rider",
    "rider_phone": "+15550001111",
    "pickup_address": "Test Pickup",
    "dropoff_address": "Test Dropoff",
    "requested_time": None,
        "ride_type": "healthcare"
}

print("\n=== Testing POST /api/health-isf/customer-requests ===")
print(f"Headers: {headers}")
print(f"Payload: {payload_data}")

response = client.post(
    "/api/health-isf/customer-requests",
    json=payload_data,
    headers=headers
)

print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")
