#!/usr/bin/env python
"""Get auth token for rider."""
import sys
import json
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from app.main import app
from app.auth import SEED_PASSWORD

client = TestClient(app)

# Try rider login
response = client.post('/api/auth/login', json={
    'email': 'rider@amicor.local',
    'password': SEED_PASSWORD
})

if response.status_code == 200:
    data = response.json()
    token = data.get('access_token')
    print(f"TOKEN={token}")
else:
    print(f"ERROR: {response.status_code} - {response.text}")
    sys.exit(1)
