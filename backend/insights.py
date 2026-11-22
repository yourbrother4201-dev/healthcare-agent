#backend/insights.py
from backend.database.database import (
    count_rows,
    get_medications,
    get_metrics,
)


def generate_health_insights(user_id):
    """Generate insights from the given user's health data only."""

    medications = get_medications(user_id=user_id, active_only=True)
    counts = count_rows(user_id)
    latest = get_metrics(user_id, limit=1)

    insights = []

    if len(medications) == 0:
        insights.append("No active medications are currently recorded.")
    else:
        insights.append(
            f"You currently have {len(medications)} "
            "active medication(s) recorded."
        )

    if counts["dose_records"] == 0:
        insights.append("No medication doses have been recorded yet.")
    else:
        insights.append(
            f"There are {counts['dose_records']} medication dose "
            "record(s) in your history."
        )

    if not latest:
        insights.append("No health measurements have been recorded yet.")
    else:
        latest_metric = latest[0]
        insights.append(
            f"Your latest recorded health metric is "
            f"{latest_metric['metric_type']}: "
            f"{latest_metric['value']} "
            f"{latest_metric.get('unit') or ''}."
        )

    return {
        "insights": insights,
        "medication_count": len(medications),
        "dose_count": counts["dose_records"],
        "metric_count": counts["health_metric_records"],
    }