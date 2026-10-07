import base64
import hashlib
import hmac
import html
import json
import math
import os
import secrets
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PORTAL_DB", ROOT / "timesheet_portal.sqlite3"))
PORT = int(os.environ.get("PORT", "8081"))
HOST = os.environ.get("HOST", "127.0.0.1")
SESSION_COOKIE = "timesheet_session"
SESSION_SECONDS = int(os.environ.get("SESSION_SECONDS", "43200"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
LOGIN_WINDOW_SECONDS = 300
LOGIN_MAX_ATTEMPTS = 10
PBKDF2_ROUNDS = 260_000
EITEKH_LOGO_URL = "https://static.wixstatic.com/media/18b327_738d02ad5b7348c996b7e05b1b45931a%7Emv2.png/v1/fill/w_192%2Ch_192%2Clg_1%2Cusm_0.66_1.00_0.01/18b327_738d02ad5b7348c996b7e05b1b45931a%7Emv2.png"
ODOO_TIMEOUT = int(os.environ.get("ODOO_TIMEOUT", "18"))
UID_CACHE_SECONDS = int(os.environ.get("UID_CACHE_SECONDS", "900"))
BOOTSTRAP_CACHE_SECONDS = int(os.environ.get("BOOTSTRAP_CACHE_SECONDS", "300"))
PROFILE_CACHE_SECONDS = int(os.environ.get("PROFILE_CACHE_SECONDS", "120"))
TIMESHEET_CACHE_SECONDS = int(os.environ.get("TIMESHEET_CACHE_SECONDS", "20"))
DEFAULT_EMPLOYEE_PASSWORD = os.environ.get("DEFAULT_EMPLOYEE_PASSWORD", "admin")
EMPLOYEE_SYNC_SECONDS = max(60, int(os.environ.get("EMPLOYEE_SYNC_SECONDS", "60")))


cache_lock = threading.RLock()
runtime_cache: dict[str, tuple[float, Any]] = {}
login_attempts_lock = threading.Lock()
login_attempts: dict[str, list[float]] = {}


app = FastAPI(title="eiTekh Timesheet Portal", version="1.0.0")


CSS = """
<style>
   :root { --ink:#152838; --muted:#64748b; --line:#dbe5ec; --paper:#ffffff; --soft:#f5f8fb; --teal:#008c99; --teal2:#006f7a; --navy:#16344d; --gold:#d7a441; --danger:#b33b4a; --ok:#087b69; }
  * { box-sizing:border-box; }
   body { margin:0; min-height:100vh; color:var(--ink); background:linear-gradient(180deg,#f7fafc 0,#eef4f7 100%); font-family:"Segoe UI",Arial,sans-serif; }
   header { background:#ffffff; color:var(--ink); padding:16px clamp(16px,4vw,42px); border-bottom:1px solid var(--line); box-shadow:0 4px 18px rgba(20,33,43,.07); }
  .bar { max-width:1120px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:14px; }
  .brand { display:flex; align-items:center; gap:12px; min-width:0; }
  .brand img { width:42px; height:42px; object-fit:contain; border-radius:8px; }
  .brand small { display:block; color:var(--muted); font-weight:700; font-size:12px; margin-top:2px; }
  .nav { display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
  .user-name { color:var(--muted); font-size:14px; font-weight:800; line-height:1; max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  h1 { margin:0; font-size:24px; line-height:1.12; letter-spacing:0; color:var(--navy); }
  h2 { margin:0 0 15px; font-size:19px; color:var(--navy); letter-spacing:0; }
   main { width:min(1180px,calc(100% - 32px)); margin:28px auto 42px; }
   .grid { display:grid; grid-template-columns:minmax(0,1fr) 340px; gap:20px; align-items:start; }
  .grid > * { min-width:0; }
   .panel { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:0 8px 22px rgba(20,33,43,.06); padding:24px; }
   form { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .one-col { grid-template-columns:1fr; }
  label { display:grid; gap:6px; font-size:13px; font-weight:700; color:#34505a; }
  .wide { grid-column:1 / -1; }
   input, select, textarea { width:100%; border:1px solid #cbd6d4; border-radius:7px; background:white; color:var(--ink); font:inherit; font-size:15px; padding:10px 11px; transition:border-color .15s,box-shadow .15s; }
   input:focus, select:focus, textarea:focus { outline:0; border-color:var(--teal); box-shadow:0 0 0 3px rgba(0,140,153,.13); }
  textarea { min-height:94px; resize:vertical; }
   button, .button { justify-self:start; border:0; border-radius:7px; background:var(--teal); color:white; font-weight:800; font-size:15px; padding:10px 16px; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; min-height:40px; transition:background .15s,transform .15s,box-shadow .15s; }
   button:hover, .button:hover { transform:translateY(-1px); box-shadow:0 3px 8px rgba(0,83,92,.16); }
  button:hover, .button:hover { background:var(--teal2); }
  button:disabled { opacity:.62; cursor:not-allowed; }
  .button.secondary { background:#eef7f9; border:1px solid #cce7ec; color:var(--navy); }
  .button.secondary:hover { background:#dff1f4; }
  .tabs { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
  .tabs a { color:var(--navy); font-weight:800; text-decoration:none; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:white; }
  .message { grid-column:1 / -1; min-height:22px; font-weight:700; color:var(--muted); }
  .message.ok { color:var(--ok); }
  .message.err { color:var(--danger); }
  table { width:100%; border-collapse:collapse; font-size:14px; }
   th, td { text-align:left; padding:12px; border-bottom:1px solid var(--line); vertical-align:top; }
  th { color:#34505a; background:var(--soft); }
  .login-shell { width:min(440px,calc(100% - 28px)); margin:42px auto; }
  .metric { display:grid; gap:4px; padding:12px 0; border-top:1px solid var(--line); }
  .metric:first-of-type { border-top:0; }
  .metric strong { color:var(--teal2); font-size:22px; word-break:break-word; }
  .metric span { color:var(--muted); font-size:13px; }
   .stack { display:grid; gap:20px; }
  .hint { color:var(--muted); font-size:13px; line-height:1.45; margin-top:8px; }
  .sheet-panel { grid-column:1 / -1; }
  .sheet-grid { min-width:900px; display:grid; grid-template-columns:minmax(190px,1.5fr) repeat(7,minmax(74px,1fr)) 82px 44px; gap:8px; align-items:center; }
  .line-item { padding:8px 0; border-top:1px solid var(--line); }
  .line-item:first-child { border-top:0; }
  .line-item input, .line-item select { height:42px; padding:8px 10px; }
  .day-input, .line-total { min-width:0; }
  .day-input input, .line-total input { text-align:right; padding:8px; }
  .line-total input { background:var(--soft); font-weight:800; color:var(--navy); }
  .line-remove { justify-self:center; width:40px; min-height:40px; padding:0; justify-content:center; background:#eef7f9; border:1px solid #cce7ec; color:var(--navy); font-size:20px; line-height:1; }
  .line-remove:hover { background:#dff1f4; }
  .toolbar { grid-column:1 / -1; display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
  .toolbar-total { margin-left:auto; color:var(--navy); font-size:18px; }
  .filters { display:grid; grid-template-columns:repeat(4,minmax(140px,1fr)) auto; gap:10px; align-items:end; margin-bottom:14px; }
  .pager { display:flex; justify-content:space-between; gap:10px; align-items:center; margin-top:12px; color:var(--muted); font-weight:700; }
  .table-wrap { overflow-x:auto; }
  .week-bar { grid-column:1 / -1; display:flex; gap:12px; align-items:end; flex-wrap:wrap; margin-bottom:2px; }
  .week-bar label { width:180px; }
  .weekly-sheet { grid-column:1 / -1; overflow-x:auto; display:grid; gap:6px; padding-bottom:4px; }
  #lines { display:grid; min-width:900px; }
  .weekly-header { color:#34505a; font-size:13px; font-weight:800; }
  .weekly-header span { padding:0 10px 6px; white-space:nowrap; }
  .weekly-header span:not(:first-child) { text-align:right; }
  .compact-form { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  .compact-form input { width:170px; }
   .assignment-tool { display:grid; gap:14px; }
   .approval-assignments { display:grid; grid-template-columns:minmax(260px,.8fr) minmax(320px,1.2fr); gap:16px; align-items:start; }
   .approval-project-checks { max-height:300px; }
   .selected-projects { grid-column:1 / -1; display:flex; gap:8px; flex-wrap:wrap; min-height:34px; padding:8px; border:1px solid var(--line); border-radius:7px; background:var(--soft); }
   .selected-projects:empty::before { content:"No projects selected"; color:var(--muted); font-size:13px; font-weight:700; padding:4px; }
   .selected-project { display:inline-flex; align-items:center; gap:7px; border:1px solid #bcdce1; border-radius:999px; background:#e9f7f8; color:var(--navy); padding:5px 7px 5px 10px; font-size:13px; font-weight:800; }
   .selected-project button { min-height:22px; width:22px; padding:0; border-radius:50%; background:transparent; color:var(--navy); font-size:18px; line-height:1; }
   .selected-project button:hover { background:#cdebed; box-shadow:none; transform:none; }
  .assignment-controls { display:grid; grid-template-columns:minmax(240px,340px) minmax(240px,1fr) minmax(110px,130px) auto auto; gap:10px; align-items:end; }
  .assignment-meta { display:flex; gap:12px; align-items:center; flex-wrap:wrap; color:var(--muted); font-size:13px; font-weight:800; }
  .project-checks { display:grid; gap:6px; max-height:380px; overflow:auto; padding:8px; border:1px solid var(--line); border-radius:8px; background:var(--soft); }
  .check-row { display:grid; grid-template-columns:24px minmax(0,1fr); align-items:center; gap:8px; padding:9px 10px; border:1px solid #e0e8ed; border-radius:6px; background:white; font-weight:700; color:var(--ink); }
  .check-row input { width:auto; }
  .check-row span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .empty-state { padding:18px; color:var(--muted); font-weight:700; text-align:center; }
  .assignment-pager { display:flex; justify-content:space-between; gap:10px; align-items:center; color:var(--muted); font-weight:800; }
  .assignment-pager-actions { display:flex; gap:8px; align-items:center; }
  .user-table-controls { display:flex; justify-content:space-between; gap:12px; align-items:end; flex-wrap:wrap; margin-bottom:12px; }
  .user-table-controls label { width:130px; }
  .user-table-meta { color:var(--muted); font-weight:800; }
  .user-management { display:grid; gap:18px; }
  .user-create-form { grid-template-columns:repeat(4,minmax(150px,1fr)) auto; align-items:end; padding:14px; border:1px solid var(--line); border-radius:8px; background:var(--soft); }
  .user-list-head { display:flex; justify-content:space-between; gap:12px; align-items:end; flex-wrap:wrap; }
  .user-list-tools { display:grid; grid-template-columns:minmax(260px,360px) 130px; gap:10px; align-items:end; }
  .row-actions { display:flex; gap:8px; flex-wrap:wrap; }
  .row-actions button { min-height:34px; padding:7px 10px; font-size:13px; }
  .edit-cell input, .edit-cell select { min-width:120px; padding:8px; font-size:14px; }
  .edit-cell.description input { min-width:180px; }
   @media (max-width:860px) { .grid { grid-template-columns:1fr; } form { grid-template-columns:1fr; } .bar { align-items:flex-start; flex-direction:column; } .nav { justify-content:flex-start; } .wide { grid-column:auto; } .approval-assignments { grid-template-columns:1fr; } }
  @media (max-width:1180px) { .filters { grid-template-columns:1fr 1fr; } .assignment-controls { grid-template-columns:1fr 1fr; } }
  @media (max-width:1050px) { .user-create-form { grid-template-columns:1fr 1fr; } }
  @media (max-width:720px) { .assignment-controls { grid-template-columns:1fr; } }
  @media (max-width:640px) { .filters { grid-template-columns:1fr; } .toolbar-total { width:100%; margin-left:0; } .user-create-form, .user-list-tools { grid-template-columns:1fr; } .user-table-controls label { width:100%; } }
</style>
"""


class TimesheetPayload(BaseModel):
    project_id: int
    task_id: int | None = None
    date: str
    unit_amount: float
    name: str = "Weekly timesheet"


class TimesheetBatchPayload(BaseModel):
    lines: list[TimesheetPayload]


class TimesheetUpdatePayload(BaseModel):
    project_id: int
    date: str
    unit_amount: float
    name: str = "Weekly timesheet"


class ProjectAssignmentPayload(BaseModel):
    user_id: int
    project_ids: list[int]


class ApprovalAssignmentPayload(BaseModel):
    user_id: int
    project_ids: list[int]


class ApprovalDecisionPayload(BaseModel):
    note: str = ""


class BulkUserActionPayload(BaseModel):
    user_ids: list[int]
    action: str


class EmployeeManagerPayload(BaseModel):
    user_id: int
    manager_user_id: int | None = None


class ManagerEmployeesPayload(BaseModel):
    manager_user_id: int
    employee_user_ids: list[int]


def now() -> int:
    return int(time.time())


def conn() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"pragma table_info({table})")}


def cache_get(key: str) -> Any | None:
    with cache_lock:
        item = runtime_cache.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            runtime_cache.pop(key, None)
            return None
        return value


def cache_set(key: str, value: Any, ttl: int) -> Any:
    with cache_lock:
        runtime_cache[key] = (time.monotonic() + ttl, value)
    return value


def cache_delete_prefix(prefix: str) -> None:
    with cache_lock:
        for key in list(runtime_cache):
            if key.startswith(prefix):
                runtime_cache.pop(key, None)


def login_allowed(request: Request) -> bool:
    """Rate-limit password guessing without trusting spoofable forwarded headers."""
    client_ip = request.client.host if request.client else "unknown"
    current = time.monotonic()
    with login_attempts_lock:
        attempts = [item for item in login_attempts.get(client_ip, []) if current - item < LOGIN_WINDOW_SECONDS]
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            login_attempts[client_ip] = attempts
            return False
        attempts.append(current)
        login_attempts[client_ip] = attempts
        return True


