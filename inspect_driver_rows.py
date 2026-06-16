#!/usr/bin/env python3
import sys
sys.path.insert(0, 'backend')

from sqlalchemy import create_engine, text

engine = create_engine('sqlite:///./backend/pilot_a4_clean.db')
with engine.connect() as conn:
    print('health_isf_drivers columns:')
    cols = conn.execute(text("PRAGMA table_info(health_isf_drivers)")).fetchall()
    for col in cols:
        print(dict(col._mapping))

    print('health_isf_drivers:')
    rows = conn.execute(text("SELECT * FROM health_isf_drivers ORDER BY created_at DESC LIMIT 5")).fetchall()
    for row in rows:
        print(dict(row._mapping))
    print('\nplatform_users matching driver@amicor.local:')
    rows = conn.execute(text("SELECT id, email, role, organization_id, is_active FROM platform_users WHERE lower(email)=lower('driver@amicor.local') LIMIT 5")).fetchall()
    for row in rows:
        print(dict(row._mapping))
