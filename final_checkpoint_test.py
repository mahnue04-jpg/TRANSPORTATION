"""
CHECKPOINT VERIFICATION: 8-STEP RIDE WORKFLOW
Mode: Evidence Collection (No Code Changes)
Endpoints discovered from: backend/app/modules/health_isf/routes.py
"""
import json
import requests
from datetime import datetime

BASE_URL = 'http://127.0.0.1:8011'
CHECKPOINT_RESULTS = {}

print('='*100)
print('CHECKPOINT VERIFICATION: AMICORE RIDE MANAGEMENT WORKFLOW')
print('='*100)
print()

# ───────────────────────────────────────────────────────────────────────────
# AUTHENTICATION
# ───────────────────────────────────────────────────────────────────────────
print('PHASE 0: AUTHENTICATION')
print('-'*100)

login_payload = {'email': 'admin@amicor.local', 'password': 'Amicor123!'}
resp_auth = requests.post(f'{BASE_URL}/api/auth/login', json=login_payload, timeout=5)
print(f'Endpoint: POST /api/auth/login')
print(f'Status: {resp_auth.status_code}')

if resp_auth.status_code != 200:
    print('ERROR: Authentication failed')
    exit(1)

token = resp_auth.json().get('access_token')
headers = {'Authorization': f'Bearer {token}'}
print(f'✓ Token obtained')
print()

# ───────────────────────────────────────────────────────────────────────────
# PRE-FLIGHT: DISCOVER TEST DATA
# ───────────────────────────────────────────────────────────────────────────
print('PHASE: PREFLIGHT DATA DISCOVERY')
print('-'*100)

# Get existing rides
resp_rides = requests.get(f'{BASE_URL}/api/health-isf/rides', headers=headers, timeout=5)
print(f'Endpoint: GET /api/health-isf/rides')
print(f'Status: {resp_rides.status_code}')

existing_ride = None
if resp_rides.status_code == 200:
    rides = resp_rides.json()
    if rides:
        existing_ride = rides[0]
        print(f'Found {len(rides)} existing rides')
        print(f'Sample: {existing_ride.get("passenger_name")} | ID: {existing_ride.get("id")[:12]}...')
    else:
        print('No rides found in database')

# Get existing providers
resp_providers = requests.get(f'{BASE_URL}/api/health-isf/providers', headers=headers, timeout=5)
print(f'Endpoint: GET /api/health-isf/providers')
print(f'Status: {resp_providers.status_code}')

existing_provider = None
if resp_providers.status_code == 200:
    providers = resp_providers.json()
    if providers:
        existing_provider = providers[0]
        print(f'Found {len(providers)} existing providers')
        print(f'Sample: {existing_provider.get("name")} | ID: {existing_provider.get("id")[:12]}...')
    else:
        print('No providers found in database')

# Get existing drivers
resp_drivers = requests.get(f'{BASE_URL}/api/health-isf/drivers', headers=headers, timeout=5)
print(f'Endpoint: GET /api/health-isf/drivers')
print(f'Status: {resp_drivers.status_code}')

existing_driver = None
if resp_drivers.status_code == 200:
    try:
        drivers = resp_drivers.json()
        if drivers and not isinstance(drivers, dict):
            existing_driver = drivers[0]
            print(f'Found {len(drivers)} existing drivers')
            print(f'Sample: {existing_driver.get("name")} | ID: {existing_driver.get("id")[:12]}...')
    except:
        print('Could not parse drivers response (may have enum errors)')
else:
    print(f'Drivers endpoint error: {resp_drivers.status_code}')

print()
print('='*100)
print('CHECKPOINT WORKFLOW: 8-STEP VERIFICATION')
print('='*100)
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 1: RIDE CREATION
# ───────────────────────────────────────────────────────────────────────────
print('STEP 1: RIDE CREATION')
print('-'*100)

if not existing_provider:
    print('⚠ SKIPPED: No provider available to create ride')
    CHECKPOINT_RESULTS['1_ride_creation'] = 'SKIPPED'
    ride_id = None
