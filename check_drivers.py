"""Check driver statuses."""
import sys
sys.path.insert(0, 'backend')
from fastapi.testclient import TestClient
from app.main import app
from app.auth import SEED_PASSWORD

client = TestClient(app)
r = client.post('/api/auth/login', json={'email': 'admin@amicor.local', 'password': SEED_PASSWORD})
token = r.json()['access_token']
h = {'Authorization': 'Bearer ' + token}

r = client.get('/api/health-isf/drivers?limit=20', headers=h)
drivers = r.json()
if isinstance(drivers, dict):
    drivers = drivers.get('items', drivers.get('drivers', []))
print('All driver statuses:')
for d in drivers[:15]:
    print('  ' + d['id'][:8] + ' status=' + d['status'] + ' name=' + d.get('name', '-'))
