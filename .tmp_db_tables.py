import sqlite3
conn = sqlite3.connect(r"backend/data/chat.db")
rows = [r[0] for r in conn.execute("select name from sqlite_master where type='table' order by name")]
print(rows)
conn.close()
