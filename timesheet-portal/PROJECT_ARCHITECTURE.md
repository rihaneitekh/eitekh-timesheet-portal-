# Odoo Timesheet Portal - Project Architecture

## Purpose

This project is a lightweight employee timesheet portal for Odoo 19.

Employees log in to this portal, select their Odoo project/task, and submit timesheets. Admin users manage portal users, reset passwords, configure Odoo credentials, and create employee logins. When an admin creates a portal employee, the app also creates the matching `hr.employee` record in Odoo.

## Technology Stack

- Python 3.10
- FastAPI for the web application and API routes
- Uvicorn as the ASGI web server
- SQLite for local portal storage
- Odoo JSON-RPC for communication with Odoo 19
- HTML/CSS/JavaScript generated from the FastAPI app
- No frontend build system is required

## Python Packages

Defined in `requirements.txt`:

- `fastapi`: web framework
- `uvicorn[standard]`: production-capable ASGI server
- `python-multipart`: required for HTML form POST handling
- `pydantic`: request payload validation
- `httpx`: test client support

## Main Files

- `portal_app.py`
  Main FastAPI application. Contains routing, HTML pages, SQLite database logic, authentication, Odoo JSON-RPC calls, caching, and business logic.

- `timesheet_portal.sqlite3`
  SQLite database file. Stores portal users, sessions, settings, and audit logs.

- `requirements.txt`
  Python dependencies required to run the project.

- `.env.example`
  Example environment variables for production deployment.

- `README.md`
  Short setup and run guide.

- `PROJECT_ARCHITECTURE.md`
  This full architecture and operations document.

## Database

Database engine: SQLite

Database file:

```bash
/home/imran/Documents/timesheet_portal.sqlite3
```

Tables:

- `users`
  Stores portal users, password hashes, admin flag, active flag, and linked Odoo employee ID.

- `sessions`
  Stores login session tokens, CSRF tokens, and expiry time.

- `settings`
  Stores Odoo connection settings:
  - Odoo URL
  - Odoo database name
  - Odoo login email
  - Odoo password

- `audit_log`
  Stores important actions like login, password reset, user creation, profile update, and timesheet creation.

Important: the Odoo password is stored in SQLite. Protect the database file in production.

## Authentication

Portal passwords are not stored as plain text.

The app uses:

- PBKDF2-HMAC-SHA256
- Per-password random salt
- 260,000 iterations

Sessions use:

- Secure random session tokens
- HttpOnly cookie
- SameSite=Lax
- Optional secure cookie with `COOKIE_SECURE=1`
- CSRF token for write operations

## Odoo Integration

The app connects to Odoo through JSON-RPC:

```text
https://your-odoo-domain.com/jsonrpc
```

Used Odoo models:

- `hr.employee`
  Create and update employee records.

- `project.project`
  Load timesheet-enabled projects.

- `project.task`
  Load project tasks.

- `account.analytic.line`
  Create and read timesheet lines.

The Odoo credential should be an internal Odoo user with only the required access for Employees, Projects, Tasks, and Timesheets.

## Important Features

Admin features:

- Configure Odoo URL/database/login/password from UI
- Create employee portal login
- Automatically create matching Odoo employee
- Reset any portal user password
- Access admin page

Employee features:

- Login with portal email/password
- Submit one or multiple timesheet lines
- View own timesheets only
- Filter timesheets by date/project
- Paginated timesheet history
- Change own password
- Update own profile
- Profile update syncs to Odoo employee

## Performance Optimizations

The app includes multiple optimizations to prevent loading issues:

- Odoo UID login cache
- Server-side project/task cache
- Browser-side project/task cache
- Short employee profile cache
- Short timesheet page cache
- Timesheet pagination
- Odoo calls moved into FastAPI threadpool
- Odoo API timeout configured by `ODOO_TIMEOUT`
- SQLite indexes on common lookup fields

Default cache settings:

```bash
UID_CACHE_SECONDS=900
BOOTSTRAP_CACHE_SECONDS=300
PROFILE_CACHE_SECONDS=120
TIMESHEET_CACHE_SECONDS=20
ODOO_TIMEOUT=18
```

## Start Project

From this folder:

```bash
cd /home/imran/Documents
.venv/bin/uvicorn portal_app:app --host 0.0.0.0 --port 8081
```

Then open:

```text
http://127.0.0.1:8081
```

## Stop Project

If the server is running in the terminal, press:

```text
Ctrl + C
```

If running in the background, find and stop it:

```bash
ps -ef | grep uvicorn
kill <PID>
```

## Restart Project

Stop first, then start again:

```bash
cd /home/imran/Documents
.venv/bin/uvicorn portal_app:app --host 0.0.0.0 --port 8081
```

## Health Check

Use:

```bash
curl http://127.0.0.1:8081/health
```

Expected response:

```json
{"ok": true, "database": "/home/imran/Documents/timesheet_portal.sqlite3"}
```

## Admin Login

Current admin login:

```text
Email: admin@example.com
Password: Admin@123456
```

Change this password before production use.

## Environment Variables

Common runtime variables:

```bash
HOST=127.0.0.1
PORT=8081
PORTAL_DB=/opt/timesheet-portal/timesheet_portal.sqlite3
COOKIE_SECURE=1
SESSION_SECONDS=43200
ODOO_TIMEOUT=18
```

Optional first-admin variables:

```bash
APP_ADMIN_EMAIL=admin@example.com
APP_ADMIN_PASSWORD=change-this-password
```

Optional Odoo prefill variables:

```bash
ODOO_URL=https://your-company.odoo.com
ODOO_DB=your-database-name
ODOO_LOGIN=admin@example.com
ODOO_PASSWORD=your-odoo-password
```

Odoo settings can also be changed from the Admin UI.

## Production Deployment Notes

Recommended production setup:

- Run app with Uvicorn or Gunicorn/Uvicorn workers
- Bind app to localhost
- Put Nginx or Caddy in front
- Use HTTPS
- Set `COOKIE_SECURE=1`
- Protect the SQLite database file
- Back up the SQLite database regularly
- Use a restricted Odoo internal user

Example production app command:

```bash
cd /opt/timesheet-portal
export PORTAL_DB=/opt/timesheet-portal/timesheet_portal.sqlite3
export COOKIE_SECURE=1
.venv/bin/uvicorn portal_app:app --host 127.0.0.1 --port 8081
```

For 100 employees, SQLite is acceptable for the MVP. If usage grows, move to PostgreSQL.

## Suggested Next Upgrades

- PostgreSQL database
- Proper Alembic migrations
- Email invitation/reset links
- Role and permission screen
- Odoo user creation if needed, not only Odoo employee creation
- Export timesheets to Excel
- Admin view of all employee timesheets
- Background refresh for project/task cache
- Systemd service file for production
- Nginx/Caddy reverse proxy config

