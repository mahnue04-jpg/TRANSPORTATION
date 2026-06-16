import requests
import json
from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from fastapi.testclient import TestClient
from app.main import app

# Initialize auth
ensure_auth_schema()
seed_default_users()
client = TestClient(app)

# Login - Updated email to dispatcher@amicor.local as per user script
login_response = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
print(f"Login status: {login_response.status_code}")

if login_response.status_code == 200:
    auth_data = login_response.json()
    token = auth_data['access_token']
    headers = {"Authorization": f"Bearer {token}"}
    
    # Try to fetch rides
    rides_response = client.get("/api/health-isf/rides", headers=headers)
    print(f"Rides endpoint status: {rides_response.status_code}")
    if rides_response.status_code != 200:
        print(f"Rides error: {rides_response.text}")
else:
    print(f"Login error: {login_response.text}")
