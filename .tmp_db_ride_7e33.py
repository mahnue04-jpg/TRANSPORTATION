import sqlite3
ride_id = "7e332312-b78b-4de2-9050-db60e57a5fb9"
conn = sqlite3.connect(r"backend/data/chat.db")
conn.row_factory = sqlite3.Row
row = conn.execute("select id, passenger_name, status, lifecycle_state, organization_id, provider_id, driver_id, assigned_at, enroute_at, arrived_at, transporting_at, completed_at from health_isf_rides where id = ?", (ride_id,)).fetchone()
print(dict(row) if row else None)
conn.close()
