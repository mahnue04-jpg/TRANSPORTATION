#!/usr/bin/env python3
import sys
sys.path.insert(0, 'backend')

from fastapi.testclient import TestClient
from app.main import app
REQUEST_ID = '95578d54-84dc-4c9c-a6d0-0e9ebadc494b'
ORG_ID = 'ca8d0c7c-1fff-4465-99d7-75a1fc51543e'

client = TestClient(app)
login_response = client.post(
    '/api/auth/login',
    json={'email': 'dispatcher@amicor.local', 'password': 'Amicor123!'},
)
login_response.raise_for_status()
dispatcher_token = login_response.json()['access_token']

headers = {'Authorization': f'Bearer {dispatcher_token}'}

driver_create_response = client.post(
    '/api/health-isf/drivers',
    json={
        'name': 'Amicor Phase 2 Driver',
        'phone': '+15550002222',
        'vehicle_type': 'Wheelchair Van',
        'vehicle_plate': 'AMICOR-P2',
    },
    headers=headers,
)
print('CREATE DRIVER', driver_create_response.status_code)
print(driver_create_response.json())
if driver_create_response.status_code == 201:
    driver_id = driver_create_response.json()['id']
else:
    driver_id = '89657d82-214a-4a67-a1eb-18cfb3929e4a'

status_response = client.post(
    f'/api/health-isf/drivers/{driver_id}/set-status',
    json={'status': 'available'},
    headers=headers,
)
print('SET STATUS', status_response.status_code)
print(status_response.json())

approve_response = client.post(
    f'/api/health-isf/dispatcher/customer-requests/{REQUEST_ID}/approve',
    params={'organization_id': ORG_ID},
    headers=headers,
)
print('APPROVE', approve_response.status_code)
print(approve_response.json())

response = client.post(
    f'/api/health-isf/dispatcher/customer-requests/{REQUEST_ID}/assign-driver',
    params={'organization_id': ORG_ID},
    json={'driver_id': driver_id},
    headers=headers,
)

print('STATUS', response.status_code)
print(response.json())
