# Track B: Smart Health Assistant

This document describes the Track B additions: security, data isolation, encryption, auditing, performance, the modular service layout, and the demo.

## 1. Architecture (modular services)

The backend runs as one FastAPI process, organised into modules with clear boundaries. Each module owns one responsibility and talks to the others through functions, not shared globals.

| Module | Responsibility | Location |
|---|---|---|
| Auth | Registration, login, JWT tokens, one shared `get_current_user` | `backend/main.py`, `backend/auth.py` |
| Health data | Medications, readings, fitness, goals (user-scoped) | `src/database.py`, `backend/main.py` |
| Analytics | Summaries, insights, wellness score, risk estimate | `backend/analytics.py`, `backend/insights.py`, `backend/wellness/*` |
| Notifications | Alerts, caregiver notifications | `backend/wellness/alerts.py`, `backend/wellness/family.py` |
| AI assistant | Chat tools, all scoped to the logged-in user | `backend/agent.py`, `backend/workflow.py` |
| Security | Field encryption, access audit | `src/crypto.py`, `src/audit.py` |

Separate deployable services were not built. Doing so would need inter-service authentication and a shared database layer, which is outside this project's scope. The module boundaries above are where that split would happen.

## 2. Security and data isolation

- Every endpoint requires a Bearer token. One shared dependency (`get_current_user`) handles it, including the wellness routes.
- Every health-data function takes a required `user_id` and filters on it. Nothing returns data across users.
- Medication actions check ownership first. A user cannot log doses for, or remove, another user's medication.
- The AI assistant reads the logged-in user from a request-scoped context variable. Tools refuse to act if no user is logged in.
- Readings without an owner are moved to a `quarantined_rows` table at startup. They are not assigned to anyone.

## 3. Encryption at rest

- Medication names, dosages, and fitness notes are encrypted with Fernet (AES with an HMAC check) using `DATA_ENCRYPTION_KEY` from `.env`.
- Existing plain-text values are encrypted on the first startup after this change.
- If the key is lost, encrypted values cannot be recovered. If the key is wrong, values show as `[unreadable: encryption key mismatch]`.

## 4. Access audit log

- Every authenticated request is recorded in `audit_log`: user, method, path, status code, client address, and time.
- Request bodies and health values are never recorded.
- Users can view their own history at `GET /audit-log`.

## 5. Performance

- Indexes on `user_id` for medications, health goals, metrics, fitness, alerts, and predictions.
- Paginated `GET /health-metrics` and `GET /fitness-activities` (`limit`, `offset`, capped at 500).
- Dose history is capped at 200 rows.

## 6. API documentation

Interactive docs are at `http://127.0.0.1:8000/docs`. Each endpoint group is tagged, and the Authorize button logs in with username and password.

## 7. Running the project

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
python -m pytest backend/tests -q
python scripts/demo_walkthrough.py
```

Required `.env` values:

```text
JWT_SECRET_KEY=...
DATA_ENCRYPTION_KEY=...
GOOGLE_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

## 8. Demo (about 8 to 10 minutes)

`scripts/demo_walkthrough.py` runs these steps against a running server:

1. Create accounts for a patient, a caregiver, and an unrelated user.
2. Add a medication and log a dose.
3. Show adherence and today's schedule.
4. Record readings through the AI assistant.
5. Show alerts.
6. Log fitness activity and create a goal.
7. Show insights, the risk estimate, and the wellness score.
8. Caregiver request, patient approval, and the consented view.
9. Show that an unrelated user sees nothing.
10. Show the access audit log.

## 9. Known limitations and HIPAA

This is a learning project. It applies strong technical controls, but it is not HIPAA-certified.

- **Not certified.** HIPAA compliance also needs policies, staff training, business associate agreements, risk assessments, and a secured hosting environment.
- **Transport security.** The app runs over HTTP locally. Production needs HTTPS.
- **Key management.** Keys are stored in `.env`. Production needs a secrets manager and key rotation.
- **Login protection.** There is no rate limiting on login yet.
- **Token revocation.** Tokens expire after 30 minutes but cannot be revoked early.
- **Synthetic risk model.** The risk estimate is trained on generated data. It is not clinically validated.
- **Medication interactions.** Results are unverified. No drug-interaction database is connected.
- **Sensitive data in the chat.** Messages sent to the AI provider leave the system. Users should not enter identifying details.

Health summaries, insights, alerts and risk estimates are informational only. They are not a medical diagnosis.