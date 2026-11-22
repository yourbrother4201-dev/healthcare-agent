"""End-to-end demo walkthrough for the Smart Health Assistant (about 8-10 minutes).

Run the backend first:
    python -m uvicorn backend.main:app --reload

Then, in a second terminal from the project root:
    python scripts/demo_walkthrough.py

It creates two new accounts, so it never touches existing data:
  - a patient who records medications, readings, fitness and goals
  - a caregiver who requests access, then sees only what the patient shares
It also shows that another user cannot see the patient's data.
"""
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"
PASSWORD = "DemoPass123"


def step(title):
    print(f"\n=== {title} ===")


def show(label, data):
    print(f"{label}: {data}")


def register(username):
    r = requests.post(f"{BASE}/register", json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return r.json()


def login(username):
    r = requests.post(f"{BASE}/login", data={"username": username, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def check(r):
    if r.status_code >= 400:
        print(f"  ! {r.status_code}: {r.text[:200]}")
        return None
    return r.json()


def main():
    try:
        requests.get(f"{BASE}/health", timeout=3).raise_for_status()
    except requests.RequestException:
        sys.exit("The backend is not running. Start it with: python -m uvicorn backend.main:app --reload")

    stamp = str(int(time.time()))[-6:]
    patient_name = f"demo_patient_{stamp}"
    caregiver_name = f"demo_carer_{stamp}"
    stranger_name = f"demo_other_{stamp}"

    step("1. Create accounts")
    patient_id = register(patient_name)["user_id"]
    register(caregiver_name)
    register(stranger_name)
    patient = login(patient_name)
    caregiver = login(caregiver_name)
    stranger = login(stranger_name)
    print(f"Patient: {patient_name}, caregiver: {caregiver_name}, unrelated user: {stranger_name}")

    step("2. Add medications and log a dose")
    med = check(requests.post(f"{BASE}/wellness/medications", headers=patient,
                              json={"name": "Metformin", "dosage": "500mg", "time": "08:00"}))
    show("Added", med)
    if med:
        show("Dose", check(requests.post(f"{BASE}/wellness/medications/{med['id']}/dose",
                                         headers=patient)))

    step("3. Adherence and today's schedule")
    adh = check(requests.get(f"{BASE}/wellness/adherence?days=7", headers=patient))
    show("Adherence (7 days)", adh and adh.get("overall"))
    show("Today", check(requests.get(f"{BASE}/wellness/medications/today", headers=patient)))

    step("4. Record readings (chat assistant or API)")
    for metric, value, unit in [("heart_rate", "72", "bpm"), ("blood_sugar", "300", "mg/dL")]:
        r = requests.post(f"{BASE}/ask", headers=patient,
                          json={"question": f"Log my {metric.replace('_', ' ')} {value} {unit}"})
        print(f"  asked assistant to log {metric}: status {r.status_code}, reply: {r.json()}")
    show("Readings", check(requests.get(f"{BASE}/health-metrics", headers=patient)))

    step("5. Alerts")
    show("Open alerts", check(requests.get(f"{BASE}/wellness/alerts", headers=patient)))

    step("6. Fitness and a goal")
    check(requests.post(f"{BASE}/fitness-activities", headers=patient,
                        json={"activity_type": "walk", "duration_minutes": 35,
                              "steps": 6500, "sleep_hours": 7.5, "notes": "Morning walk"}))
    goal = check(requests.post(f"{BASE}/wellness/goals", headers=patient,
                               json={"title": "Daily steps", "target_value": 8000,
                                     "unit": "steps", "source": "steps"}))
    show("Goal created", goal)
    show("Progress", check(requests.get(f"{BASE}/wellness/goals", headers=patient)))

    step("7. Insights, risk estimate and report")
    show("Wellness score", check(requests.get(f"{BASE}/wellness/overview", headers=patient)))
    show("Risk estimate", check(requests.get(f"{BASE}/wellness/risk", headers=patient)))
    show("Insights", check(requests.get(f"{BASE}/wellness/insights", headers=patient)))
    print(f"Printable report: {BASE}/wellness/report/printable (open in a browser with the token)")

    step("8. Family monitoring with consent")
    invite = check(requests.post(f"{BASE}/wellness/family/invite-code", headers=patient))
    if invite:
        show("Invite code (valid 24 hours)", invite["invite_code"])
        req = check(requests.post(f"{BASE}/wellness/family/join", headers=caregiver,
                                  json={"invite_code": invite["invite_code"],
                                        "relationship": "parent"}))
        show("Caregiver request", req)
        pending = check(requests.get(f"{BASE}/wellness/family", headers=patient))
        link_id = pending["pending_requests"][0]["id"] if pending and pending["pending_requests"] else None
        if link_id:
            check(requests.post(f"{BASE}/wellness/family/{link_id}/respond", headers=patient,
                                json={"accept": True, "share_medications": True,
                                      "share_fitness": True, "share_metrics": False}))
            print("Patient approved and chose to share medications and fitness (not readings).")
            show("Caregiver's view of patient",
                 check(requests.get(f"{BASE}/wellness/family/members/{patient_id}/overview",
                                    headers=caregiver)) and "shown (medications and fitness only)")

    step("9. Privacy check: an unrelated user sees nothing")
    show("Stranger's medications", check(requests.get(f"{BASE}/medications", headers=stranger)))
    show("Stranger's readings", check(requests.get(f"{BASE}/health-metrics", headers=stranger)))
    show("Stranger's dose history", check(requests.get(f"{BASE}/dose-history", headers=stranger)))

    step("10. Access audit log")
    log = check(requests.get(f"{BASE}/audit-log?limit=5", headers=patient))
    if log:
        for entry in log:
            print(f"  {entry['created_at']}  {entry['method']} {entry['path']}  -> {entry['status_code']}")

    print("\nDemo complete. Remember: this is a learning project, not a clinical tool.")


if __name__ == "__main__":
    main()