import os
import sqlite3

_DEFAULT_DB = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "chat.db")
)
DB_FILENAME = os.getenv("DB_FILENAME", _DEFAULT_DB)
_RUNTIME_MEMORY_CONTEXTS: dict[str, dict[str, object]] = {}


def _clear_runtime_context(user_id: str) -> None:
    """Reset in-memory runtime buckets used by active request/session orchestration."""
    _RUNTIME_MEMORY_CONTEXTS[user_id] = {
        "conversation_history": [],
        "session_cache": {},
        "memory_store": {},
        "frontend_messages": [],
        "workflow_context": {},
        "tool_context": {},
    }


def get_connection():
    return sqlite3.connect(DB_FILENAME)

def init_db():
    os.makedirs(os.path.dirname(DB_FILENAME), exist_ok=True)
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id    TEXT NOT NULL,
            key        TEXT NOT NULL,
            value      TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, key)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_summaries (
            user_id    TEXT PRIMARY KEY,
            summary    TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS email_drafts (
            user_id    TEXT PRIMARY KEY,
            subject    TEXT NOT NULL,
            body       TEXT NOT NULL,
            tone       TEXT NOT NULL,
            status     TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
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

def get_recent_messages(user_id: str, limit: int = 10) -> list: # type: ignore
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
    return [{"role": row[0], "content": row[1]} for row in rows] # type: ignore


def get_chat_history(user_id: str, limit: int = 50) -> list: # type: ignore
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, role, content, timestamp FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    rows = list(reversed(cursor.fetchall()))
    conn.close()
    return [
        {
            "id": row[0],
            "role": row[1],
            "content": row[2],
            "timestamp": row[3],
        }
        for row in rows
    ] # type: ignore


def clear_user_memory(user_id: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("BEGIN")
        cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_preferences WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM memory_summaries WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM email_drafts WHERE user_id = ?", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _clear_runtime_context(user_id)


def save_preference(user_id: str, key: str, value: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO user_preferences (user_id, key, value, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, key, value),
    )
    conn.commit()
    conn.close()


def get_preferences(user_id: str) -> dict: # type: ignore
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT key, value FROM user_preferences WHERE user_id = ? ORDER BY key ASC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows} # type: ignore


def save_memory_summary(user_id: str, summary: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO memory_summaries (user_id, summary, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            summary = excluded.summary,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, summary),
    )
    conn.commit()
    conn.close()


def get_memory_summary(user_id: str) -> str | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT summary FROM memory_summaries WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def save_email_draft(user_id: str, subject: str, body: str, tone: str, status: str) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO email_drafts (user_id, subject, body, tone, status, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            subject = excluded.subject,
            body = excluded.body,
            tone = excluded.tone,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, subject, body, tone, status),
    )
    conn.commit()
    conn.close()


def get_email_draft(user_id: str) -> dict | None: # type: ignore
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT subject, body, tone, status, updated_at FROM email_drafts WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "subject": row[0],
        "body": row[1],
        "tone": row[2],
        "status": row[3],
        "updated_at": row[4],
    } # type: ignore
