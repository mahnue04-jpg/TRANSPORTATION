"""Quick org/provider diagnostic."""
from app.db.session import SessionLocal
from app.modules.health_isf.models import HealthISFOrganization, HealthISFProvider, HealthISFDriver
from app.modules.health_isf import service as hs
from app.db.models import User

db = SessionLocal()
try:
    orgs = db.query(HealthISFOrganization).all()
    print("ORGS:")
    for o in orgs:
        pc = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == o.id).count()
        dc = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == o.id).count()
        print(f"  {o.code} id={o.id} providers={pc} drivers={dc}")
    canonical = hs._get_or_create_default_org(db)
    db.commit()
    print("CANONICAL:", canonical.code, canonical.id)
    u = db.query(User).filter(User.email == "dispatcher@amicor.local").first()
    if u:
        print("DISPATCHER org_id:", u.organization_id, "match:", str(u.organization_id) == str(canonical.id))
finally:
    db.close()
