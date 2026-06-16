import uuid
import sys
from fastapi.testclient import TestClient
try:
    from app.main import app
    from app.auth import SEED_PASSWORD
except Exception as e:
    print(f'Import Error: {e}')
    sys.exit(1)

client = TestClient(app)
print('Client initialized')

def get_token(email, password):
    try:
        resp = client.post('/api/auth/login', json={'email': email, 'password': password})
        if resp.status_code == 200:
            return resp.json().get('access_token')
    except Exception as e:
        print(f'Login error for {email}: {e}')
    return None

dispatcher_token = get_token('dispatcher@amicor.local', SEED_PASSWORD)
print(f'Dispatcher token: {dispatcher_token[:10] if dispatcher_token else "NONE"}')

staff_email = f'staff_{uuid.uuid4().hex[:6]}@amicor.local'
client.post('/api/auth/register', json={
    'email': staff_email,
    'password': SEED_PASSWORD,
    'full_name': 'Test Staff',
    'organization_id': 1
})
staff_token = get_token(staff_email, SEED_PASSWORD)
print(f'Staff token: {staff_token[:10] if staff_token else "NONE"}')

endpoints = [
    '/api/health-isf/dashboard',
    '/api/health-isf/providers',
    '/api/health-isf/rides',
    '/api/health-isf/intelligence/summary',
    '/api/health-isf/ai-dispatch/snapshot'
]

results = []
errors = []

for ep in endpoints:
    row = {'endpoint': ep}
    for label, token in [('disp', dispatcher_token), ('unauth', None), ('staff', staff_token)]:
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        try:
            resp = client.get(ep, headers=headers)
            row[label] = resp.status_code
            if resp.status_code != 200:
                errors.append(f'{ep} ({label}): {resp.status_code} - {resp.text[:100]}')
        except Exception as e:
            row[label] = 'ERR'
            errors.append(f'{ep} ({label}): Exception - {str(e)}')
    results.append(row)

print('{:<40} | {:<5} | {:<6} | {:<5}'.format('Endpoint', 'Disp', 'Unauth', 'Staff'))
print('-' * 65)
for r in results:
    print('{:<40} | {:<5} | {:<6} | {:<5}'.format(r['endpoint'], r['disp'], r['unauth'], r['staff']))

if errors:
    print('\nNon-200 Details:')
    for err in errors:
        print(err)
