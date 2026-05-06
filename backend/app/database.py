import sqlite3
import os

DB_FILENAME = os.path.join(os.path.dirname(__file__), 'chat.db')

def get_connection():
    return sqlite3.connect(DB_FILENAME)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        role TEXT,
        content TEXT
    )
    """)

    conn.commit()
    conn.close()
