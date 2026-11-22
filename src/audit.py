"""Access audit log.

Records every authenticated API request: who (user id), what (method and path),
the response status, when, and the client address. It never stores request
bodies or health values, so the log itself is not sensitive health data.
"""
import logging

from src.database import get_connection, now_local

logger = logging.getLogger("audit")

AUDIT_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    client_ip TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log (user_id, created_at);
"""


def init_audit_log():
    conn = get_connection()
    try:
        conn.executescript(AUDIT_SQL)
        conn.commit()
    finally:
        conn.close()


def log_event(user_id, method, path, status_code, client_ip=None):
    """Write one audit row. A failure here is logged but never breaks the request."""
    try:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO audit_log
                   (user_id, method, path, status_code, client_ip, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (int(user_id), method, path[:200], int(status_code), client_ip,
                 now_local().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to write audit log entry")


def get_audit_log(user_id, limit=100):
    """A user's own access history, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT method, path, status_code, client_ip, created_at
               FROM audit_log WHERE user_id = ?
               ORDER BY id DESC LIMIT ?""",
            (int(user_id), min(int(limit), 500)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()