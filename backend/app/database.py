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
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id   TEXT    NOT NULL,
        role      TEXT    NOT NULL,
        content   TEXT    NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages (user_id, id)")
    conn.commit()
    conn.close()

def save_message(user_id: str, role: str, content: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()
    conn.close()

def get_recent_messages(user_id: str, limit: int = 10) -> list:
    """Return the most recent `limit` messages as [{"role": ..., "content": ...}, ...]"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT role, content FROM (
            SELECT id, role, content FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
        ) ORDER BY id ASC
        """,
        (user_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in rows]
