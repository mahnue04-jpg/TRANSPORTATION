import json
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\smoni\OneDrive\New folder\New folder\Amicore_Rebuild\backend\data\chat.db")
TABLES = [
    "health_isf_customer_ride_requests",
    "health_isf_rides",
    "health_isf_dispatch_assignments",
    "health_isf_dispatch_logs",
    "health_isf_ride_status_history",
]

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
out = {}
for table in TABLES:
    cur.execute(f"PRAGMA table_info({table})")
    out[table] = [dict(r) for r in cur.fetchall()]
conn.close()
print(json.dumps(out, indent=2))
