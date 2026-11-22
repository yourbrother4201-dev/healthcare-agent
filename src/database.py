# src/database.py
"""Database access layer.

Every function that reads or writes a user's health data takes a required
integer `user_id` and filters on it. Nothing here returns data across users.
Sensitive text (medication names and dosages, fitness notes) is encrypted at rest.
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from src.crypto import PREFIX, decrypt_text, encrypt_text


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "health.db"

TIMEZONE = ZoneInfo("Asia/Kolkata")


def now_local():
    return datetime.now(TIMEZONE)


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _columns(conn, table):
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def init_db():
    """Create tables if they don't exist yet. user_id is INTEGER everywhere."""
    conn = get_connection()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'patient',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            dosage TEXT,
            time TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dose_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            medication_id INTEGER NOT NULL,
            taken_at TEXT NOT NULL,
            FOREIGN KEY (medication_id) REFERENCES medications (id)
        );

        CREATE TABLE IF NOT EXISTS health_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric_type TEXT NOT NULL,
            value TEXT NOT NULL,
            unit TEXT,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fitness_activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            activity_type TEXT NOT NULL,
            duration_minutes INTEGER,
            steps INTEGER,
            distance_km REAL,
            calories_burned INTEGER,
            sleep_hours REAL,
            notes TEXT,
            recorded_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS health_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_type TEXT NOT NULL,
            target_value REAL NOT NULL,
            unit TEXT NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        );

        -- Rows that could not be attributed to a user are moved here, not
        -- deleted and not reassigned. Reviewed manually.
        CREATE TABLE IF NOT EXISTS quarantined_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_table TEXT NOT NULL,
            source_id INTEGER,
            payload_json TEXT NOT NULL,
            quarantined_at TEXT NOT NULL
        );
        """)
        conn.commit()
    finally:
        conn.close()


def migrate_user_id():
    """Add user_id columns, quarantine unowned rows, and encrypt legacy plain text.

    Rows with no user_id are NOT assigned to any account. They are copied to
    quarantined_rows and removed from the live tables. Plain-text medication and
    note values are encrypted in place. Safe to run on every startup.
    """
    conn = get_connection()
    try:
        for table in ["medications", "health_metrics", "fitness_activities", "health_goals"]:
            if "user_id" not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")

        for table in ["medications", "health_metrics", "fitness_activities", "health_goals"]:
            rows = conn.execute(f"SELECT * FROM {table} WHERE user_id IS NULL").fetchall()
            for row in rows:
                conn.execute(
                    """INSERT INTO quarantined_rows
                       (source_table, source_id, payload_json, quarantined_at)
                       VALUES (?, ?, ?, ?)""",
                    (table, row["id"], json.dumps(dict(row), default=str),
                     now_local().strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (row["id"],))

        # Encrypt legacy plain-text values. encrypt_text skips values already encrypted.
        for row in conn.execute("SELECT id, name, dosage FROM medications").fetchall():
            name, dosage = encrypt_text(row["name"]), encrypt_text(row["dosage"])
            if (name, dosage) != (row["name"], row["dosage"]):
                conn.execute("UPDATE medications SET name = ?, dosage = ? WHERE id = ?",
                             (name, dosage, row["id"]))
        for row in conn.execute(
            "SELECT id, notes FROM fitness_activities WHERE notes IS NOT NULL AND notes != ''"
        ).fetchall():
            notes = encrypt_text(row["notes"])
            if notes != row["notes"]:
                conn.execute("UPDATE fitness_activities SET notes = ? WHERE id = ?",
                             (notes, row["id"]))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------- Medications ----------

def _decrypt_medication(row):
    med = dict(row)
    med["name"] = decrypt_text(med["name"])
    med["dosage"] = decrypt_text(med["dosage"])
    return med


def add_medication(name, dosage, time, user_id):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO medications (name, dosage, time, user_id) VALUES (?, ?, ?, ?)",
            (encrypt_text(name), encrypt_text(dosage), time, int(user_id)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_medications(user_id, active_only=True):
    conn = get_connection()
    try:
        query = "SELECT * FROM medications WHERE user_id = ?"
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY time"
        return [_decrypt_medication(r) for r in conn.execute(query, (int(user_id),)).fetchall()]
    finally:
        conn.close()


def get_medication_for_user(med_id, user_id):
    """Return one medication only if it belongs to this user, else None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM medications WHERE id = ? AND user_id = ? AND active = 1",
            (int(med_id), int(user_id)),
        ).fetchone()
        return _decrypt_medication(row) if row else None
    finally:
        conn.close()


