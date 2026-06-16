import json
from fastapi.testclient import TestClient
from backend.app.main import app

c = TestClient(app)

providers = c.get('/api/health-isf/providers').json()
drivers = c.get('/api/health-isf/drivers').json()
provider_id = providers[0]['id']
available = next(d for d in drivers if d['status']=='available')
unavailable = next(d for d in drivers if d['status']!='available')

before = c.get('/api/health-isf/dashboard').json()

payload = { # type: ignore
    'passenger_name': 'Workflow Test Rider',
    'passenger_phone': '646-555-9090',
    'pickup_address': '1 Test Ave, Brooklyn, NY',
    'dropoff_address': '2 Test Blvd, Queens, NY',
    'service_type': 'medical_transport',
    'provider_id': provider_id,
    'notes': 'workflow test'
}
created = c.post('/api/health-isf/rides', json=payload)
ride = created.json()
ride_id = ride['id']

neg_completed = c.patch(f'/api/health-isf/rides/{ride_id}/status', json={'status':'completed'})
neg_unavailable = c.patch(f'/api/health-isf/rides/{ride_id}/assign-driver', json={'driver_id': unavailable['id']})

assign_ok = c.patch(f'/api/health-isf/rides/{ride_id}/assign-driver', json={'driver_id': available['id']})
accepted_ok = c.patch(f'/api/health-isf/rides/{ride_id}/status', json={'status':'accepted'})
in_transit_ok = c.patch(f'/api/health-isf/rides/{ride_id}/status', json={'status':'in_transit'})
completed_ok = c.patch(f'/api/health-isf/rides/{ride_id}/status', json={'status':'completed'})

after = c.get('/api/health-isf/dashboard').json()

print(json.dumps({
    'openapi_has_status_patch': '/api/health-isf/rides/{ride_id}/status' in c.get('/openapi.json').json().get('paths', {}),
    'openapi_has_assign_patch': '/api/health-isf/rides/{ride_id}/assign-driver' in c.get('/openapi.json').json().get('paths', {}),
    'created': {'code': created.status_code, 'ride_id': ride_id, 'initial_status': ride['status']},
    'negative_completed': {'code': neg_completed.status_code, 'detail': neg_completed.json().get('detail')},
    'negative_unavailable': {'code': neg_unavailable.status_code, 'detail': neg_unavailable.json().get('detail')},
    'happy_path': {
      'assign': {'code': assign_ok.status_code, 'status': assign_ok.json().get('status')},
      'accepted': {'code': accepted_ok.status_code, 'status': accepted_ok.json().get('status')},
      'in_transit': {'code': in_transit_ok.status_code, 'status': in_transit_ok.json().get('status')},
      'completed': {'code': completed_ok.status_code, 'status': completed_ok.json().get('status')}
    },
    'dashboard_before': {k: before[k] for k in ['total_rides','pending_rides','active_rides','completed_rides']},
    'dashboard_after': {k: after[k] for k in ['total_rides','pending_rides','active_rides','completed_rides']}
}, indent=2))