def clear_login_attempts(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    with login_attempts_lock:
        login_attempts.pop(client_ip, None)


def settings_signature(cfg: dict[str, str] | None = None) -> str:
    cfg = cfg or settings()
    raw = "|".join([cfg.get("odoo_url", ""), cfg.get("odoo_db", ""), cfg.get("odoo_login", ""), cfg.get("odoo_password", "")])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def migrate_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with conn() as db:
        db.executescript(
            """
            create table if not exists users (
              id integer primary key autoincrement,
              username text not null unique,
              password_hash text not null,
              display_name text not null,
              is_admin integer not null default 0,
              odoo_employee_id integer,
              active integer not null default 1,
              created_at integer not null
            );
            create table if not exists sessions (
              token text primary key,
              user_id integer not null references users(id),
              csrf_token text not null,
              expires_at integer not null
            );
            create table if not exists settings (
              key text primary key,
              value text not null,
              updated_at integer not null
            );
            create table if not exists audit_log (
              id integer primary key autoincrement,
              actor_user_id integer,
              action text not null,
              details text not null default '{}',
              created_at integer not null
            );
            create table if not exists user_projects (
              user_id integer not null references users(id) on delete cascade,
              project_id integer not null,
              primary key (user_id, project_id)
            );
            create table if not exists project_managers (
              project_id integer primary key,
              manager_user_id integer not null references users(id) on delete cascade,
              assigned_at integer not null
            );
            create table if not exists project_approvers (
              project_id integer not null,
              user_id integer not null references users(id) on delete cascade,
              assigned_at integer not null,
              primary key (project_id,user_id)
            );
            create table if not exists employee_managers (
              user_id integer primary key references users(id) on delete cascade,
              manager_user_id integer not null references users(id) on delete cascade,
              assigned_at integer not null
            );
            create table if not exists timesheet_approvals (
              id integer primary key autoincrement,
              submitter_user_id integer not null references users(id),
              manager_user_id integer not null references users(id),
              project_id integer not null,
              task_id integer,
              work_date text not null,
              unit_amount real not null,
              description text not null,
              status text not null default 'pending',
              submitted_at integer not null,
              decided_at integer,
              decided_by integer references users(id),
              decision_note text not null default '',
              odoo_line_id integer
            );
            create table if not exists timesheet_approval_approvers (
              approval_id integer not null references timesheet_approvals(id) on delete cascade,
              user_id integer not null references users(id) on delete cascade,
              primary key (approval_id,user_id)
            );
            create index if not exists idx_sessions_user_expires on sessions(user_id, expires_at);
            create index if not exists idx_sessions_expires on sessions(expires_at);
            create index if not exists idx_users_active_admin on users(active, is_admin);
            create index if not exists idx_user_projects_project on user_projects(project_id);
            create index if not exists idx_project_managers_manager on project_managers(manager_user_id);
            create index if not exists idx_project_approvers_user on project_approvers(user_id,project_id);
            create index if not exists idx_employee_managers_manager on employee_managers(manager_user_id,user_id);
            create index if not exists idx_timesheet_approvals_manager_status on timesheet_approvals(manager_user_id,status,submitted_at);
            create index if not exists idx_timesheet_approval_approvers_user on timesheet_approval_approvers(user_id,approval_id);
            """
        )
        session_cols = columns(db, "sessions")
        if "csrf_token" not in session_cols:
            db.execute("alter table sessions add column csrf_token text not null default ''")
            db.execute("update sessions set csrf_token=? where csrf_token=''", (secrets.token_urlsafe(24),))
        db.execute("insert or ignore into project_approvers (project_id,user_id,assigned_at) select project_id,manager_user_id,assigned_at from project_managers")
        db.execute("insert or ignore into timesheet_approval_approvers (approval_id,user_id) select id,manager_user_id from timesheet_approvals")

        defaults = {
            "odoo_url": os.environ.get("ODOO_URL", "").rstrip("/"),
            "odoo_db": os.environ.get("ODOO_DB", ""),
            "odoo_login": os.environ.get("ODOO_LOGIN", ""),
            "odoo_password": os.environ.get("ODOO_PASSWORD", ""),
        }
        for key, value in defaults.items():
            if value and not db.execute("select 1 from settings where key=?", (key,)).fetchone():
                set_setting(db, key, value)

        admin_password = os.environ.get("APP_ADMIN_PASSWORD", "")
        admin_email = os.environ.get("APP_ADMIN_EMAIL", "admin@example.com").strip()
        if admin_password and not db.execute("select 1 from users where lower(username)=lower(?)", (admin_email,)).fetchone():
            db.execute(
                """
                insert into users (username,password_hash,display_name,is_admin,active,created_at)
                values (?,?,?,?,1,?)
                """,
                (admin_email, password_hash(admin_password), "Administrator", 1, now()),
            )


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()


def password_ok(password: str, stored: str) -> bool:
    try:
        salt64, digest64 = stored.split(":", 1)
        salt = base64.b64decode(salt64)
        expected = base64.b64decode(digest64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def set_setting(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute(
        """
        insert into settings (key,value,updated_at) values (?,?,?)
        on conflict(key) do update set value=excluded.value, updated_at=excluded.updated_at
        """,
        (key, value, now()),
    )


def settings() -> dict[str, str]:
    with conn() as db:
        rows = db.execute("select key,value from settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def public_settings() -> dict[str, str]:
    cfg = settings()
    return {
        "odoo_url": cfg.get("odoo_url", ""),
        "odoo_db": cfg.get("odoo_db", ""),
        "odoo_login": cfg.get("odoo_login", ""),
        "odoo_password_set": "Yes" if cfg.get("odoo_password") else "No",
    }


def reset_connection_data(keep_admin_user_id: int) -> None:
    """Clear local data tied to an Odoo database while preserving the active admin."""
    with conn() as db:
        db.execute("delete from timesheet_approval_approvers")
        db.execute("delete from timesheet_approvals")
        db.execute("delete from user_projects")
        db.execute("delete from project_approvers")
        db.execute("delete from employee_managers")
        db.execute("delete from project_managers")
        db.execute("delete from sessions where user_id<>?", (int(keep_admin_user_id),))
        db.execute("delete from users where is_admin=0")
        db.execute("delete from audit_log")
    cache_delete_prefix("")


def audit(actor_user_id: int | None, action: str, details: dict[str, Any] | None = None) -> None:
    with conn() as db:
        db.execute(
            "insert into audit_log (actor_user_id,action,details,created_at) values (?,?,?,?)",
            (actor_user_id, action, json.dumps(details or {}), now()),
        )


def users_count() -> int:
    with conn() as db:
        return int(db.execute("select count(*) from users").fetchone()[0])


def create_session(user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with conn() as db:
        db.execute(
            "insert into sessions (token,user_id,csrf_token,expires_at) values (?,?,?,?)",
            (token, user_id, csrf, now() + SESSION_SECONDS),
        )
    return token, csrf


def session_from_request(request: Request) -> sqlite3.Row | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        return None
    with conn() as db:
        return db.execute(
            """
            select s.token,s.csrf_token,u.* from sessions s
            join users u on u.id=s.user_id
            where s.token=? and s.expires_at>? and u.active=1
            """,
            (token, now()),
        ).fetchone()


def current_user(request: Request) -> dict[str, Any] | None:
    row = session_from_request(request)
    return dict(row) if row else None


def require_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def verify_csrf(request: Request, submitted: str) -> None:
    row = session_from_request(request)
    if not row or not hmac.compare_digest(row["csrf_token"], submitted):
        raise HTTPException(status_code=403, detail="Security token expired. Please reload and try again.")


def delete_session(token: str) -> None:
    if token:
        with conn() as db:
            db.execute("delete from sessions where token=?", (token,))


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with conn() as db:
        row = db.execute("select * from users where lower(username)=lower(?) and active=1", (username.strip(),)).fetchone()
    if row and password_ok(password, row["password_hash"]):
        return dict(row)
    return None


def app_users() -> list[dict[str, Any]]:
    with conn() as db:
        rows = db.execute(
            """
            select id,username,display_name,is_admin,odoo_employee_id,active,created_at
            from users order by is_admin desc,odoo_employee_id asc,created_at asc,id asc
            """
        ).fetchall()
    return [dict(row) for row in rows]


def assignable_users() -> list[dict[str, Any]]:
    return [user for user in app_users() if not user["is_admin"] and user["active"]]


def portal_user(user_id: int) -> dict[str, Any] | None:
    with conn() as db:
        row = db.execute("select * from users where id=?", (int(user_id),)).fetchone()
    return dict(row) if row else None


def assigned_project_ids(user_id: int) -> set[int]:
    with conn() as db:
        rows = db.execute("select project_id from user_projects where user_id=?", (int(user_id),)).fetchall()
    return {int(row["project_id"]) for row in rows}


def project_assignments() -> dict[str, list[int]]:
    with conn() as db:
        rows = db.execute("select user_id,project_id from user_projects order by user_id,project_id").fetchall()
    output: dict[str, list[int]] = {}
    for row in rows:
        output.setdefault(str(row["user_id"]), []).append(int(row["project_id"]))
    return output


def project_approvers() -> dict[str, list[int]]:
    with conn() as db:
        rows = db.execute("select project_id,user_id from project_approvers order by project_id,user_id").fetchall()
    output: dict[str, list[int]] = {}
    for row in rows:
        output.setdefault(str(row["project_id"]), []).append(int(row["user_id"]))
    return output


def employee_managers() -> dict[str, int]:
    with conn() as db:
        rows = db.execute("select user_id,manager_user_id from employee_managers").fetchall()
    return {str(row["user_id"]): int(row["manager_user_id"]) for row in rows}


def set_employee_manager(actor: dict[str, Any], payload: EmployeeManagerPayload) -> dict[str, Any]:
    employee = portal_user(payload.user_id)
    if not employee or employee.get("is_admin") or not employee.get("active"):
        raise ValueError("Select an active employee portal user.")
    with conn() as db:
        if payload.manager_user_id is None:
            db.execute("delete from employee_managers where user_id=?", (int(payload.user_id),))
            manager_id = None
        else:
            manager = db.execute("select id from users where id=? and active=1", (int(payload.manager_user_id),)).fetchone()
            if not manager or int(payload.manager_user_id) == int(payload.user_id):
                raise ValueError("Select another active portal user as the manager.")
            manager_id = int(payload.manager_user_id)
            db.execute("insert into employee_managers (user_id,manager_user_id,assigned_at) values (?,?,?) on conflict(user_id) do update set manager_user_id=excluded.manager_user_id,assigned_at=excluded.assigned_at", (int(payload.user_id), manager_id, now()))
    audit(actor["id"], "admin.employee_manager.update", {"employee_user_id": int(payload.user_id), "manager_user_id": manager_id})
    return {"user_id": int(payload.user_id), "manager_user_id": manager_id}


def set_manager_employees(actor: dict[str, Any], payload: ManagerEmployeesPayload) -> dict[str, Any]:
    manager = portal_user(payload.manager_user_id)
    if not manager or not manager.get("active"):
        raise ValueError("Select an active portal user as the manager.")
    employee_ids = sorted({int(user_id) for user_id in payload.employee_user_ids if int(user_id) != int(payload.manager_user_id)})
    with conn() as db:
        if employee_ids:
            placeholders = ",".join("?" for _ in employee_ids)
            valid = db.execute(f"select id from users where id in ({placeholders}) and is_admin=0 and active=1", employee_ids).fetchall()
            if len(valid) != len(employee_ids):
                raise ValueError("Selected employees must be active employee portal users.")
        db.execute("delete from employee_managers where manager_user_id=?", (int(payload.manager_user_id),))
        db.executemany("insert into employee_managers (user_id,manager_user_id,assigned_at) values (?,?,?) on conflict(user_id) do update set manager_user_id=excluded.manager_user_id,assigned_at=excluded.assigned_at", [(employee_id, int(payload.manager_user_id), now()) for employee_id in employee_ids])
    audit(actor["id"], "admin.manager_employees.update", {"manager_user_id": int(payload.manager_user_id), "employee_user_ids": employee_ids})
    return {"manager_user_id": int(payload.manager_user_id), "employee_user_ids": employee_ids}


def has_approval_responsibility(user_id: int) -> bool:
    with conn() as db:
        return bool(db.execute("select 1 from project_approvers where user_id=? union select 1 from employee_managers where manager_user_id=? limit 1", (int(user_id), int(user_id))).fetchone())


def manager_project_ids(user_id: int) -> set[int]:
    with conn() as db:
        rows = db.execute("select project_id from project_approvers where user_id=?", (int(user_id),)).fetchall()
    return {int(row["project_id"]) for row in rows}


def set_approval_assignments(actor: dict[str, Any], payload: ApprovalAssignmentPayload) -> dict[str, Any]:
    approver = portal_user(payload.user_id)
    if not approver or not approver.get("active"):
        raise ValueError("Select an active portal user as the approver.")
    available_ids = {int(project["id"]) for project in bootstrap_data()["projects"]}
    project_ids = sorted({int(project_id) for project_id in payload.project_ids if int(project_id) in available_ids})
    with conn() as db:
        db.execute("delete from project_approvers where user_id=?", (int(payload.user_id),))
        db.executemany("insert into project_approvers (project_id,user_id,assigned_at) values (?,?,?)", [(project_id, int(payload.user_id), now()) for project_id in project_ids])
    audit(actor["id"], "admin.approval_assignments.update", {"approver_user_id": int(payload.user_id), "project_ids": project_ids})
    return {"ok": True, "user_id": int(payload.user_id), "project_ids": project_ids}


def set_project_assignments(actor: dict[str, Any], payload: ProjectAssignmentPayload) -> dict[str, Any]:
    target = portal_user(payload.user_id)
    if not target or target.get("is_admin") or not target.get("active"):
        raise ValueError("Select an active employee user.")
    available_ids = {int(project["id"]) for project in bootstrap_data()["projects"]}
    project_ids = sorted({int(project_id) for project_id in payload.project_ids if int(project_id) in available_ids})
    with conn() as db:
        db.execute("delete from user_projects where user_id=?", (int(payload.user_id),))
        db.executemany(
            "insert into user_projects (user_id,project_id) values (?,?)",
            [(int(payload.user_id), project_id) for project_id in project_ids],
        )
    cache_delete_prefix("bootstrap:")
    audit(actor["id"], "admin.project_assignments.update", {"target_user_id": payload.user_id, "project_ids": project_ids})
    return {"ok": True, "user_id": int(payload.user_id), "project_ids": project_ids}


def set_user_password(user_id: int, password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    with conn() as db:
        result = db.execute("update users set password_hash=? where id=?", (password_hash(password), int(user_id)))
        if result.rowcount != 1:
            raise ValueError("Portal user not found.")


def set_user_active(actor: dict[str, Any], user_id: int, active: bool) -> dict[str, Any]:
    target = portal_user(user_id)
    if not target:
        raise ValueError("Portal user not found.")
    if int(target["id"]) == int(actor["id"]) and not active:
        raise ValueError("You cannot deactivate your own account.")
    with conn() as db:
        result = db.execute("update users set active=? where id=?", (1 if active else 0, int(user_id)))
        if result.rowcount != 1:
            raise ValueError("Portal user not found.")
        if not active:
            db.execute("delete from sessions where user_id=?", (int(user_id),))
    audit(actor["id"], "admin.user.active.update", {"target_user_id": int(user_id), "active": active})
    return {"id": int(user_id), "active": active, "username": target["username"]}


def bulk_manage_portal_users(actor: dict[str, Any], payload: BulkUserActionPayload) -> dict[str, Any]:
    action = payload.action.strip().lower()
    if action not in {"archive", "delete"}:
        raise ValueError("Choose archive or delete.")
    user_ids = sorted({int(user_id) for user_id in payload.user_ids})
    if not user_ids:
        raise ValueError("Select at least one portal user.")
    if int(actor["id"]) in user_ids:
        raise ValueError("You cannot archive or delete your own admin account.")
    placeholders = ",".join("?" for _ in user_ids)
    with conn() as db:
        rows = db.execute(f"select id,is_admin,odoo_employee_id from users where id in ({placeholders})", user_ids).fetchall()
    if len(rows) != len(user_ids) or any(row["is_admin"] or not row["odoo_employee_id"] for row in rows):
        raise ValueError("Only employee portal accounts linked to Odoo can be selected.")
    employee_ids = [int(row["odoo_employee_id"]) for row in rows]
    if action == "archive":
        execute("hr.employee", "write", employee_ids, {"active": False})
        with conn() as db:
            db.execute(f"update users set active=0 where id in ({placeholders})", user_ids)
            db.execute(f"delete from sessions where user_id in ({placeholders})", user_ids)
            db.execute(f"update timesheet_approvals set status='rejected',decided_at=?,decision_note='Employee archived.' where submitter_user_id in ({placeholders}) and status='pending'", [now(), *user_ids])
    else:
        execute("hr.employee", "unlink", employee_ids)
        with conn() as db:
            db.execute(f"update timesheet_approvals set status='rejected',decided_at=?,decision_note='Employee deleted.' where submitter_user_id in ({placeholders}) and status='pending'", [now(), *user_ids])
            db.execute(f"delete from timesheet_approval_approvers where user_id in ({placeholders})", user_ids)
            db.execute(f"delete from sessions where user_id in ({placeholders})", user_ids)
            db.execute(f"delete from user_projects where user_id in ({placeholders})", user_ids)
            db.execute(f"delete from project_approvers where user_id in ({placeholders})", user_ids)
            db.execute(f"delete from employee_managers where user_id in ({placeholders}) or manager_user_id in ({placeholders})", [*user_ids, *user_ids])
            db.execute(f"delete from project_managers where manager_user_id in ({placeholders})", user_ids)
            db.execute(f"delete from users where id in ({placeholders})", user_ids)
    cache_delete_prefix("employee_profile:")
    cache_delete_prefix("timesheets:")
    audit(actor["id"], f"users.bulk_{action}", {"user_ids": user_ids, "odoo_employee_ids": employee_ids})
    return {"action": action, "count": len(user_ids)}


def rpc(service: str, method: str, args: list[Any]) -> Any:
    cfg = settings()
    url = cfg.get("odoo_url", "").rstrip("/")
    if not all([url, cfg.get("odoo_db"), cfg.get("odoo_login"), cfg.get("odoo_password")]):
        raise RuntimeError("Configure Odoo URL, database, email, and password in Admin Settings first.")
    payload = {"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}}
    req = urllib.request.Request(
        url + "/jsonrpc",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=ODOO_TIMEOUT) as resp:
        body = json.loads(resp.read().decode())
    if body.get("error"):
        data = body["error"].get("data") or {}
        raise RuntimeError(data.get("message") or body["error"].get("message") or "Odoo API error")
    return body.get("result")


def odoo_uid() -> int:
    cfg = settings()
    cache_key = f"odoo_uid:{settings_signature(cfg)}"
    cached = cache_get(cache_key)
    if cached is not None:
        return int(cached)
    uid = rpc("common", "login", [cfg.get("odoo_db"), cfg.get("odoo_login"), cfg.get("odoo_password")])
    if not uid:
        raise RuntimeError("Odoo login failed. Check Admin Settings.")
    return int(cache_set(cache_key, int(uid), UID_CACHE_SECONDS))


def execute(model: str, method: str, *args: Any, **kwargs: Any) -> Any:
    cfg = settings()
    return rpc("object", "execute_kw", [cfg.get("odoo_db"), odoo_uid(), cfg.get("odoo_password"), model, method, list(args), kwargs])


def odoo_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": item["id"], "name": item.get("name") or f"Record {item['id']}"} for item in records]


def employee_name(employee_id: int | None) -> str:
    if not employee_id:
        return "Not mapped"
    rows = execute("hr.employee", "read", [int(employee_id)], fields=["name", "work_email"])
    return rows[0].get("name") if rows else "Not found"


def employee_profile(employee_id: int | None) -> dict[str, Any]:
    if not employee_id:
        return {"name": "", "work_email": "", "work_phone": "", "job_title": ""}
    cache_key = f"employee_profile:{settings_signature()}:{int(employee_id)}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    rows = execute("hr.employee", "read", [int(employee_id)], fields=["name", "work_email", "work_phone", "job_title"])
    if not rows:
        return {"name": "", "work_email": "", "work_phone": "", "job_title": ""}
    row = rows[0]
    return cache_set(cache_key, {
        "name": row.get("name") or "",
        "work_email": row.get("work_email") or "",
        "work_phone": row.get("work_phone") or "",
        "job_title": row.get("job_title") or "",
    }, PROFILE_CACHE_SECONDS)


def create_odoo_employee(name: str, email: str, work_phone: str = "") -> int:
    vals = {"name": name.strip(), "work_email": email.strip()}
    if work_phone.strip():
        vals["work_phone"] = work_phone.strip()
    return int(execute("hr.employee", "create", vals))


def update_employee_profile(employee_id: int, vals: dict[str, str]) -> None:
    clean_vals = {key: value.strip() for key, value in vals.items() if value is not None}
    execute("hr.employee", "write", [int(employee_id)], clean_vals)
    cache_delete_prefix(f"employee_profile:{settings_signature()}:{int(employee_id)}")


def update_portal_profile(user_id: int, email: str, display_name: str) -> None:
    if "@" not in email:
        raise ValueError("Email must contain @.")
    if not display_name.strip():
        raise ValueError("Name is required.")
    with conn() as db:
        existing = db.execute("select id from users where lower(username)=lower(?) and id<>?", (email.strip(), int(user_id))).fetchone()
        if existing:
            raise ValueError("Another portal user already has this email.")
        db.execute("update users set username=?, display_name=? where id=?", (email.strip(), display_name.strip(), int(user_id)))


def create_app_user(username: str, password: str, display_name: str, employee_id: int, is_admin: bool = False) -> None:
    if not username.strip() or not password or not display_name.strip() or not employee_id:
        raise ValueError("Email, password, display name, and Odoo employee are required.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    with conn() as db:
        if db.execute("select 1 from users where lower(username)=lower(?)", (username.strip(),)).fetchone():
            raise ValueError("A portal user with this email already exists.")
        db.execute(
            """
            insert into users (username,password_hash,display_name,is_admin,odoo_employee_id,active,created_at)
            values (?,?,?,?,?,?,?)
            """,
            (username.strip(), password_hash(password), display_name.strip(), 1 if is_admin else 0, int(employee_id), 1, now()),
        )


def sync_odoo_employees(actor_user_id: int | None = None) -> dict[str, int]:
    """Mirror Odoo employees, including archive and deletion status, in portal accounts."""
    records = execute(
        "hr.employee",
        "search_read",
        [],
        fields=["name", "work_email", "work_phone", "active"],
        order="name,id",
        limit=2000,
        context={"active_test": False},
    )
    created = 0
    updated = 0
    skipped = 0
    deactivated = 0
    deleted = 0
    odoo_employee_ids = {int(employee["id"]) for employee in records}
    with conn() as db:
        for employee in records:
            employee_id = int(employee["id"])
            email = str(employee.get("work_email") or "").strip()
            name = str(employee.get("name") or "").strip()
            if not email or not name:
                skipped += 1
                continue
            active = 1 if employee.get("active", True) else 0
            by_employee = db.execute(
                "select id,username,display_name,is_admin,active from users where odoo_employee_id=?",
                (employee_id,),
            ).fetchone()
            by_email = db.execute(
                "select id,username,display_name,is_admin,odoo_employee_id,active from users where lower(username)=lower(?)",
                (email,),
            ).fetchone()
            if by_employee:
                if by_email and int(by_email["id"]) != int(by_employee["id"]):
                    skipped += 1
                    continue
                changed = by_employee["username"] != email or by_employee["display_name"] != name or int(by_employee["active"]) != active
                if changed:
                    db.execute(
                        "update users set username=?,display_name=?,active=? where id=? and is_admin=0",
                        (email, name, active, int(by_employee["id"])),
                    )
                    updated += 1
                if not active:
                    db.execute("delete from sessions where user_id=?", (int(by_employee["id"]),))
                    db.execute("update timesheet_approvals set status='rejected',decided_at=?,decision_note='Employee is inactive in Odoo.' where submitter_user_id=? and status='pending'", (now(), int(by_employee["id"])))
                    deactivated += int(changed)
                continue
            if by_email:
                if by_email["is_admin"] or by_email["odoo_employee_id"] not in (None, employee_id):
                    skipped += 1
                    continue
                changed = by_email["display_name"] != name or int(by_email["active"]) != active or by_email["odoo_employee_id"] != employee_id
                if changed:
                    db.execute(
                        "update users set display_name=?,odoo_employee_id=?,active=? where id=?",
                        (name, employee_id, active, int(by_email["id"])),
                    )
                    updated += 1
                if not active:
                    db.execute("delete from sessions where user_id=?", (int(by_email["id"]),))
                    db.execute("update timesheet_approvals set status='rejected',decided_at=?,decision_note='Employee is inactive in Odoo.' where submitter_user_id=? and status='pending'", (now(), int(by_email["id"])))
                    deactivated += int(changed)
                continue
            db.execute(
                """
                insert into users (username,password_hash,display_name,is_admin,odoo_employee_id,active,created_at)
                values (?,?,?,?,?,?,?)
                """,
                (email, password_hash(DEFAULT_EMPLOYEE_PASSWORD), name, 0, employee_id, active, now()),
            )
            created += 1
        portal_employees = db.execute("select id,odoo_employee_id from users where is_admin=0 and odoo_employee_id is not null").fetchall()
        for portal_employee in portal_employees:
            if int(portal_employee["odoo_employee_id"]) in odoo_employee_ids:
                continue
            user_id = int(portal_employee["id"])
            db.execute("update timesheet_approvals set status='rejected',decided_at=?,decision_note='Employee no longer exists in Odoo.' where submitter_user_id=? and status='pending'", (now(), user_id))
            db.execute("delete from sessions where user_id=?", (user_id,))
            db.execute("delete from user_projects where user_id=?", (user_id,))
            db.execute("delete from project_managers where manager_user_id=?", (user_id,))
            db.execute("delete from project_approvers where user_id=?", (user_id,))
            db.execute("delete from employee_managers where user_id=? or manager_user_id=?", (user_id, user_id))
            db.execute("delete from users where id=?", (user_id,))
            deleted += 1
    cache_delete_prefix("employee_profile:")
    if actor_user_id is not None or any([created, updated, skipped, deactivated, deleted]):
        audit(actor_user_id, "odoo.employee.sync", {"created": created, "updated": updated, "skipped": skipped, "deactivated": deactivated, "deleted": deleted})
    return {"created": created, "updated": updated, "skipped": skipped, "deactivated": deactivated, "deleted": deleted}


def employee_sync_worker() -> None:
    """Keep portal employment access aligned with Odoo without manual admin action."""
    while True:
        try:
            sync_odoo_employees()
        except Exception:
            # The next interval retries transient Odoo connectivity failures.
            pass
        time.sleep(EMPLOYEE_SYNC_SECONDS)


def bootstrap_data() -> dict[str, Any]:
    cache_key = f"bootstrap:{settings_signature()}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    projects = execute("project.project", "search_read", [("allow_timesheets", "=", True)], fields=["name"], order="name", limit=200)
    project_ids = [project["id"] for project in projects]
    tasks: list[dict[str, Any]] = []
    if project_ids:
        tasks = execute("project.task", "search_read", [("project_id", "in", project_ids)], fields=["name", "project_id"], order="project_id,name", limit=1000)
    grouped: dict[str, list[dict[str, Any]]] = {str(project_id): [] for project_id in project_ids}
    for task in tasks:
        project = task.get("project_id")
        if project:
            grouped.setdefault(str(project[0]), []).append({"id": task["id"], "name": task["name"]})
    return cache_set(cache_key, {"projects": odoo_records(projects), "tasks_by_project": grouped}, BOOTSTRAP_CACHE_SECONDS)


def bootstrap_data_for_user(user: dict[str, Any]) -> dict[str, Any]:
    data = bootstrap_data()
    if user.get("is_admin"):
        return data
    allowed = assigned_project_ids(int(user["id"]))
    projects = [project for project in data["projects"] if int(project["id"]) in allowed]
    project_keys = {str(project["id"]) for project in projects}
    tasks_by_project = {project_id: tasks for project_id, tasks in data["tasks_by_project"].items() if project_id in project_keys}
    return {"projects": projects, "tasks_by_project": tasks_by_project}


def default_task_for_project(project_id: int) -> int:
    rows = execute(
        "project.task",
        "search_read",
        [("project_id", "=", int(project_id)), ("name", "=", "Default Task")],
        fields=["name"],
        limit=1,
    )
    if rows:
        return int(rows[0]["id"])
    rows = execute("project.task", "search_read", [("project_id", "=", int(project_id))], fields=["name"], order="id", limit=1)
    if rows:
        return int(rows[0]["id"])
    return int(execute("project.task", "create", {"name": "Default Task", "project_id": int(project_id)}))


def valid_timesheet_hours(value: float) -> float:
    """Return a valid daily duration, limited to whole or half-hour increments."""
    hours = float(value)
    if not math.isfinite(hours) or hours <= 0 or hours > 24:
        raise ValueError("Hours must be between 0 and 24.")
    if not math.isclose(hours * 2, round(hours * 2), abs_tol=1e-9):
        raise ValueError("Hours must be in whole-hour or half-hour increments (for example, 1 or 1.5).")
    return hours


def create_timesheet(user: dict[str, Any], payload: TimesheetPayload) -> dict[str, Any]:
    if not user.get("odoo_employee_id"):
        raise ValueError("This login is not mapped to an Odoo employee.")
    if not user.get("is_admin") and int(payload.project_id) not in assigned_project_ids(int(user["id"])):
        raise ValueError("This project is not assigned to your portal account.")
    hours = valid_timesheet_hours(payload.unit_amount)
    task_id = int(payload.task_id) if payload.task_id else default_task_for_project(int(payload.project_id))
    description = payload.name.strip() if payload.name else "Weekly timesheet"
    vals = {
        "employee_id": int(user["odoo_employee_id"]),
        "project_id": int(payload.project_id),
        "task_id": task_id,
        "date": payload.date,
        "unit_amount": hours,
        "name": description,
    }
    line_id = execute("account.analytic.line", "create", vals)
    audit(user["id"], "timesheet.create", {"line_id": line_id, "employee_id": user["odoo_employee_id"]})
    return {"id": line_id}


def queue_timesheet_for_approval(user: dict[str, Any], payload: TimesheetPayload, approver_user_ids: list[int]) -> int:
    if not user.get("odoo_employee_id"):
        raise ValueError("This login is not mapped to an Odoo employee.")
    if not user.get("is_admin") and int(payload.project_id) not in assigned_project_ids(int(user["id"])):
        raise ValueError("This project is not assigned to your portal account.")
    hours = valid_timesheet_hours(payload.unit_amount)
    task_id = int(payload.task_id) if payload.task_id else default_task_for_project(int(payload.project_id))
    description = payload.name.strip() if payload.name else "Weekly timesheet"
    with conn() as db:
        result = db.execute(
            """
            insert into timesheet_approvals
            (submitter_user_id,manager_user_id,project_id,task_id,work_date,unit_amount,description,status,submitted_at)
            values (?,?,?,?,?,?,?,?,?)
            """,
            (int(user["id"]), int(approver_user_ids[0]), int(payload.project_id), task_id, payload.date, hours, description, "pending", now()),
        )
        approval_id = int(result.lastrowid)
        db.executemany("insert into timesheet_approval_approvers (approval_id,user_id) values (?,?)", [(approval_id, int(approver_id)) for approver_id in approver_user_ids])
        return approval_id


def create_timesheets(user: dict[str, Any], payload: TimesheetBatchPayload) -> dict[str, Any]:
    if not payload.lines:
        raise ValueError("Add at least one timesheet line.")
    if len(payload.lines) > 100:
        raise ValueError("Submit 100 daily entries or fewer at a time.")
    approvers = project_approvers()
    managers = employee_managers()
    created: list[int] = []
    queued: list[int] = []
    for line in payload.lines:
        approver_ids = [managers[str(user["id"])] ] if str(user["id"]) in managers else approvers.get(str(int(line.project_id)), [])
        if approver_ids:
            queued.append(queue_timesheet_for_approval(user, line, approver_ids))
        else:
            created.append(create_timesheet(user, line)["id"])
    audit(user["id"], "timesheet.batch_create", {"line_ids": created, "approval_ids": queued, "count": len(created) + len(queued)})
    cache_delete_prefix(f"timesheets:{settings_signature()}:{user['id']}:")
    return {"ids": created, "approval_ids": queued, "count": len(created) + len(queued), "submitted_count": len(created), "pending_count": len(queued)}


def pending_approvals_for_manager(user: dict[str, Any]) -> list[dict[str, Any]]:
    with conn() as db:
        rows = db.execute(
            """
            select a.id,a.project_id,a.work_date,a.unit_amount,a.submitted_at,u.display_name,u.username
            from timesheet_approvals a
            join users u on u.id=a.submitter_user_id
            join timesheet_approval_approvers aa on aa.approval_id=a.id
            where aa.user_id=? and a.status='pending'
            order by a.submitted_at asc,a.id asc
            """,
            (int(user["id"]),),
        ).fetchall()
    projects = {int(project["id"]): project["name"] for project in bootstrap_data()["projects"]}
    return [
        {
            "id": int(row["id"]), "project_id": int(row["project_id"]), "project": projects.get(int(row["project_id"]), f"Project {row['project_id']}"),
            "date": row["work_date"], "hours": row["unit_amount"], "submitter": row["display_name"] or row["username"], "submitted_at": row["submitted_at"],
        }
        for row in rows
    ]


def decide_timesheet_approval(user: dict[str, Any], approval_id: int, approved: bool, note: str = "") -> dict[str, Any]:
    with conn() as db:
        approval = db.execute("select * from timesheet_approvals where id=?", (int(approval_id),)).fetchone()
    if not approval:
        raise ValueError("Approval request not found.")
    with conn() as db:
        assigned = db.execute("select 1 from timesheet_approval_approvers where approval_id=? and user_id=?", (int(approval_id), int(user["id"]))).fetchone()
    if not assigned:
        raise ValueError("Only an assigned approver can decide this request.")
    if int(approval["submitter_user_id"]) == int(user["id"]):
        raise ValueError("A manager cannot approve or reject their own timesheet.")
    if approval["status"] != "pending":
        raise ValueError("This request has already been decided.")
    clean_note = note.strip()[:500]
    if not approved:
        with conn() as db:
            db.execute("update timesheet_approvals set status='rejected',decided_at=?,decided_by=?,decision_note=? where id=? and status='pending'", (now(), int(user["id"]), clean_note, int(approval_id)))
        audit(user["id"], "timesheet.approval.reject", {"approval_id": int(approval_id)})
        return {"id": int(approval_id), "status": "rejected"}
    submitter = portal_user(int(approval["submitter_user_id"]))
    if not submitter or not submitter.get("odoo_employee_id"):
        raise ValueError("The submitting employee is no longer mapped to Odoo.")
    vals = {
        "employee_id": int(submitter["odoo_employee_id"]), "project_id": int(approval["project_id"]), "task_id": int(approval["task_id"]),
        "date": approval["work_date"], "unit_amount": float(approval["unit_amount"]), "name": approval["description"],
    }
    line_id = execute("account.analytic.line", "create", vals)
    with conn() as db:
        result = db.execute("update timesheet_approvals set status='approved',decided_at=?,decided_by=?,decision_note=?,odoo_line_id=? where id=? and status='pending'", (now(), int(user["id"]), clean_note, int(line_id), int(approval_id)))
    if result.rowcount != 1:
        raise ValueError("This request was already decided.")
    cache_delete_prefix(f"timesheets:{settings_signature()}:{submitter['id']}:")
    audit(user["id"], "timesheet.approval.approve", {"approval_id": int(approval_id), "line_id": int(line_id)})
    return {"id": int(approval_id), "status": "approved", "line_id": int(line_id)}


def timesheet_record_for_user(user: dict[str, Any], line_id: int) -> dict[str, Any]:
    if not user.get("odoo_employee_id"):
        raise ValueError("This login is not mapped to an Odoo employee.")
    rows = execute(
        "account.analytic.line",
        "read",
        [int(line_id)],
        fields=["employee_id", "project_id", "task_id", "date", "unit_amount", "name"],
    )
    if not rows:
        raise ValueError("Timesheet line not found.")
    row = rows[0]
    employee = row.get("employee_id") or []
    employee_id = employee[0] if isinstance(employee, list) and employee else None
    if int(employee_id or 0) != int(user["odoo_employee_id"]):
        raise ValueError("You can only manage your own timesheets.")
    project = row.get("project_id") or []
    project_id = project[0] if isinstance(project, list) and project else None
    if not user.get("is_admin") and int(project_id or 0) not in assigned_project_ids(int(user["id"])):
        raise ValueError("This timesheet project is not assigned to your portal account.")
    return row


def update_timesheet(user: dict[str, Any], line_id: int, payload: TimesheetUpdatePayload) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise ValueError("Approved timesheets cannot be edited by employees.")
    timesheet_record_for_user(user, line_id)
    if not user.get("is_admin") and int(payload.project_id) not in assigned_project_ids(int(user["id"])):
        raise ValueError("This project is not assigned to your portal account.")
    hours = valid_timesheet_hours(payload.unit_amount)
    vals = {
        "project_id": int(payload.project_id),
        "task_id": default_task_for_project(int(payload.project_id)),
        "date": payload.date,
        "unit_amount": hours,
    }
    execute("account.analytic.line", "write", [int(line_id)], vals)
    audit(user["id"], "timesheet.update", {"line_id": int(line_id)})
    cache_delete_prefix(f"timesheets:{settings_signature()}:{user['id']}:")
    return {"id": int(line_id)}


def delete_timesheet(user: dict[str, Any], line_id: int) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise ValueError("Approved timesheets cannot be deleted by employees.")
    timesheet_record_for_user(user, line_id)
    execute("account.analytic.line", "unlink", [int(line_id)])
    audit(user["id"], "timesheet.delete", {"line_id": int(line_id)})
    cache_delete_prefix(f"timesheets:{settings_signature()}:{user['id']}:")
    return {"id": int(line_id)}


def my_timesheets(
    user: dict[str, Any],
    page: int = 1,
    page_size: int = 20,
    date_from: str = "",
    date_to: str = "",
    project_id: int | None = None,
    search: str = "",
) -> dict[str, Any]:
    if not user.get("odoo_employee_id"):
        return {"timesheets": [], "page": page, "page_size": page_size, "total": 0, "has_next": False}
    page = max(1, int(page or 1))
    page_size = min(50, max(5, int(page_size or 20)))
    search = search.strip()
    cache_key = f"timesheets:{settings_signature()}:{user['id']}:{page}:{page_size}:{date_from}:{date_to}:{project_id or ''}:{search}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    domain: list[Any] = [("employee_id", "=", int(user["odoo_employee_id"]))]
    if not user.get("is_admin"):
        allowed = assigned_project_ids(int(user["id"]))
        if not allowed:
            return {"timesheets": [], "page": page, "page_size": page_size, "total": 0, "has_next": False}
        if project_id and int(project_id) not in allowed:
            return {"timesheets": [], "page": page, "page_size": page_size, "total": 0, "has_next": False}
        domain.append(("project_id", "in", sorted(allowed)))
    if date_from:
        domain.append(("date", ">=", date_from))
    if date_to:
        domain.append(("date", "<=", date_to))
    if project_id:
        domain.append(("project_id", "=", int(project_id)))
    if search:
        domain = ["|", "|", ("name", "ilike", search), ("project_id.name", "ilike", search), ("task_id.name", "ilike", search)] + domain
    rows = execute(
        "account.analytic.line",
        "search_read",
        domain,
        fields=["date", "unit_amount", "project_id"],
        order="date desc,id desc",
        limit=page_size + 1,
        offset=(page - 1) * page_size,
    )
    has_next = len(rows) > page_size
    rows = rows[:page_size]
    output = []
    for row in rows:
        project = row.get("project_id") or ["", ""]
        output.append(
            {
                "id": row["id"],
                "date": row.get("date") or "",
                "project_id": project[0] if isinstance(project, list) and project else "",
                "project": project[1] if isinstance(project, list) and len(project) > 1 else "",
                "hours": row.get("unit_amount") or 0,
            }
        )
    return cache_set(cache_key, {"timesheets": output, "page": page, "page_size": page_size, "has_next": has_next}, TIMESHEET_CACHE_SECONDS)


def page(title: str, user: dict[str, Any] | None, content: str) -> HTMLResponse:
    nav = ""
    if user:
        admin = '<a class="button secondary" href="/admin">Admin</a>' if user.get("is_admin") else ""
        display_name = html.escape(str(user.get("display_name") or user.get("username") or "User"))
        nav = f'<div class="nav"><span class="user-name" title="{display_name}">{display_name}</span>{admin}<a class="button secondary" href="/account">Account</a><a class="button secondary" href="/logout">Logout</a></div>'
    brand = f"<div class='brand'><img src='{EITEKH_LOGO_URL}' alt='eiTekh logo'><div><h1>{html.escape(title)}</h1><small>eiTekh ERP Limited</small></div></div>"
    body = f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><link rel='icon' href='{EITEKH_LOGO_URL}'><title>{html.escape(title)}</title>{CSS}</head><body><header><div class='bar'>{brand}{nav}</div></header>{content}</body></html>"
    response = HTMLResponse(body)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' https://static.wixstatic.com data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    if COOKIE_SECURE:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def login_page(message: str = "") -> HTMLResponse:
    msg = f"<div class='message err'>{html.escape(message)}</div>" if message else ""
    return page(
        "Timesheet Portal Login",
        None,
        f"""
        <main class="login-shell"><section class="panel">
          <h2>Employee Login</h2>
          <form class="one-col" method="post" action="/login">
            <label>Email<input name="username" type="email" autocomplete="username" required></label>
            <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
            <button type="submit">Login</button>{msg}
          </form>
        </section></main>
        """,
    )


def setup_page(message: str = "", is_error: bool = False) -> HTMLResponse:
    cls = "err" if is_error else "ok"
    msg = f"<div class='message {cls}'>{html.escape(message)}</div>" if message else ""
    return page(
        "First Admin Setup",
        None,
        f"""
        <main class="login-shell"><section class="panel">
          <h2>Create First Admin</h2>
          <form class="one-col" method="post" action="/setup">
            <label>Admin email<input name="username" type="email" required></label>
            <label>Admin name<input name="display_name" required></label>
            <label>Password<input name="password" type="password" minlength="8" required></label>
            <button type="submit">Create Admin</button>{msg}
          </form>
          <p class="hint">This page is available only while no portal users exist.</p>
        </section></main>
        """,
    )


def dashboard_page(user: dict[str, Any]) -> HTMLResponse:
    csrf = html.escape(user["csrf_token"])
    can_manage_timesheets = bool(user.get("is_admin"))
    timesheet_actions_header = "<th>Actions</th>" if can_manage_timesheets else ""
    timesheet_colspan = "4" if can_manage_timesheets else "3"
    approval_panel = """
          <section class="panel wide" id="approvalPanel">
            <h2>Timesheets Awaiting Your Approval</h2>
            <p class="hint">Approved entries are sent to Odoo. Rejected entries remain out of Odoo.</p>
            <div class="table-wrap">
              <table><thead><tr><th>Employee</th><th>Date</th><th>Project</th><th>Hours</th><th>Actions</th></tr></thead><tbody id="approvalRows"><tr><td colspan="5">Loading...</td></tr></tbody></table>
            </div>
            <div id="approvalMessage" class="message"></div>
          </section>
    """ if has_approval_responsibility(int(user["id"])) else ""
    return page(
        "eiTekh Timesheet Portal",
        user,
        f"""
        <main class="grid">
          <section class="panel sheet-panel">
            <h2>Submit Timesheets</h2>
            <form id="timesheetForm">
              <div class="week-bar">
                <label>Week Starting (Sunday)<input id="weekStart" type="date" required></label>
                <button id="currentWeekButton" type="button">Current Week</button>
                <span class="hint">Enter whole hours or half-hours only: <strong>.5 = 30 minutes</strong> (for example, 1, 1.5, or 2).</span>
              </div>
              <div class="weekly-sheet">
                <div class="weekly-header sheet-grid">
                  <span>Project</span><span>Sunday</span><span>Monday</span><span>Tuesday</span><span>Wednesday</span><span>Thursday</span><span>Friday</span><span>Saturday</span><span>Total</span><span></span>
                </div>
                <div id="lines"></div>
              </div>
              <div class="toolbar">
                <button id="addLineButton" type="button">Add Project</button>
                <button id="submitButton" type="submit">Submit</button>
                <strong id="weekTotal" class="toolbar-total">Total: 0.00</strong>
              </div>
              <div id="message" class="message"></div>
            </form>
          </section>
          {approval_panel}
          <section class="panel wide">
            <h2>My Timesheets</h2>
            <div class="filters">
              <label>Date From<input id="filterDateFrom" type="date"></label>
              <label>Date To<input id="filterDateTo" type="date"></label>
              <label>Project<select id="filterProject"><option value="">All projects</option></select></label>
              <label>Search<input id="filterSearch" type="search" placeholder="Project"></label>
              <label>Page Size<select id="pageSize"><option value="10">10</option><option value="20" selected>20</option><option value="50">50</option></select></label>
              <button id="applyFilters" type="button">Filter</button>
            </div>
            <div class="table-wrap">
              <table><thead><tr><th>Date</th><th>Project</th><th>Hours</th>{timesheet_actions_header}</tr></thead><tbody id="timesheetRows"><tr><td colspan="{timesheet_colspan}">Loading...</td></tr></tbody></table>
            </div>
            <div class="pager">
              <button id="prevPage" type="button">Previous</button>
              <span id="pageInfo">Page 1</span>
              <button id="nextPage" type="button">Next</button>
            </div>
          </section>
        </main>
        <script>
          const csrfToken = "{csrf}";
          const lines = document.getElementById('lines');
          const msg = document.getElementById('message');
          const button = document.getElementById('submitButton');
          const canManageTimesheets = {str(can_manage_timesheets).lower()};
          let projects = [];
          let timesheetPage = 1;
          let timesheetHasNext = false;
          const dayNames = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
          function option(item) {{ const node = document.createElement('option'); node.value = item.id; node.textContent = item.name; return node; }}
          function setMessage(text, type) {{ msg.textContent = text; msg.className = 'message ' + (type || ''); }}
          function localDate(value) {{ return value.getFullYear() + '-' + String(value.getMonth() + 1).padStart(2, '0') + '-' + String(value.getDate()).padStart(2, '0'); }}
          function today() {{ return localDate(new Date()); }}
          function sundayOf(date) {{
            const value = new Date(date + 'T12:00:00');
            value.setDate(value.getDate() - value.getDay());
            return localDate(value);
          }}
          function dateForDay(index) {{
            const value = new Date(document.getElementById('weekStart').value + 'T12:00:00');
            value.setDate(value.getDate() + index);
            return localDate(value);
          }}
          function hoursValue(input) {{
            const value = Number(input.value || 0);
            return Number.isFinite(value) && value > 0 && Math.abs(value * 2 - Math.round(value * 2)) < 0.000001 ? value : 0;
          }}
          function validHourIncrement(value) {{ return Number.isFinite(value) && value >= 0 && value <= 24 && Math.abs(value * 2 - Math.round(value * 2)) < 0.000001; }}
          function updateTotals() {{
            let weekTotal = 0;
            Array.from(lines.children).forEach(row => {{
              let rowTotal = 0;
              row.querySelectorAll('[data-day]').forEach(input => rowTotal += hoursValue(input));
              row.querySelector('[data-row-total]').value = rowTotal.toFixed(2);
              weekTotal += rowTotal;
            }});
            document.getElementById('weekTotal').textContent = 'Total: ' + weekTotal.toFixed(2);
          }}
          function addLine(values) {{
            const row = document.createElement('div');
            row.className = 'line-item sheet-grid';
            row.innerHTML = `
              <div><select name="project_id" aria-label="Project" required></select></div>
              <div class="day-input"><input data-day="0" name="sunday" aria-label="Sunday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="1" name="monday" aria-label="Monday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="2" name="tuesday" aria-label="Tuesday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="3" name="wednesday" aria-label="Wednesday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="4" name="thursday" aria-label="Thursday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="5" name="friday" aria-label="Friday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="day-input"><input data-day="6" name="saturday" aria-label="Saturday hours" type="number" min="0" max="24" step="0.5" placeholder="0"></div>
              <div class="line-total"><input data-row-total aria-label="Row total" readonly value="0.00"></div>
              <button class="line-remove" type="button" data-remove aria-label="Remove project" title="Remove project">&times;</button>
            `;
            const project = row.querySelector('[name="project_id"]');
            projects.forEach(item => project.appendChild(option(item)));
            dayNames.forEach((name, index) => row.querySelector('[name="' + name + '"]').value = values?.[name] || '');
            row.querySelectorAll('[data-day]').forEach(input => input.addEventListener('input', updateTotals));
            row.querySelector('[data-remove]').addEventListener('click', () => {{
              if (lines.children.length > 1) row.remove();
              updateTotals();
            }});
            lines.appendChild(row);
            updateTotals();
          }}
          function timesheetQuery() {{
            const params = new URLSearchParams();
            params.set('page', String(timesheetPage));
            params.set('page_size', document.getElementById('pageSize').value);
            const dateFrom = document.getElementById('filterDateFrom').value;
            const dateTo = document.getElementById('filterDateTo').value;
            const projectId = document.getElementById('filterProject').value;
            const search = document.getElementById('filterSearch').value.trim();
            if (dateFrom) params.set('date_from', dateFrom);
            if (dateTo) params.set('date_to', dateTo);
            if (projectId) params.set('project_id', projectId);
            if (search) params.set('search', search);
            return params.toString();
          }}
          function projectSelectHtml(selectedId) {{
            const options = projects.map(project => '<option value="' + project.id + '"' + (Number(project.id) === Number(selectedId) ? ' selected' : '') + '>' + project.name.replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char])) + '</option>');
            return '<select name="project_id" aria-label="Project">' + options.join('') + '</select>';
          }}
          function renderTimesheetRow(item) {{
            const tr = document.createElement('tr');
            tr.dataset.lineId = item.id;
            tr.dataset.item = JSON.stringify(item);
            [item.date, item.project, Number(item.hours).toFixed(2)].forEach(value => {{
              const td = document.createElement('td');
              td.textContent = value;
              tr.appendChild(td);
            }});
            if (canManageTimesheets) {{
              const actions = document.createElement('td');
              actions.className = 'row-actions';
              actions.innerHTML = '<button type="button" class="button secondary" data-edit>Edit</button><button type="button" class="button secondary" data-delete>Delete</button>';
              tr.appendChild(actions);
              actions.querySelector('[data-edit]').addEventListener('click', () => renderEditRow(tr));
              actions.querySelector('[data-delete]').addEventListener('click', () => deleteTimesheetRow(tr));
            }}
            return tr;
          }}
          function renderEditRow(tr) {{
            const item = JSON.parse(tr.dataset.item);
            tr.innerHTML = `
              <td class="edit-cell"><input name="date" type="date" value="${{item.date}}"></td>
              <td class="edit-cell">${{projectSelectHtml(item.project_id)}}</td>
              <td class="edit-cell"><input name="unit_amount" type="number" min="0.5" max="24" step="0.5" value="${{Number(item.hours).toFixed(2)}}"></td>
              <td class="row-actions"><button type="button" data-save>Save</button><button type="button" class="button secondary" data-cancel>Cancel</button></td>
            `;
            tr.querySelector('[data-save]').addEventListener('click', () => saveTimesheetRow(tr));
            tr.querySelector('[data-cancel]').addEventListener('click', () => tr.replaceWith(renderTimesheetRow(item)));
          }}
          async function saveTimesheetRow(tr) {{
            const payload = {{
              project_id: Number(tr.querySelector('[name="project_id"]').value),
              date: tr.querySelector('[name="date"]').value,
              unit_amount: Number(tr.querySelector('[name="unit_amount"]').value),
            }};
            const res = await fetch('/api/timesheets/' + tr.dataset.lineId, {{ method:'PUT', headers:{{'Content-Type':'application/json','X-CSRF-Token':csrfToken}}, body:JSON.stringify(payload) }});
            const data = await res.json();
            if (!res.ok) {{
              setMessage(data.error || 'Could not update timesheet.', 'err');
              return;
            }}
            setMessage('Timesheet updated.', 'ok');
            loadTimesheets();
          }}
          async function deleteTimesheetRow(tr) {{
            if (!confirm('Delete this timesheet line?')) return;
            const res = await fetch('/api/timesheets/' + tr.dataset.lineId, {{ method:'DELETE', headers:{{'X-CSRF-Token':csrfToken}} }});
            const data = await res.json();
            if (!res.ok) {{
              setMessage(data.error || 'Could not delete timesheet.', 'err');
              return;
            }}
            setMessage('Timesheet deleted.', 'ok');
            loadTimesheets();
          }}
          async function loadTimesheets() {{
            const tbody = document.getElementById('timesheetRows');
            try {{
              const res = await fetch('/api/my-timesheets?' + timesheetQuery());
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Could not load timesheets');
              tbody.innerHTML = '';
              if (!data.timesheets.length) {{
                tbody.innerHTML = '<tr><td colspan="{timesheet_colspan}">No timesheets submitted yet.</td></tr>';
                timesheetHasNext = false;
                document.getElementById('pageInfo').textContent = 'Page ' + data.page;
                document.getElementById('prevPage').disabled = data.page <= 1;
                document.getElementById('nextPage').disabled = true;
                return;
              }}
              data.timesheets.forEach(item => {{
                tbody.appendChild(renderTimesheetRow(item));
              }});
              timesheetHasNext = data.has_next;
              document.getElementById('pageInfo').textContent = 'Page ' + data.page + (data.has_next ? '' : ' - end');
              document.getElementById('prevPage').disabled = data.page <= 1;
              document.getElementById('nextPage').disabled = !data.has_next;
            }} catch (error) {{
              tbody.innerHTML = '';
              const tr = document.createElement('tr');
              const td = document.createElement('td');
              td.colSpan = {timesheet_colspan};
              td.textContent = error.message;
              tr.appendChild(td);
              tbody.appendChild(tr);
              document.getElementById('pageInfo').textContent = 'Page ' + timesheetPage;
            }}
          }}
          async function loadData() {{
            setMessage('Preparing timesheet form...', '');
            const res = await fetch('/api/bootstrap?refresh=1', {{ cache: 'no-store' }});
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not load Odoo data');
            projects = data.projects;
            const filterProject = document.getElementById('filterProject');
            filterProject.innerHTML = '<option value="">All projects</option>';
            data.projects.forEach(item => filterProject.appendChild(option(item)));
            lines.innerHTML = '';
            document.getElementById('weekStart').value = sundayOf(today());
            addLine();
            setMessage(data.projects.length ? 'Ready to submit.' : 'No timesheet-enabled projects found.', data.projects.length ? 'ok' : 'err');
          }}
          document.getElementById('addLineButton').addEventListener('click', () => addLine());
          document.getElementById('currentWeekButton').addEventListener('click', () => {{ document.getElementById('weekStart').value = sundayOf(today()); }});
          document.getElementById('weekStart').addEventListener('change', event => {{ if (event.target.value) event.target.value = sundayOf(event.target.value); }});
          document.getElementById('applyFilters').addEventListener('click', () => {{ timesheetPage = 1; loadTimesheets(); }});
          document.getElementById('pageSize').addEventListener('change', () => {{ timesheetPage = 1; loadTimesheets(); }});
          document.getElementById('prevPage').addEventListener('click', () => {{ if (timesheetPage > 1) {{ timesheetPage -= 1; loadTimesheets(); }} }});
          document.getElementById('nextPage').addEventListener('click', () => {{ if (timesheetHasNext) {{ timesheetPage += 1; loadTimesheets(); }} }});
          document.getElementById('timesheetForm').addEventListener('submit', async event => {{
            event.preventDefault();
            button.disabled = true;
            setMessage('Submitting to Odoo...', '');
            const payload = {{ lines: [] }};
            const invalidHour = Array.from(lines.querySelectorAll('[data-day]')).find(input => input.value && !validHourIncrement(Number(input.value)));
            if (invalidHour) {{ setMessage('Enter hours in whole-hour or half-hour increments only (for example, 1 or 1.5).', 'err'); button.disabled = false; return; }}
            Array.from(lines.children).forEach(row => {{
              const projectId = Number(row.querySelector('[name="project_id"]').value);
              row.querySelectorAll('[data-day]').forEach(input => {{
                const hours = hoursValue(input);
                if (projectId && hours > 0) {{
                  payload.lines.push({{
                    project_id: projectId,
                    date: dateForDay(Number(input.dataset.day)),
                    unit_amount: hours,
                    name: 'Weekly timesheet'
                  }});
                }}
              }});
            }});
            try {{
              if (!payload.lines.length) throw new Error('Enter hours for at least one project day.');
              const res = await fetch('/api/timesheets', {{ method:'POST', headers:{{'Content-Type':'application/json','X-CSRF-Token':csrfToken}}, body:JSON.stringify(payload) }});
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Submission failed');
              const approvalText = data.pending_count ? (' ' + data.pending_count + ' line(s) sent for manager approval.') : '';
              const directText = data.submitted_count ? (data.submitted_count + ' line(s) sent to Odoo.') : '';
              setMessage((directText + approvalText).trim(), 'ok');
              lines.innerHTML = '';
              addLine();
              loadTimesheets();
            }} catch (error) {{ setMessage(error.message, 'err'); }}
            finally {{ button.disabled = false; }}
          }});
          loadData()
            .then(() => setTimeout(loadTimesheets, 100))
            .catch(error => setMessage(error.message, 'err'));
          const approvalRows = document.getElementById('approvalRows');
          if (approvalRows) {{
            const approvalMessage = document.getElementById('approvalMessage');
            function setApprovalMessage(text, type) {{ approvalMessage.textContent = text; approvalMessage.className = 'message ' + (type || ''); }}
            async function decideApproval(id, approved) {{
              try {{
                setApprovalMessage(approved ? 'Approving timesheet...' : 'Rejecting timesheet...', '');
                const res = await fetch('/api/approvals/' + id + (approved ? '/approve' : '/reject'), {{
                  method: 'POST', headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken }}, body: JSON.stringify({{}})
                }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Could not update approval.');
                setApprovalMessage(approved ? 'Timesheet approved and sent to Odoo.' : 'Timesheet rejected.', 'ok');
                loadApprovals();
              }} catch (error) {{ setApprovalMessage(error.message, 'err'); }}
            }}
            async function loadApprovals() {{
              try {{
                const res = await fetch('/api/my-approvals');
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Could not load approvals.');
                approvalRows.innerHTML = '';
                if (!data.approvals.length) {{ approvalRows.innerHTML = '<tr><td colspan="5">No timesheets are awaiting your approval.</td></tr>'; return; }}
                data.approvals.forEach(item => {{
                  const tr = document.createElement('tr');
                  [item.submitter, item.date, item.project, Number(item.hours).toFixed(2)].forEach(value => {{ const td = document.createElement('td'); td.textContent = value; tr.appendChild(td); }});
                  const actions = document.createElement('td'); actions.className = 'row-actions';
                  const approve = document.createElement('button'); approve.type = 'button'; approve.textContent = 'Approve'; approve.addEventListener('click', () => decideApproval(item.id, true));
                  const reject = document.createElement('button'); reject.type = 'button'; reject.className = 'button secondary'; reject.textContent = 'Reject'; reject.addEventListener('click', () => decideApproval(item.id, false));
                  actions.appendChild(approve); actions.appendChild(reject); tr.appendChild(actions); approvalRows.appendChild(tr);
                }});
              }} catch (error) {{ approvalRows.innerHTML = '<tr><td colspan="5"></td></tr>'; approvalRows.firstChild.firstChild.textContent = error.message; }}
            }}
            loadApprovals();
          }}
        </script>
        """,
    )


def admin_page(user: dict[str, Any], message: str = "", is_error: bool = False, message_area: str = "") -> HTMLResponse:
    cfg = public_settings()
    def portal_user_row(item: dict[str, Any]) -> str:
        if int(item["id"]) == int(user["id"]):
            access_action = '<span class="user-table-meta">Current user</span>'
        else:
            access_action = f"""
            <form class="compact-form user-status-form">
              <input type="hidden" name="csrf_token" value="{html.escape(user['csrf_token'])}">
              <input type="hidden" name="user_id" value="{item['id']}">
              <input type="hidden" name="active" value="{'0' if item['active'] else '1'}">
              <button type="submit" class="button secondary" data-status-button>{'Deactivate' if item['active'] else 'Activate'}</button>
            </form>
            """
        return f"""
        <tr class="portal-user-row">
          <td><input class="portal-user-select" type="checkbox" value="{item['id']}" aria-label="Select {html.escape(item['display_name'])}" {'disabled' if item['is_admin'] else ''}></td>
          <td>{html.escape(item['username'])}</td>
          <td>{html.escape(item['display_name'])}</td>
          <td>{'Admin' if item['is_admin'] else 'Employee'}</td>
          <td>{html.escape(str(item['odoo_employee_id'] or ''))}</td>
          <td data-status-cell>{'Active' if item['active'] else 'Inactive'}</td>
          <td>{access_action}</td>
          <td>
            <form class="compact-form" method="post" action="/admin/users/password#portal-users">
              <input type="hidden" name="csrf_token" value="{html.escape(user['csrf_token'])}">
              <input type="hidden" name="user_id" value="{item['id']}">
              <input name="password" type="password" minlength="8" placeholder="New password" required>
              <button type="submit">Reset</button>
            </form>
          </td>
        </tr>
        """
    rows = "".join(portal_user_row(item) for item in app_users())
    csrf = html.escape(user["csrf_token"])
    msg_class = "err" if is_error else "ok"
    msg = f"<div class='message {msg_class}'>{html.escape(message)}</div>" if message else ""
    odoo_msg = msg if message_area == "odoo" else ""
    users_msg = msg if message_area == "users" else ""
    global_msg = msg if message and not message_area else ""
    return page(
        "Portal Admin",
        user,
        f"""
        <main class="stack">
          <div class="tabs"><a href="/">Timesheet</a><a href="/account">My Password</a></div>
          {global_msg}
          <section class="panel">
            <h2>Odoo Connection</h2>
            <form method="post" action="/admin/settings">
              <input type="hidden" name="csrf_token" value="{csrf}">
              <label>Odoo URL<input name="odoo_url" value="{html.escape(cfg['odoo_url'])}" placeholder="https://your-company.odoo.com"></label>
              <label>Database<input name="odoo_db" value="{html.escape(cfg['odoo_db'])}" placeholder="Production database name"></label>
              <label>Odoo email<input name="odoo_login" type="email" value="{html.escape(cfg['odoo_login'])}"></label>
              <label>Odoo password<input name="odoo_password" type="password" placeholder="{'Password is saved' if cfg['odoo_password_set'] == 'Yes' else 'Required'}"></label>
              <button type="submit">Save Connection</button>
              <button type="submit" name="test" value="1">Save and Test</button>
              {odoo_msg}
            </form>
            <p class="hint">Use an Odoo internal user with access to Employees, Projects, Tasks, and Timesheets. Clearing or changing the Database value resets all connection-specific portal data, while keeping the current admin account ready for the next database.</p>
          </section>
          <section class="panel">
            <h2>Employee Timesheet Managers</h2>
            <p class="hint">Choose a manager, then select every employee whose timesheets that manager should approve. Employee manager rules take priority over project approvers.</p>
            <div class="approval-assignments">
              <label>Timesheet Manager<select id="employeeManagerManager"></select></label>
              <label>Search Employees<input id="employeeManagerSearch" type="search" placeholder="Type an employee name or email"></label>
              <label class="wide">Selected Employees<div id="employeeManagerSelected" class="selected-projects" aria-live="polite"></div></label>
              <label class="wide">Employees Managed<div id="employeeManagerList" class="project-checks approval-project-checks"></div></label>
            </div>
            <div class="toolbar"><button id="saveEmployeeManager" type="button">Save Manager's Employees</button></div>
            <div id="employeeManagerMessage" class="message"></div>
          </section>
          <section class="panel">
            <h2>Project Approver Fallback (Optional)</h2>
            <p class="hint">Choose an approver, then select every project they can approve. A project can have more than one approver. Hold Ctrl (Windows) or Command (Mac) to select multiple projects.</p>
            <div class="approval-assignments">
              <label>Approver<select id="approvalUser"></select></label>
              <label>Search Projects<input id="approvalProjectSearch" type="search" placeholder="Type a project name"></label>
              <label class="wide">Selected Projects<div id="approvalSelectedProjects" class="selected-projects" aria-live="polite"></div></label>
              <label class="wide">Projects this approver can approve<div id="approvalProjectList" class="project-checks approval-project-checks"></div></label>
            </div>
            <div class="toolbar"><button id="saveApprovalAssignments" type="button">Save Approval Assignments</button></div>
            <div id="approvalAssignmentMessage" class="message"></div>
          </section>
          <section class="panel">
            <h2>Assign Employee Projects</h2>
            <div class="assignment-tool">
              <div class="assignment-controls">
                <label>Search Employees<input id="assignmentUserSearch" type="search" placeholder="Name, email, employee ID"></label>
                <label>Employee<select id="assignmentUser"></select></label>
                <label>Search Projects<input id="assignmentSearch" type="search" placeholder="Type project name"></label>
                <label>Show<select id="assignmentPageSize"><option value="5" selected>5</option><option value="10">10</option><option value="25">25</option><option value="50">50</option></select></label>
                <button id="selectVisibleProjects" type="button" class="button secondary">Select All Displayed Projects</button>
                <button id="clearVisibleProjects" type="button" class="button secondary">Clear Selection</button>
              </div>
              <div class="assignment-meta">
                <span id="assignmentCount">0 selected</span>
                <span id="assignmentVisibleCount">0 visible</span>
              </div>
              <div id="assignmentProjects" class="project-checks"></div>
              <div class="assignment-pager">
                <span id="assignmentPageInfo">Page 1</span>
                <div class="assignment-pager-actions">
                  <button id="assignmentPrevPage" type="button" class="button secondary">Previous</button>
                  <button id="assignmentNextPage" type="button" class="button secondary">Next</button>
                </div>
              </div>
              <div class="toolbar">
                <button id="saveAssignments" type="button">Save Assignments</button>
                <span id="assignmentMessage" class="message"></span>
              </div>
            </div>
          </section>
          <section id="portal-users" class="panel">
            <h2>Portal Users</h2>
            <div class="user-management">
              {users_msg}
              <form class="user-create-form" method="post" action="/admin/users#portal-users">
                <input type="hidden" name="csrf_token" value="{csrf}">
                <label>Employee name<input name="display_name" required></label>
                <label>Employee email<input name="username" type="email" required></label>
                <label>Portal password<input name="password" type="password" minlength="8" required></label>
                <label>Work phone<input name="work_phone" placeholder="Enter contact number"></label>
                <button type="submit">Create Login</button>
              </form>
              <form class="compact-form" method="post" action="/admin/users/sync#portal-users">
                <input type="hidden" name="csrf_token" value="{csrf}">
                <button type="submit" class="button secondary">Sync Odoo Employees</button>
                <span class="hint">New Odoo employees with work email receive the default portal password: admin. Change it immediately.</span>
              </form>
              <div class="user-list-head">
                <div class="user-list-tools">
                  <label>Search Users<input id="userSearch" type="search" placeholder="Name, email, role, status"></label>
                  <label>Show<select id="userPageSize"><option value="5" selected>5</option><option value="10">10</option><option value="25">25</option><option value="50">50</option></select></label>
                </div>
                <span id="userPageInfo" class="user-table-meta">Page 1</span>
              </div>
              <div class="toolbar">
                <button id="selectVisibleUsers" type="button" class="button secondary">Select All Displayed</button>
                <button id="clearSelectedUsers" type="button" class="button secondary">Clear Selection</button>
                <button id="archiveSelectedUsers" type="button" class="button secondary">Archive Selected</button>
                <button id="deleteSelectedUsers" type="button">Delete Selected</button>
                <span id="selectedUserCount" class="hint">0 selected</span>
              </div>
              <div class="table-wrap">
                <table><thead><tr><th>Select</th><th>Email</th><th>Name</th><th>Role</th><th>Odoo Employee ID</th><th>Status</th><th>Access</th><th>Reset Password</th></tr></thead><tbody id="portalUserRows">{rows}</tbody></table>
              </div>
              <div class="pager">
                <button id="userPrevPage" type="button">Previous</button>
                <span></span>
                <button id="userNextPage" type="button">Next</button>
              </div>
            </div>
          </section>
        </main>
        <script>
          const assignmentCsrf = "{csrf}";
          const assignmentUser = document.getElementById('assignmentUser');
          const assignmentUserSearch = document.getElementById('assignmentUserSearch');
          const assignmentProjects = document.getElementById('assignmentProjects');
          const assignmentMessage = document.getElementById('assignmentMessage');
          const assignmentSearch = document.getElementById('assignmentSearch');
          const assignmentCount = document.getElementById('assignmentCount');
          const assignmentVisibleCount = document.getElementById('assignmentVisibleCount');
          const assignmentPageSize = document.getElementById('assignmentPageSize');
          const assignmentPageInfo = document.getElementById('assignmentPageInfo');
          const assignmentPrevPage = document.getElementById('assignmentPrevPage');
          const assignmentNextPage = document.getElementById('assignmentNextPage');
          const approvalUser = document.getElementById('approvalUser');
          const employeeManagerManager = document.getElementById('employeeManagerManager');
          const employeeManagerSearch = document.getElementById('employeeManagerSearch');
          const employeeManagerSelected = document.getElementById('employeeManagerSelected');
          const employeeManagerList = document.getElementById('employeeManagerList');
          const employeeManagerMessage = document.getElementById('employeeManagerMessage');
          const approvalProjectList = document.getElementById('approvalProjectList');
          const approvalSelectedProjects = document.getElementById('approvalSelectedProjects');
          const approvalProjectSearch = document.getElementById('approvalProjectSearch');
          const approvalAssignmentMessage = document.getElementById('approvalAssignmentMessage');
          let assignmentData = {{ users: [], projects: [], assignments: {{}}, project_approvers: {{}}, employee_managers: {{}} }};
          let selectedManagerEmployees = new Set();
          let selectedApprovalProjects = new Set();
          let selectedProjects = new Set();
          let visibleProjects = [];
          let filteredProjects = [];
          let filteredAssignmentUsers = [];
          let assignmentPage = 1;
          const userRows = Array.from(document.querySelectorAll('.portal-user-row'));
          const selectedPortalUsers = new Set();
          const selectedUserCount = document.getElementById('selectedUserCount');
          const userSearch = document.getElementById('userSearch');
          const userPageSize = document.getElementById('userPageSize');
          const userPageInfo = document.getElementById('userPageInfo');
          const userPrevPage = document.getElementById('userPrevPage');
          const userNextPage = document.getElementById('userNextPage');
          let filteredUserRows = userRows;
          let userPage = 1;

          function setAssignmentMessage(text, type) {{
            assignmentMessage.textContent = text;
            assignmentMessage.className = 'message ' + (type || '');
          }}

          function setApprovalAssignmentMessage(text, type) {{
            approvalAssignmentMessage.textContent = text;
            approvalAssignmentMessage.className = 'message ' + (type || '');
          }}

          function renderEmployeeManagers() {{
            const prior = employeeManagerManager.value;
            employeeManagerManager.innerHTML = '';
            assignmentData.users.forEach(user => {{
              const managerOption = document.createElement('option'); managerOption.value = user.id; managerOption.textContent = user.display_name + ' (' + user.username + ')'; employeeManagerManager.appendChild(managerOption);
            }});
            if (prior) employeeManagerManager.value = prior;
            syncEmployeeManager();
          }}
          function syncEmployeeManager() {{
            const managerId = Number(employeeManagerManager.value);
            selectedManagerEmployees = new Set(assignmentData.users.filter(user => Number(user.id) !== managerId && Number(assignmentData.employee_managers[String(user.id)]) === managerId).map(user => Number(user.id)));
            renderSelectedManagerEmployees(); renderManagerEmployeeList();
          }}
          function renderSelectedManagerEmployees() {{
            employeeManagerSelected.innerHTML = '';
            assignmentData.users.filter(user => selectedManagerEmployees.has(Number(user.id))).forEach(user => {{
              const chip = document.createElement('span'); chip.className = 'selected-project'; chip.append(document.createTextNode(user.display_name));
              const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.title = 'Remove ' + user.display_name;
              remove.addEventListener('click', () => {{ selectedManagerEmployees.delete(Number(user.id)); renderSelectedManagerEmployees(); renderManagerEmployeeList(); }});
              chip.appendChild(remove); employeeManagerSelected.appendChild(chip);
            }});
          }}
          function renderManagerEmployeeList() {{
            const managerId = Number(employeeManagerManager.value); const query = employeeManagerSearch.value.trim().toLowerCase();
            employeeManagerList.innerHTML = '';
            const matches = assignmentData.users.filter(user => Number(user.id) !== managerId && [user.display_name,user.username].join(' ').toLowerCase().includes(query));
            if (!matches.length) {{ employeeManagerList.innerHTML = '<div class="empty-state">No employees match this search.</div>'; return; }}
            matches.forEach(user => {{
              const label = document.createElement('label'); label.className = 'check-row'; const input = document.createElement('input'); input.type = 'checkbox'; input.value = user.id; input.checked = selectedManagerEmployees.has(Number(user.id));
              input.addEventListener('change', () => {{ if (input.checked) selectedManagerEmployees.add(Number(user.id)); else selectedManagerEmployees.delete(Number(user.id)); renderSelectedManagerEmployees(); }});
              const text = document.createElement('span'); text.textContent = user.display_name + ' (' + user.username + ')'; label.append(input,text); employeeManagerList.appendChild(label);
            }});
          }}

          function renderApprovalAssignments() {{
            const priorUser = approvalUser.value;
            approvalUser.innerHTML = '';
            assignmentData.users.forEach(user => {{
              const option = document.createElement('option');
              option.value = user.id;
              option.textContent = user.display_name + ' (' + user.username + ')';
              approvalUser.appendChild(option);
            }});
            if (priorUser && assignmentData.users.some(user => String(user.id) === priorUser)) approvalUser.value = priorUser;
            syncSelectedApprovalAssignments();
            renderApprovalProjectList();
          }}

          function syncSelectedApprovalAssignments() {{
            const userId = Number(approvalUser.value);
            selectedApprovalProjects = new Set(assignmentData.projects.filter(project => (assignmentData.project_approvers[String(project.id)] || []).map(Number).includes(userId)).map(project => Number(project.id)));
            renderSelectedApprovalProjects();
          }}

          function renderSelectedApprovalProjects() {{
            approvalSelectedProjects.innerHTML = '';
            assignmentData.projects.filter(project => selectedApprovalProjects.has(Number(project.id))).forEach(project => {{
              const chip = document.createElement('span');
              chip.className = 'selected-project';
              chip.append(document.createTextNode(project.name));
              const remove = document.createElement('button');
              remove.type = 'button'; remove.title = 'Remove ' + project.name; remove.setAttribute('aria-label', 'Remove ' + project.name); remove.textContent = '×';
              remove.addEventListener('click', () => {{ selectedApprovalProjects.delete(Number(project.id)); renderSelectedApprovalProjects(); renderApprovalProjectList(); }});
              chip.appendChild(remove); approvalSelectedProjects.appendChild(chip);
            }});
          }}

          function renderApprovalProjectList() {{
            const query = approvalProjectSearch.value.trim().toLowerCase();
            approvalProjectList.innerHTML = '';
            const matches = assignmentData.projects.filter(project => project.name.toLowerCase().includes(query));
            if (!matches.length) {{ approvalProjectList.innerHTML = '<div class="empty-state">No projects match this search.</div>'; return; }}
            matches.forEach(project => {{
              const label = document.createElement('label'); label.className = 'check-row';
              const input = document.createElement('input'); input.type = 'checkbox'; input.value = project.id; input.checked = selectedApprovalProjects.has(Number(project.id));
              input.addEventListener('change', () => {{ if (input.checked) selectedApprovalProjects.add(Number(project.id)); else selectedApprovalProjects.delete(Number(project.id)); renderSelectedApprovalProjects(); }});
              const name = document.createElement('span'); name.textContent = project.name; name.title = project.name;
              label.append(input, name); approvalProjectList.appendChild(label);
            }});
          }}

          function renderUserPage() {{
            const query = userSearch.value.trim().toLowerCase();
            filteredUserRows = userRows.filter(row => row.textContent.toLowerCase().includes(query));
            const pageSize = Number(userPageSize.value || 5);
            const pageCount = Math.max(1, Math.ceil(filteredUserRows.length / pageSize));
            userPage = Math.min(Math.max(1, userPage), pageCount);
            const startIndex = (userPage - 1) * pageSize;
            const endIndex = startIndex + pageSize;
            userRows.forEach(row => row.style.display = 'none');
            filteredUserRows.forEach((row, index) => {{
              row.style.display = index >= startIndex && index < endIndex ? '' : 'none';
            }});
            const start = filteredUserRows.length ? startIndex + 1 : 0;
            const end = Math.min(filteredUserRows.length, endIndex);
            userPageInfo.textContent = filteredUserRows.length ? 'Showing ' + start + '-' + end + ' of ' + filteredUserRows.length : 'No users';
            userPrevPage.disabled = userPage <= 1;
            userNextPage.disabled = userPage >= pageCount;
            updateSelectedUserCount();
          }}

          function updateSelectedUserCount() {{
            selectedUserCount.textContent = selectedPortalUsers.size + ' selected';
            userRows.forEach(row => {{ const checkbox = row.querySelector('.portal-user-select'); if (checkbox && !checkbox.disabled) checkbox.checked = selectedPortalUsers.has(Number(checkbox.value)); }});
          }}

          async function applyBulkUserAction(action) {{
            if (!selectedPortalUsers.size) {{ setAssignmentMessage('Select at least one employee portal user.', 'err'); return; }}
            const label = action === 'delete' ? 'permanently delete' : 'archive';
            if (!confirm('This will ' + label + ' the selected employee(s) in both Odoo and the portal. Continue?')) return;
            try {{
              const res = await fetch('/api/portal-users/bulk-action', {{ method:'POST', headers:{{'Content-Type':'application/json','X-CSRF-Token':assignmentCsrf}}, body:JSON.stringify({{user_ids:Array.from(selectedPortalUsers),action}}) }});
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Could not update users.');
              selectedPortalUsers.clear();
              setAssignmentMessage(data.count + ' employee portal user(s) ' + (action === 'delete' ? 'deleted.' : 'archived.'), 'ok');
              window.location.reload();
            }} catch (error) {{ setAssignmentMessage(error.message, 'err'); }}
          }}

          function syncAssignmentCounts() {{
            assignmentCount.textContent = selectedProjects.size + ' selected';
            assignmentVisibleCount.textContent = filteredProjects.length + ' matching';
            const pageSize = Number(assignmentPageSize.value || 5);
            const pageCount = Math.max(1, Math.ceil(filteredProjects.length / pageSize));
            const start = filteredProjects.length ? ((assignmentPage - 1) * pageSize) + 1 : 0;
            const end = Math.min(filteredProjects.length, assignmentPage * pageSize);
            assignmentPageInfo.textContent = filteredProjects.length ? 'Showing ' + start + '-' + end + ' of ' + filteredProjects.length : 'No projects';
            assignmentPrevPage.disabled = assignmentPage <= 1;
            assignmentNextPage.disabled = assignmentPage >= pageCount;
          }}

          function renderAssignmentUsers() {{
            const previousUser = assignmentUser.value;
            const query = assignmentUserSearch.value.trim().toLowerCase();
            filteredAssignmentUsers = assignmentData.users.filter(user => {{
              const employeeId = user.odoo_employee_id ? String(user.odoo_employee_id) : '';
              const haystack = [user.display_name, user.username, employeeId].join(' ').toLowerCase();
              return haystack.includes(query);
            }});
            assignmentUser.innerHTML = '';
            filteredAssignmentUsers.forEach(user => {{
              const option = document.createElement('option');
              option.value = user.id;
              option.textContent = user.display_name + ' (' + user.username + ')';
              assignmentUser.appendChild(option);
            }});
            if (previousUser && filteredAssignmentUsers.some(user => String(user.id) === previousUser)) {{
              assignmentUser.value = previousUser;
            }}
          }}

          function renderProjectList() {{
            const query = assignmentSearch.value.trim().toLowerCase();
            filteredProjects = assignmentData.projects.filter(project => project.name.toLowerCase().includes(query));
            const pageSize = Number(assignmentPageSize.value || 5);
            const pageCount = Math.max(1, Math.ceil(filteredProjects.length / pageSize));
            assignmentPage = Math.min(Math.max(1, assignmentPage), pageCount);
            visibleProjects = filteredProjects.slice((assignmentPage - 1) * pageSize, assignmentPage * pageSize);
            assignmentProjects.innerHTML = '';
            if (!assignmentData.projects.length) {{
              assignmentProjects.innerHTML = '<div class="empty-state">No timesheet-enabled projects found.</div>';
              syncAssignmentCounts();
              return;
            }}
            if (!visibleProjects.length) {{
              assignmentProjects.innerHTML = '<div class="empty-state">No projects match this search.</div>';
              syncAssignmentCounts();
              return;
            }}
            visibleProjects.forEach(project => {{
              const label = document.createElement('label');
              label.className = 'check-row';
              const input = document.createElement('input');
              input.type = 'checkbox';
              input.value = project.id;
              input.checked = selectedProjects.has(Number(project.id));
              input.addEventListener('change', () => {{
                const projectId = Number(input.value);
                if (input.checked) selectedProjects.add(projectId);
                else selectedProjects.delete(projectId);
                syncAssignmentCounts();
              }});
              const span = document.createElement('span');
              span.title = project.name;
              span.textContent = project.name;
              label.appendChild(input);
              label.appendChild(span);
              assignmentProjects.appendChild(label);
            }});
            syncAssignmentCounts();
          }}

          function loadSelectedProjectsForUser() {{
            const selectedUser = assignmentUser.value;
            selectedProjects = new Set((assignmentData.assignments[selectedUser] || []).map(Number));
            assignmentSearch.value = '';
            assignmentPage = 1;
            renderProjectList();
          }}

          async function loadAssignments() {{
            setAssignmentMessage('Loading assignments...', '');
            const res = await fetch('/api/project-assignments');
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not load assignments');
            assignmentData = data;
            renderAssignmentUsers();
            loadSelectedProjectsForUser();
            renderApprovalAssignments();
            renderEmployeeManagers();
            setAssignmentMessage(data.users.length ? 'Ready.' : 'Create an employee login first.', data.users.length ? 'ok' : 'err');
          }}

          assignmentUserSearch.addEventListener('input', () => {{
            const previousUser = assignmentUser.value;
            renderAssignmentUsers();
            if (!filteredAssignmentUsers.length) {{
              selectedProjects = new Set();
              assignmentProjects.innerHTML = '<div class="empty-state">No employees match this search.</div>';
              syncAssignmentCounts();
              setAssignmentMessage('No employees match this search.', 'err');
              return;
            }}
            loadSelectedProjectsForUser();
            if (assignmentUser.value !== previousUser) setAssignmentMessage('Showing first matching employee.', 'ok');
          }});
          assignmentUser.addEventListener('change', loadSelectedProjectsForUser);
          approvalUser.addEventListener('change', () => {{ syncSelectedApprovalAssignments(); renderApprovalProjectList(); }});
          employeeManagerManager.addEventListener('change', syncEmployeeManager);
          employeeManagerSearch.addEventListener('input', renderManagerEmployeeList);
          document.getElementById('saveEmployeeManager').addEventListener('click', async () => {{
            try {{
              const managerId = Number(employeeManagerManager.value);
              if (!managerId) throw new Error('Select a manager.');
              const res = await fetch('/api/manager-employees', {{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':assignmentCsrf}},body:JSON.stringify({{manager_user_id:managerId,employee_user_ids:Array.from(selectedManagerEmployees)}})}});
              const data = await res.json(); if (!res.ok) throw new Error(data.error || 'Could not save employee manager.');
              Object.keys(assignmentData.employee_managers).forEach(userId => {{ if (Number(assignmentData.employee_managers[userId]) === managerId) delete assignmentData.employee_managers[userId]; }});
              data.employee_user_ids.forEach(userId => assignmentData.employee_managers[String(userId)] = managerId);
              employeeManagerMessage.textContent = data.employee_user_ids.length + ' employee manager assignment(s) saved.'; employeeManagerMessage.className = 'message ok';
            }} catch (error) {{ employeeManagerMessage.textContent = error.message; employeeManagerMessage.className = 'message err'; }}
          }});
          approvalProjectSearch.addEventListener('input', renderApprovalProjectList);
          document.getElementById('saveApprovalAssignments').addEventListener('click', async () => {{
            try {{
              const userId = Number(approvalUser.value);
              if (!userId) throw new Error('Select an approver.');
              const projectIds = Array.from(selectedApprovalProjects);
              setApprovalAssignmentMessage('Saving approval assignments...', '');
              const res = await fetch('/api/approval-assignments', {{
                method: 'POST', headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': assignmentCsrf }},
                body: JSON.stringify({{ user_id: userId, project_ids: projectIds }})
              }});
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Could not save approval assignments.');
              Object.keys(assignmentData.project_approvers).forEach(projectId => {{ assignmentData.project_approvers[projectId] = assignmentData.project_approvers[projectId].filter(id => Number(id) !== userId); if (!assignmentData.project_approvers[projectId].length) delete assignmentData.project_approvers[projectId]; }});
              data.project_ids.forEach(projectId => {{ (assignmentData.project_approvers[String(projectId)] ||= []).push(userId); }});
              setApprovalAssignmentMessage(data.project_ids.length ? 'Approval assignments saved.' : 'Approval requirement removed for this approver.', 'ok');
            }} catch (error) {{ setApprovalAssignmentMessage(error.message, 'err'); }}
          }});
          assignmentSearch.addEventListener('input', () => {{
            assignmentPage = 1;
            renderProjectList();
          }});
          assignmentPageSize.addEventListener('change', () => {{
            assignmentPage = 1;
            renderProjectList();
          }});
          assignmentPrevPage.addEventListener('click', () => {{
            if (assignmentPage > 1) {{
              assignmentPage -= 1;
              renderProjectList();
            }}
          }});
          assignmentNextPage.addEventListener('click', () => {{
            const pageSize = Number(assignmentPageSize.value || 5);
            const pageCount = Math.max(1, Math.ceil(filteredProjects.length / pageSize));
            if (assignmentPage < pageCount) {{
              assignmentPage += 1;
              renderProjectList();
            }}
          }});
          document.getElementById('selectVisibleProjects').addEventListener('click', () => {{
            visibleProjects.forEach(project => selectedProjects.add(Number(project.id)));
            renderProjectList();
          }});
          document.getElementById('clearVisibleProjects').addEventListener('click', () => {{
            visibleProjects.forEach(project => selectedProjects.delete(Number(project.id)));
            renderProjectList();
          }});
          document.getElementById('saveAssignments').addEventListener('click', async () => {{
            try {{
              const payload = {{
                user_id: Number(assignmentUser.value),
                project_ids: Array.from(selectedProjects)
              }};
              if (!payload.user_id) throw new Error('Select an employee.');
              setAssignmentMessage('Saving assignments...', '');
              const res = await fetch('/api/project-assignments', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': assignmentCsrf }},
                body: JSON.stringify(payload)
              }});
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || 'Could not save assignments');
              assignmentData.assignments[String(data.user_id)] = data.project_ids;
              selectedProjects = new Set(data.project_ids.map(Number));
              renderProjectList();
              setAssignmentMessage('Assignments saved.', 'ok');
            }} catch (error) {{
              setAssignmentMessage(error.message, 'err');
            }}
          }});
          userPageSize.addEventListener('change', () => {{
            userPage = 1;
            renderUserPage();
          }});
          userSearch.addEventListener('input', () => {{
            userPage = 1;
            renderUserPage();
          }});
          userPrevPage.addEventListener('click', () => {{
            if (userPage > 1) {{
              userPage -= 1;
              renderUserPage();
            }}
          }});
          userNextPage.addEventListener('click', () => {{
            const pageSize = Number(userPageSize.value || 5);
            const pageCount = Math.max(1, Math.ceil(filteredUserRows.length / pageSize));
            if (userPage < pageCount) {{
              userPage += 1;
              renderUserPage();
            }}
          }});
          document.querySelectorAll('.portal-user-select').forEach(checkbox => checkbox.addEventListener('change', () => {{ if (checkbox.checked) selectedPortalUsers.add(Number(checkbox.value)); else selectedPortalUsers.delete(Number(checkbox.value)); updateSelectedUserCount(); }}));
          document.getElementById('selectVisibleUsers').addEventListener('click', () => {{ userRows.filter(row => row.style.display !== 'none').forEach(row => {{ const checkbox = row.querySelector('.portal-user-select'); if (checkbox && !checkbox.disabled) selectedPortalUsers.add(Number(checkbox.value)); }}); updateSelectedUserCount(); }});
          document.getElementById('clearSelectedUsers').addEventListener('click', () => {{ selectedPortalUsers.clear(); updateSelectedUserCount(); }});
          document.getElementById('archiveSelectedUsers').addEventListener('click', () => applyBulkUserAction('archive'));
          document.getElementById('deleteSelectedUsers').addEventListener('click', () => applyBulkUserAction('delete'));
          document.querySelectorAll('.user-status-form').forEach(form => {{
            form.addEventListener('submit', async event => {{
              event.preventDefault();
              const button = form.querySelector('[data-status-button]');
              const statusInput = form.querySelector('[name="active"]');
              const row = form.closest('tr');
              const statusCell = row.querySelector('[data-status-cell]');
              button.disabled = true;
              try {{
                const body = new FormData(form);
                const res = await fetch('/admin/users/status', {{ method: 'POST', body }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Could not update access.');
                statusCell.textContent = data.active ? 'Active' : 'Inactive';
                statusInput.value = data.active ? '0' : '1';
                button.textContent = data.active ? 'Deactivate' : 'Activate';
                renderUserPage();
                loadAssignments().catch(() => {{}});
              }} catch (error) {{
                button.textContent = statusInput.value === '1' ? 'Activate' : 'Deactivate';
              }} finally {{
                button.disabled = false;
              }}
            }});
          }});
          renderUserPage();
          loadAssignments().catch(error => setAssignmentMessage(error.message, 'err'));
        </script>
        """,
    )


def account_page(user: dict[str, Any], message: str = "", is_error: bool = False, load_profile: bool = True) -> HTMLResponse:
    csrf = html.escape(user["csrf_token"])
    msg_class = "err" if is_error else "ok"
    msg = f"<div class='message {msg_class}'>{html.escape(message)}</div>" if message else ""
    if load_profile:
        try:
            profile = employee_profile(user.get("odoo_employee_id"))
        except Exception:
            profile = {"name": "", "work_email": "", "work_phone": "", "job_title": ""}
    else:
        profile = {"name": "", "work_email": "", "work_phone": "", "job_title": ""}
    display_name = profile.get("name") or user.get("display_name", "")
    email = profile.get("work_email") or user.get("username", "")
    return page(
        "My Account",
        user,
        f"""
        <main class="stack">
          <div class="tabs"><a href="/">Timesheet</a></div>
          <section class="panel">
            <h2>Account Summary</h2>
            <div class="metric"><strong>{html.escape(user["display_name"])}</strong><span>Portal user</span></div>
            <div class="metric"><strong>{html.escape(str(user.get("odoo_employee_id") or "Not mapped"))}</strong><span>Odoo employee ID</span></div>
            <div class="metric"><strong id="accountProjectCount">Loading...</strong><span>Timesheet-enabled projects</span></div>
          </section>
          <section class="panel">
            <h2>Update Profile</h2>
            <form method="post" action="/account/profile">
              <input type="hidden" name="csrf_token" value="{csrf}">
              <label>Name<input name="display_name" value="{html.escape(display_name)}" required></label>
              <label>Email<input name="email" type="email" value="{html.escape(email)}" required></label>
              <label>Contact Number<input name="work_phone" value="{html.escape(profile.get('work_phone', ''))}" placeholder="Enter contact number"></label>
              <label class="wide">Job Title<input name="job_title" value="{html.escape(profile.get('job_title', ''))}"></label>
              <button type="submit">Update Profile</button>{msg}
            </form>
            <p class="hint">Profile changes update this portal account and the linked Odoo employee record.</p>
          </section>
          <section class="panel">
            <h2>Change Password</h2>
            <form method="post" action="/account/password">
              <input type="hidden" name="csrf_token" value="{csrf}">
              <label>Current password<input name="current_password" type="password" required></label>
              <label>New password<input name="new_password" type="password" minlength="8" required></label>
              <label class="wide">Confirm new password<input name="confirm_password" type="password" minlength="8" required></label>
              <button type="submit">Change Password</button>
            </form>
          </section>
        </main>
        <script>
          fetch('/api/bootstrap')
            .then(response => response.ok ? response.json() : Promise.reject())
            .then(data => {{
              document.getElementById('accountProjectCount').textContent = data.projects.length;
            }})
            .catch(() => {{
              document.getElementById('accountProjectCount').textContent = 'Unavailable';
            }});
        </script>
        """,
    )


@app.on_event("startup")
def startup() -> None:
    migrate_db()
    threading.Thread(target=employee_sync_worker, name="employee-sync", daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Any:
    if users_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return dashboard_page(user)


@app.get("/setup", response_class=HTMLResponse)
async def setup_get() -> Any:
    if users_count() > 0:
        return RedirectResponse("/login", status_code=303)
    return setup_page()


@app.post("/setup", response_class=HTMLResponse)
async def setup_post(request: Request) -> Any:
    if users_count() > 0:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    password = str(form.get("password", ""))
    if len(password) < 8:
        return setup_page("Password must be at least 8 characters.", True)
    with conn() as db:
        db.execute(
            """
            insert into users (username,password_hash,display_name,is_admin,active,created_at)
            values (?,?,?,?,1,?)
            """,
            (str(form.get("username", "")).strip(), password_hash(password), str(form.get("display_name", "")).strip(), 1, now()),
        )
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_get() -> Any:
    if users_count() == 0:
        return RedirectResponse("/setup", status_code=303)
    return login_page()


@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request) -> Any:
    if not login_allowed(request):
        return login_page("Too many login attempts. Please wait five minutes and try again.")
    form = await request.form()
    user = authenticate(str(form.get("username", "")), str(form.get("password", "")))
    if not user:
        return login_page("Invalid email or password.")
    clear_login_attempts(request)
    token, _csrf = create_session(user["id"])
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    audit(user["id"], "auth.login")
    return response


@app.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    delete_session(request.cookies.get(SESSION_COOKIE, ""))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
async def admin_get(request: Request) -> HTMLResponse:
    user = require_admin(request)
    return admin_page(user)


@app.get("/account", response_class=HTMLResponse)
async def account_get(request: Request) -> HTMLResponse:
    user = require_user(request)
    return await run_in_threadpool(account_page, user)


@app.post("/account/profile", response_class=HTMLResponse)
async def account_profile(request: Request) -> HTMLResponse:
    user = require_user(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    display_name = str(form.get("display_name", "")).strip()
    email = str(form.get("email", "")).strip()
    work_phone = str(form.get("work_phone", "")).strip()
    job_title = str(form.get("job_title", "")).strip()
    try:
        update_portal_profile(user["id"], email, display_name)
        if user.get("odoo_employee_id"):
            await run_in_threadpool(
                update_employee_profile,
                int(user["odoo_employee_id"]),
                {
                    "name": display_name,
                    "work_email": email,
                    "work_phone": work_phone,
                    "job_title": job_title,
                },
            )
        audit(user["id"], "user.profile.update", {"user_id": user["id"], "email": email})
        refreshed = portal_user(user["id"]) or user
        refreshed["csrf_token"] = user["csrf_token"]
        return await run_in_threadpool(account_page, refreshed, "Profile updated.")
    except Exception as exc:
        return await run_in_threadpool(account_page, user, str(exc), True)


@app.post("/account/password", response_class=HTMLResponse)
async def account_password(request: Request) -> HTMLResponse:
    user = require_user(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    current_password = str(form.get("current_password", ""))
    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    if not password_ok(current_password, user["password_hash"]):
        return await run_in_threadpool(account_page, user, "Current password is incorrect.", True, False)
    if new_password != confirm_password:
        return await run_in_threadpool(account_page, user, "New password and confirmation do not match.", True, False)
    try:
        set_user_password(user["id"], new_password)
        audit(user["id"], "user.password.change", {"user_id": user["id"]})
        return await run_in_threadpool(account_page, user, "Password changed.", False, False)
    except Exception as exc:
        return await run_in_threadpool(account_page, user, str(exc), True, False)


@app.post("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request) -> HTMLResponse:
    user = require_admin(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    odoo_password = str(form.get("odoo_password", ""))
    odoo_url = str(form.get("odoo_url", "")).strip().rstrip("/")
    odoo_db = str(form.get("odoo_db", "")).strip()
    odoo_login = str(form.get("odoo_login", "")).strip()
    previous = settings()
    reset_required = bool(previous.get("odoo_db")) and (previous.get("odoo_url", "") != odoo_url or previous.get("odoo_db", "") != odoo_db)
    if reset_required:
        await run_in_threadpool(reset_connection_data, int(user["id"]))
    with conn() as db:
        set_setting(db, "odoo_url", odoo_url)
        set_setting(db, "odoo_db", odoo_db)
        set_setting(db, "odoo_login", odoo_login)
        if odoo_password:
            set_setting(db, "odoo_password", odoo_password)
    cache_delete_prefix("odoo_uid:")
    cache_delete_prefix("bootstrap:")
    cache_delete_prefix("employee_profile:")
    cache_delete_prefix("timesheets:")
    try:
        if form.get("test"):
            uid = await run_in_threadpool(odoo_uid)
            message = f"Odoo connection saved and tested. Connected user ID: {uid}."
        else:
            message = "Odoo connection saved." + (" Previous database portal data was reset." if reset_required else "")
        audit(user["id"], "settings.odoo.update")
        return await run_in_threadpool(admin_page, user, message, False, "odoo")
    except Exception as exc:
        return await run_in_threadpool(admin_page, user, f"Settings saved, but Odoo test failed: {exc}", True, "odoo")


@app.post("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request) -> HTMLResponse:
    user = require_admin(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    username = str(form.get("username", "")).strip()
    display_name = str(form.get("display_name", "")).strip()
    password = str(form.get("password", ""))
    work_phone = str(form.get("work_phone", "")).strip()
    try:
        with conn() as db:
            if db.execute("select 1 from users where lower(username)=lower(?)", (username,)).fetchone():
                raise ValueError("A portal user with this email already exists.")
        employee_id = await run_in_threadpool(create_odoo_employee, display_name, username, work_phone)
        create_app_user(username, password, display_name, employee_id)
        audit(user["id"], "user.create", {"username": username, "employee_id": employee_id})
        return await run_in_threadpool(admin_page, user, f"Employee and portal login created. Odoo employee ID: {employee_id}.", False, "users")
    except Exception as exc:
        return await run_in_threadpool(admin_page, user, str(exc), True, "users")


@app.post("/admin/users/sync", response_class=HTMLResponse)
async def admin_users_sync(request: Request) -> HTMLResponse:
    user = require_admin(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    try:
        result = await run_in_threadpool(sync_odoo_employees, int(user["id"]))
        message = "Odoo sync complete: " + ", ".join(f"{key} {value}" for key, value in result.items())
        return await run_in_threadpool(admin_page, user, message, False, "users")
    except Exception as exc:
        return await run_in_threadpool(admin_page, user, f"Odoo employee sync failed: {exc}", True, "users")


@app.post("/admin/users/password", response_class=HTMLResponse)
async def admin_user_password(request: Request) -> HTMLResponse:
    user = require_admin(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    target_id = int(str(form.get("user_id", "0")) or "0")
    password = str(form.get("password", ""))
    target = portal_user(target_id)
    if not target:
        return await run_in_threadpool(admin_page, user, "Portal user not found.", True, "users")
    try:
        set_user_password(target_id, password)
        audit(user["id"], "admin.password.reset", {"target_user_id": target_id, "target_username": target["username"]})
        return await run_in_threadpool(admin_page, user, f"Password reset for {target['username']}.", False, "users")
    except Exception as exc:
        return await run_in_threadpool(admin_page, user, str(exc), True, "users")


@app.post("/admin/users/status")
async def admin_user_status(request: Request) -> JSONResponse:
    user = require_admin(request)
    form = await request.form()
    verify_csrf(request, str(form.get("csrf_token", "")))
    target_id = int(str(form.get("user_id", "0")) or "0")
    active = str(form.get("active", "0")) == "1"
    try:
        return JSONResponse(set_user_active(user, target_id, active))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/portal-users/bulk-action")
async def api_portal_users_bulk_action(request: Request, payload: BulkUserActionPayload) -> JSONResponse:
    user = require_admin(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(bulk_manage_portal_users, user, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/bootstrap")
async def api_bootstrap(request: Request) -> JSONResponse:
    user = require_user(request)
    try:
        if request.query_params.get("refresh") == "1":
            cache_delete_prefix("bootstrap:")
        return JSONResponse(await run_in_threadpool(bootstrap_data_for_user, user))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/project-assignments")
async def api_project_assignments(request: Request) -> JSONResponse:
    require_admin(request)
    try:
        cache_delete_prefix("bootstrap:")
        data = await run_in_threadpool(bootstrap_data)
        return JSONResponse(
            {
                "users": [
                    {
                        "id": user["id"],
                        "username": user["username"],
                        "display_name": user["display_name"],
                        "odoo_employee_id": user["odoo_employee_id"],
                    }
                    for user in assignable_users()
                ],
                "projects": data["projects"],
                "assignments": project_assignments(),
                "project_approvers": project_approvers(),
                "employee_managers": employee_managers(),
            }
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/approval-assignments")
async def api_approval_assignments_save(request: Request, payload: ApprovalAssignmentPayload) -> JSONResponse:
    user = require_admin(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(set_approval_assignments, user, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/employee-managers")
async def api_employee_managers_save(request: Request, payload: EmployeeManagerPayload) -> JSONResponse:
    user = require_admin(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(set_employee_manager, user, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/manager-employees")
async def api_manager_employees_save(request: Request, payload: ManagerEmployeesPayload) -> JSONResponse:
    user = require_admin(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(set_manager_employees, user, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/my-approvals")
async def api_my_approvals(request: Request) -> JSONResponse:
    user = require_user(request)
    try:
        return JSONResponse({"approvals": await run_in_threadpool(pending_approvals_for_manager, user)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/approvals/{approval_id}/approve")
async def api_approval_approve(request: Request, approval_id: int, payload: ApprovalDecisionPayload) -> JSONResponse:
    user = require_user(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(decide_timesheet_approval, user, approval_id, True, payload.note))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/approvals/{approval_id}/reject")
async def api_approval_reject(request: Request, approval_id: int, payload: ApprovalDecisionPayload) -> JSONResponse:
    user = require_user(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(decide_timesheet_approval, user, approval_id, False, payload.note))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/project-assignments")
async def api_project_assignments_save(request: Request, payload: ProjectAssignmentPayload) -> JSONResponse:
    user = require_admin(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(set_project_assignments, user, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/my-timesheets")
async def api_my_timesheets(request: Request) -> JSONResponse:
    user = require_user(request)
    try:
        params = request.query_params
        project_id = int(params["project_id"]) if params.get("project_id") else None
        data = await run_in_threadpool(
            my_timesheets,
            user,
            int(params.get("page", "1")),
            int(params.get("page_size", "20")),
            params.get("date_from", ""),
            params.get("date_to", ""),
            project_id,
            params.get("search", ""),
        )
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/timesheets")
async def api_timesheets(request: Request, payload: TimesheetBatchPayload) -> JSONResponse:
    user = require_user(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(create_timesheets, user, payload), status_code=201)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.put("/api/timesheets/{line_id}")
async def api_timesheet_update(request: Request, line_id: int, payload: TimesheetUpdatePayload) -> JSONResponse:
    user = require_user(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(update_timesheet, user, line_id, payload))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/timesheets/{line_id}")
async def api_timesheet_delete(request: Request, line_id: int) -> JSONResponse:
    user = require_user(request)
    verify_csrf(request, request.headers.get("X-CSRF-Token", ""))
    try:
        return JSONResponse(await run_in_threadpool(delete_timesheet, user, line_id))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "database": str(DB_PATH)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("portal_app:app", host=HOST, port=PORT, reload=False)