def delete_medication(med_id, user_id):
    """Soft-delete. Returns True only if a row owned by this user was changed."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE medications SET active = 0 WHERE id = ? AND user_id = ?",
            (int(med_id), int(user_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------- Dose log ----------

def log_dose(medication_id, user_id):
    """Log a dose only if the medication belongs to this user.

    Returns True if logged, False if the medication is not theirs.
    """
    if get_medication_for_user(medication_id, user_id) is None:
        return False
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO dose_log (medication_id, taken_at) VALUES (?, ?)",
            (int(medication_id), now_local().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_dose_log(user_id):
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute("""
            SELECT d.id, m.name, m.dosage, d.taken_at
            FROM dose_log d JOIN medications m ON m.id = d.medication_id
            WHERE m.user_id = ?
            ORDER BY d.taken_at DESC
            LIMIT 200
        """, (int(user_id),)).fetchall()]
        for row in rows:
            row["name"] = decrypt_text(row["name"])
            row["dosage"] = decrypt_text(row["dosage"])
        return rows
    finally:
        conn.close()


def get_doses_taken_today(user_id):
    """Set of this user's medication ids already taken today."""
    today = now_local().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT DISTINCT d.medication_id
            FROM dose_log d JOIN medications m ON m.id = d.medication_id
            WHERE m.user_id = ? AND date(d.taken_at) = ?
        """, (int(user_id), today)).fetchall()
        return {r["medication_id"] for r in rows}
    finally:
        conn.close()


# ---------- Health metrics ----------

def add_metric(metric_type, value, unit="", user_id=None):
    if user_id is None:
        raise ValueError("user_id is required to store a health metric.")
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO health_metrics (metric_type, value, unit, recorded_at, user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (metric_type, str(value), unit,
             now_local().strftime("%Y-%m-%d %H:%M:%S"), int(user_id)),
        )
        conn.commit()
    finally:
        conn.close()


def get_metrics(user_id, metric_type=None, limit=200, offset=0):
    """This user's readings only, newest first, paginated."""
    conn = get_connection()
    try:
        query = "SELECT * FROM health_metrics WHERE user_id = ?"
        params = [int(user_id)]
        if metric_type:
            query += " AND metric_type = ?"
            params.append(metric_type)
        query += " ORDER BY recorded_at DESC, id DESC LIMIT ? OFFSET ?"
        params += [min(int(limit), 500), max(int(offset), 0)]
        return [dict(r) for r in conn.execute(query, params).fetchall()]
    finally:
        conn.close()


# ---------- Fitness tracking ----------

def add_fitness_activity(
    activity_type,
    duration_minutes=None,
    steps=None,
    distance_km=None,
    calories_burned=None,
    sleep_hours=None,
    notes="",
    user_id=None,
):
    if user_id is None:
        raise ValueError("user_id is required to store a fitness activity.")
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO fitness_activities (
                user_id, activity_type, duration_minutes, steps, distance_km,
                calories_burned, sleep_hours, notes, recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                activity_type.strip().lower(),
                duration_minutes,
                steps,
                distance_km,
                calories_burned,
                sleep_hours,
                encrypt_text(notes or ""),
                now_local().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_fitness_activities(user_id, limit=50, offset=0):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT * FROM fitness_activities
            WHERE user_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (int(user_id), min(int(limit), 500), max(int(offset), 0)),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["notes"] = decrypt_text(item["notes"])
            result.append(item)
        return result
    finally:
        conn.close()


def get_fitness_summary(user_id):
    """Summary statistics for this user's fitness activities only."""
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT
                COUNT(*) AS total_activities,
                COALESCE(SUM(duration_minutes), 0) AS total_duration_minutes,
                COALESCE(SUM(steps), 0) AS total_steps,
                COALESCE(SUM(distance_km), 0) AS total_distance_km,
                COALESCE(SUM(calories_burned), 0) AS total_calories,
                COALESCE(SUM(sleep_hours), 0) AS total_sleep_hours
            FROM fitness_activities
            WHERE user_id = ?
        """, (int(user_id),)).fetchone()
        return dict(row)
    finally:
        conn.close()


# ---------- Health goals ----------

def add_health_goal(goal_type, target_value, unit, user_id):
    if user_id is None:
        raise ValueError("user_id is required to create a goal.")
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO health_goals
            (goal_type, target_value, unit, created_at, user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                goal_type.strip().lower(),
                target_value,
                unit.strip(),
                now_local().strftime("%Y-%m-%d %H:%M:%S"),
                int(user_id),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_health_goals(user_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM health_goals WHERE active = 1 AND user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_health_goal_progress(user_id):
    conn = get_connection()
    try:
        goals = conn.execute(
            "SELECT * FROM health_goals WHERE active = 1 AND user_id = ? ORDER BY id DESC",
            (int(user_id),),
        ).fetchall()

        today = now_local().strftime("%Y-%m-%d")
        activities = conn.execute(
            """
            SELECT
                COALESCE(SUM(steps), 0) AS total_steps,
                COALESCE(SUM(duration_minutes), 0) AS total_duration,
                COALESCE(SUM(distance_km), 0) AS total_distance,
                COALESCE(SUM(calories_burned), 0) AS total_calories,
                COALESCE(SUM(sleep_hours), 0) AS total_sleep
            FROM fitness_activities
            WHERE user_id = ? AND date(recorded_at) = ?
            """,
            (int(user_id), today),
        ).fetchone()
    finally:
        conn.close()

    totals = {
        "steps": activities["total_steps"],
        "duration": activities["total_duration"],
        "distance": activities["total_distance"],
        "calories": activities["total_calories"],
        "sleep": activities["total_sleep"],
    }

    results = []
    for goal in goals:
        goal_type = goal["goal_type"].strip().lower()
        current = totals.get(goal_type) or 0
        target = goal["target_value"]
        percentage = min(round((current / target) * 100, 1), 100)
        results.append({
            "id": goal["id"],
            "goal_type": goal_type,
            "current_value": current,
            "target_value": target,
            "unit": goal["unit"],
            "progress_percent": percentage,
            "completed": current >= target,
        })
    return results