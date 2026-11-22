"""Cross-user isolation tests.

Each test creates two users and checks that user B can never read, change, or
log against user A's data, through the database layer and the chatbot tools.

Run from the project root:
    python -m pytest backend/tests/test_user_isolation.py -q
"""
import os
import tempfile
import unittest
from pathlib import Path

# Point the app at a throwaway database before anything imports it.
_TMP = tempfile.mkdtemp()
os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-key-not-for-production")

import src.database as db  # noqa: E402

db.DB_PATH = Path(_TMP) / "test_health.db"

from src import scheduler  # noqa: E402
from backend import agent  # noqa: E402


def _make_user(username):
    conn = db.get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, 'x', 'patient')",
            (username,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


class IsolationTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        db.migrate_user_id()
        from backend.wellness.schema import init_wellness_db
        from backend.wellness.schema_b import init_schema_b
        init_wellness_db()
        init_schema_b()

    def setUp(self):
        self.alice = _make_user(f"alice_{id(self)}")
        self.bob = _make_user(f"bob_{id(self)}")
        self.alice_med = db.add_medication("Metformin", "500mg", "08:00", user_id=self.alice)


class DatabaseIsolationTests(IsolationTestBase):
    def test_medications_are_scoped(self):
        names = [m["name"] for m in db.get_medications(user_id=self.bob)]
        self.assertNotIn("Metformin", names)

    def test_bob_cannot_delete_alices_medication(self):
        self.assertFalse(db.delete_medication(self.alice_med, self.bob))
        self.assertEqual(len(db.get_medications(user_id=self.alice)), 1)

    def test_bob_cannot_log_dose_on_alices_medication(self):
        self.assertFalse(db.log_dose(self.alice_med, self.bob))
        self.assertEqual(db.get_dose_log(user_id=self.alice), [])

    def test_alice_can_log_dose_on_own_medication(self):
        self.assertTrue(db.log_dose(self.alice_med, self.alice))
        self.assertEqual(len(db.get_dose_log(user_id=self.alice)), 1)

    def test_doses_taken_today_is_scoped(self):
        db.log_dose(self.alice_med, self.alice)
        self.assertEqual(db.get_doses_taken_today(self.bob), set())

    def test_metrics_are_scoped(self):
        db.add_metric("heart_rate", "72", "bpm", user_id=self.alice)
        self.assertEqual(db.get_metrics(self.bob), [])
        self.assertEqual(len(db.get_metrics(self.alice)), 1)

    def test_metric_requires_user(self):
        with self.assertRaises(ValueError):
            db.add_metric("heart_rate", "72", "bpm", user_id=None)

    def test_fitness_is_scoped(self):
        db.add_fitness_activity("walk", steps=5000, user_id=self.alice)
        self.assertEqual(db.get_fitness_activities(self.bob), [])
        self.assertEqual(db.get_fitness_summary(self.bob)["total_steps"], 0)
        self.assertEqual(db.get_fitness_summary(self.alice)["total_steps"], 5000)

    def test_fitness_requires_user(self):
        with self.assertRaises(ValueError):
            db.add_fitness_activity("walk", steps=100, user_id=None)

    def test_goals_are_scoped_and_owned(self):
        db.add_health_goal("steps", 8000, "steps", user_id=self.alice)
        self.assertEqual(db.get_health_goals(self.bob), [])
        self.assertEqual(len(db.get_health_goals(self.alice)), 1)

    def test_goal_progress_ignores_other_users_steps(self):
        db.add_fitness_activity("walk", steps=9000, user_id=self.alice)
        db.add_health_goal("steps", 8000, "steps", user_id=self.bob)
        progress = db.get_health_goal_progress(self.bob)
        self.assertEqual(progress[0]["current_value"], 0)

    def test_goal_requires_user(self):
        with self.assertRaises(ValueError):
            db.add_health_goal("steps", 8000, "steps", user_id=None)

    def test_schedule_is_scoped(self):
        schedule = scheduler.get_schedule_status(self.bob)
        self.assertEqual(schedule, [])

    def test_schedule_requires_user(self):
        with self.assertRaises(ValueError):
            scheduler.get_schedule_status(None)


class ChatbotIsolationTests(IsolationTestBase):
    def _as(self, user_id):
        return agent.CURRENT_USER_ID.set(user_id)

    def test_tools_refuse_without_login(self):
        token = self._as(None)
        try:
            self.assertEqual(agent.log_dose_tool.invoke({"name": "Metformin"}), agent.NOT_LOGGED_IN)
            self.assertEqual(agent.remove_medication.invoke({"name": "Metformin"}), agent.NOT_LOGGED_IN)
            self.assertEqual(agent.get_today_schedule.invoke({}), agent.NOT_LOGGED_IN)
        finally:
            agent.CURRENT_USER_ID.reset(token)
        self.assertEqual(len(db.get_medications(user_id=self.alice)), 1)

    def test_bob_cannot_remove_alices_medication_via_chat(self):
        token = self._as(self.bob)
        try:
            result = agent.remove_medication.invoke({"name": "Metformin"})
        finally:
            agent.CURRENT_USER_ID.reset(token)
        self.assertIn("No medication named", result)
        self.assertEqual(len(db.get_medications(user_id=self.alice)), 1)

    def test_bob_cannot_log_dose_for_alice_via_chat(self):
        token = self._as(self.bob)
        try:
            result = agent.log_dose_tool.invoke({"name": "Metformin"})
        finally:
            agent.CURRENT_USER_ID.reset(token)
        self.assertIn("No medication named", result)
        self.assertEqual(db.get_dose_log(user_id=self.alice), [])

    def test_bob_cannot_read_alices_readings_via_chat(self):
        db.add_metric("blood_sugar", "300", "mg/dL", user_id=self.alice)
        token = self._as(self.bob)
        try:
            result = agent.get_recent_readings.invoke({"metric_type": ""})
        finally:
            agent.CURRENT_USER_ID.reset(token)
        self.assertEqual(result, "No readings saved.")

    def test_bob_cannot_see_alices_fitness_via_chat(self):
        db.add_fitness_activity("run", steps=7000, user_id=self.alice)
        token = self._as(self.bob)
        try:
            result = agent.get_fitness_history.invoke({})
        finally:
            agent.CURRENT_USER_ID.reset(token)
        self.assertEqual(result, "No fitness activities have been recorded yet.")


if __name__ == "__main__":
    unittest.main()