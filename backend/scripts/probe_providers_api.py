import os
import sys
import httpx

os.environ.setdefault("PYTHONPATH", ".")
BASE = "http://127.0.0.1:8765"
EMAIL = "dispatcher@amicor.local"
PASSWORD = os.getenv("AMICOR_SEED_PASSWORD", "Amicor123!")

try:
    r = httpx.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30.0)
    print("login", r.status_code, r.text[:300])
    if r.status_code != 200:
        sys.exit(1)
    token = r.json()["access_token"]
    org = r.json().get("organization_id")
    pr = httpx.get(
        f"{BASE}/api/health-isf/providers",
        headers={"Authorization": f"Bearer {token}"},
        params={"organization_id": org} if org else None,
        timeout=30.0,
    )
    print("providers", pr.status_code, len(pr.json()) if pr.status_code == 200 else pr.text[:300])
except Exception as exc:
    print("ERROR", exc)
    sys.exit(1)
