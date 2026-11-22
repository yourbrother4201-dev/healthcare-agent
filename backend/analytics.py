#backend/analytics.py
from backend.database.database import (
    count_rows,
    get_medications,
    get_dose_log,
    get_metrics,
)


def get_health_analytics(user_id):
    """Calculate basic health analytics from the given user's stored data."""

    medications = get_medications(user_id=user_id, active_only=True)
    dose_log = get_dose_log(user_id)
    metrics = get_metrics(user_id, limit=5)
    counts = count_rows(user_id)

    return {
        "active_medications": counts["active_medications"],
        "total_doses_recorded": counts["dose_records"],
        "total_health_metrics": counts["health_metric_records"],
        "medications": medications,
        "recent_doses": dose_log[:5],
        "recent_metrics": metrics,
    }