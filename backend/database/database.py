#backend/database/database.py
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.database import (
    init_db,
    migrate_user_id,
    get_connection,
    get_medications,
    get_dose_log,
    get_metrics,
    get_doses_taken_today,
    add_fitness_activity,
    get_fitness_activities,
    get_fitness_summary,
    add_health_goal,
    get_health_goals,
    get_health_goal_progress,
    add_metric,
)


def count_rows(user_id):
    """Exact counts for one user (not capped by pagination)."""
    conn = get_connection()
    try:
        uid = int(user_id)
        meds = conn.execute(
            "SELECT COUNT(*) FROM medications WHERE user_id = ? AND active = 1", (uid,)
        ).fetchone()[0]
        doses = conn.execute(
            """SELECT COUNT(*) FROM dose_log d
               JOIN medications m ON m.id = d.medication_id
               WHERE m.user_id = ?""",
            (uid,),
        ).fetchone()[0]
        metrics = conn.execute(
            "SELECT COUNT(*) FROM health_metrics WHERE user_id = ?", (uid,)
        ).fetchone()[0]
        return {
            "active_medications": meds,
            "dose_records": doses,
            "health_metric_records": metrics,
        }
    finally:
        conn.close()


def get_health_summary(user_id):
    return count_rows(user_id)