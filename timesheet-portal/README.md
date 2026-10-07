# Odoo Timesheet Portal MVP

Small FastAPI portal for employees to submit Odoo 19 timesheets without receiving direct Odoo access.

## What It Does

- First-run admin setup if no portal users exist.
- Admin can save Odoo URL, database, login email, and password from the UI.
- Admin can create an employee login; the portal creates a matching `hr.employee` in Odoo automatically.
- Employees log in to the portal and submit timesheets to Odoo projects/tasks.
- SQLite stores portal users, sessions, settings, and audit events.

## Run Locally

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn portal_app:app --host 127.0.0.1 --port 8081
```

Open `http://127.0.0.1:8081`.

## Production Notes

Use a reverse proxy such as Nginx/Caddy with HTTPS, then run the app on localhost:

```bash
export PORTAL_DB=/opt/timesheet-portal/timesheet_portal.sqlite3
export COOKIE_SECURE=1
uvicorn portal_app:app --host 127.0.0.1 --port 8081
```

Protect the SQLite database file. It contains local password hashes and the saved Odoo password. For a larger deployment, the next upgrade should move settings/secrets to PostgreSQL plus a secrets manager or OS key store.

The Odoo credential should belong to an internal Odoo user with only the permissions needed for Employees, Projects, Tasks, and Timesheets.