else:
    ride_payload = {
        'provider_id': existing_provider['id'],
        'passenger_name': 'Checkpoint Test User',
        'passenger_phone': '555-0123',
        'pickup_address': '100 Main St, Test City',
        'dropoff_address': '200 Park Ave, Test City',
        'estimated_distance_miles': 5.0,
        'service_type': 'medical_transport'
    }
    
    resp = requests.post(f'{BASE_URL}/api/health-isf/rides', json=ride_payload, headers=headers, timeout=5)
    print(f'Endpoint: POST /api/health-isf/rides')
    print(f'Provider ID: {existing_provider["id"][:20]}...')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['1_ride_creation'] = 'PASS' if resp.status_code in [200, 201] else 'FAIL'
    
    if resp.status_code in [200, 201]:
        try:
            ride_data = resp.json()
            ride_id = ride_data.get('id')
            print(f'✓ Created ride: {ride_id[:20]}...')
        except:
            ride_id = None
    else:
        ride_id = existing_ride['id'] if existing_ride else None
        if ride_id:
            print(f'Using existing ride for continuation: {ride_id[:20]}...')

print(f'RESULT: {CHECKPOINT_RESULTS["1_ride_creation"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 2: DRIVER ASSIGNMENT
# ───────────────────────────────────────────────────────────────────────────
print('STEP 2: DRIVER ASSIGNMENT')
print('-'*100)

if not ride_id:
    print('⚠ SKIPPED: No ride available for assignment')
    CHECKPOINT_RESULTS['2_driver_assignment'] = 'SKIPPED'
    driver_id = None
elif not existing_driver:
    print('⚠ SKIPPED: No driver available for assignment')
    CHECKPOINT_RESULTS['2_driver_assignment'] = 'SKIPPED'
    driver_id = None
else:
    driver_id = existing_driver['id']
    assignment_payload = {
        'ride_id': ride_id,
        'driver_id': driver_id
    }
    
    resp = requests.post(f'{BASE_URL}/api/health-isf/dispatch/auto-assign', json=assignment_payload, headers=headers, timeout=5)
    print(f'Endpoint: POST /api/health-isf/dispatch/auto-assign')
    print(f'Ride ID: {ride_id[:20]}...')
    print(f'Driver ID: {driver_id[:20]}...')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['2_driver_assignment'] = 'PASS' if resp.status_code in [200, 201] else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["2_driver_assignment"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 3: DRIVER ACCEPTANCE
# ───────────────────────────────────────────────────────────────────────────
print('STEP 3: DRIVER ACCEPTANCE')
print('-'*100)

if not ride_id or not driver_id:
    print('⚠ SKIPPED: Missing ride or driver')
    CHECKPOINT_RESULTS['3_driver_acceptance'] = 'SKIPPED'
else:
    acceptance_payload = {'ride_id': ride_id}
    resp = requests.post(f'{BASE_URL}/api/health-isf/drivers/{driver_id}/accept-ride', json=acceptance_payload, headers=headers, timeout=5)
    print(f'Endpoint: POST /api/health-isf/drivers/{{driver_id}}/accept-ride')
    print(f'Driver ID: {driver_id[:20]}...')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['3_driver_acceptance'] = 'PASS' if resp.status_code in [200, 201] else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["3_driver_acceptance"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 4: TRIP START (PICKUP COMPLETE)
# ───────────────────────────────────────────────────────────────────────────
print('STEP 4: TRIP START (PICKUP COMPLETE)')
print('-'*100)

if not ride_id or not driver_id:
    print('⚠ SKIPPED: Missing ride or driver')
    CHECKPOINT_RESULTS['4_trip_start'] = 'SKIPPED'
else:
    start_payload = {'ride_id': ride_id}
    resp = requests.post(f'{BASE_URL}/api/health-isf/drivers/{driver_id}/pickup-complete', json=start_payload, headers=headers, timeout=5)
    print(f'Endpoint: POST /api/health-isf/drivers/{{driver_id}}/pickup-complete')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['4_trip_start'] = 'PASS' if resp.status_code in [200, 201] else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["4_trip_start"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 5: TRIP COMPLETION (DROPOFF COMPLETE)
# ───────────────────────────────────────────────────────────────────────────
print('STEP 5: TRIP COMPLETION (DROPOFF COMPLETE)')
print('-'*100)

if not ride_id or not driver_id:
    print('⚠ SKIPPED: Missing ride or driver')
    CHECKPOINT_RESULTS['5_trip_completion'] = 'SKIPPED'
else:
    complete_payload = {'ride_id': ride_id}
    resp = requests.post(f'{BASE_URL}/api/health-isf/drivers/{driver_id}/dropoff-complete', json=complete_payload, headers=headers, timeout=5)
    print(f'Endpoint: POST /api/health-isf/drivers/{{driver_id}}/dropoff-complete')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['5_trip_completion'] = 'PASS' if resp.status_code in [200, 201] else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["5_trip_completion"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 6: RIDE HISTORY
# ───────────────────────────────────────────────────────────────────────────
print('STEP 6: RIDE HISTORY')
print('-'*100)

if not ride_id:
    print('⚠ SKIPPED: No ride available')
    CHECKPOINT_RESULTS['6_ride_history'] = 'SKIPPED'
else:
    resp = requests.get(f'{BASE_URL}/api/health-isf/rides/{ride_id}/history', headers=headers, timeout=5)
    print(f'Endpoint: GET /api/health-isf/rides/{{ride_id}}/history')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['6_ride_history'] = 'PASS' if resp.status_code == 200 else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["6_ride_history"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 7: DRIVER HISTORY
# ───────────────────────────────────────────────────────────────────────────
print('STEP 7: DRIVER HISTORY')
print('-'*100)

if not driver_id:
    print('⚠ SKIPPED: No driver available')
    CHECKPOINT_RESULTS['7_driver_history'] = 'SKIPPED'
else:
    resp = requests.get(f'{BASE_URL}/api/health-isf/drivers/{driver_id}/assigned-rides', headers=headers, timeout=5)
    print(f'Endpoint: GET /api/health-isf/drivers/{{driver_id}}/assigned-rides')
    print(f'Response Status: {resp.status_code}')
    print(f'Response (excerpt): {resp.text[:250]}')
    
    CHECKPOINT_RESULTS['7_driver_history'] = 'PASS' if resp.status_code == 200 else 'FAIL'

print(f'RESULT: {CHECKPOINT_RESULTS["7_driver_history"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# STEP 8: ADMIN HISTORY (LIST ALL RIDES)
# ───────────────────────────────────────────────────────────────────────────
print('STEP 8: ADMIN HISTORY (LIST ALL RIDES)')
print('-'*100)

resp = requests.get(f'{BASE_URL}/api/health-isf/rides', headers=headers, timeout=5)
print(f'Endpoint: GET /api/health-isf/rides')
print(f'Response Status: {resp.status_code}')
print(f'Response (excerpt): {resp.text[:250]}')

CHECKPOINT_RESULTS['8_admin_history'] = 'PASS' if resp.status_code == 200 else 'FAIL'
print(f'RESULT: {CHECKPOINT_RESULTS["8_admin_history"]}')
print()

# ───────────────────────────────────────────────────────────────────────────
# SUMMARY
# ───────────────────────────────────────────────────────────────────────────
print('='*100)
print('CHECKPOINT SUMMARY')
print('='*100)
print()

for step, result in sorted(CHECKPOINT_RESULTS.items()):
    symbol = '✓' if result == 'PASS' else '✗' if result == 'FAIL' else '⚠'
    print(f'{symbol} {step.upper()}: {result}')

print()
passed = sum(1 for v in CHECKPOINT_RESULTS.values() if v == 'PASS')
failed = sum(1 for v in CHECKPOINT_RESULTS.values() if v == 'FAIL')
skipped = sum(1 for v in CHECKPOINT_RESULTS.values() if v == 'SKIPPED')

print(f'TOTAL RESULTS: {passed} PASS | {failed} FAIL | {skipped} SKIPPED')
print(f'WORKFLOW STATUS: {"✓ OPERATIONAL" if failed == 0 and passed > 0 else "✗ IMPAIRED" if failed > 0 else "⚠ INCOMPLETE"}')
print()
