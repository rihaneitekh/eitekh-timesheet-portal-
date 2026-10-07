# Downloaded Timesheet Portal: setup and GitHub upload

This copy contains the running server project's Python source, dependency list,
README and architecture document. These four files were copied without changes
and verified against SHA-256 checksums on the server. The server was not changed.

The live portal is a standalone FastAPI application integrating with Odoo; it is
not an installable Odoo addon. Its running application is `portal_app:app`.

## What is included

- `portal_app.py`: application, embedded pages, authentication, portal storage and Odoo integration.
- `requirements.txt`: server project's pinned Python dependencies.
- `README.md` and `PROJECT_ARCHITECTURE.md`: original project documentation.
- `.gitignore`: excludes credentials, SQLite data, environments, backups and logs.
- `.env.example`: blank configuration template; contains no production credentials.

The production database, users, sessions, saved Odoo connection credentials,
virtual environment, caches and backups are excluded. This is a source-code
download, not a production-data backup or complete server image. Starting the
downloaded project creates a new local portal database.

Some original architecture instructions refer to an older developer path and
older functionality. Use the source code and the setup instructions below for
this downloaded version.

## Run locally on Windows PowerShell

Use Python 3.10 or newer; the remote process uses Python 3.12.

```powershell
cd 'path\to\timesheet-portal'
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:HOST = '127.0.0.1'
$env:PORT = '8081'
$env:COOKIE_SECURE = '0'
$env:PORTAL_DB = Join-Path (Get-Location) 'timesheet_portal.sqlite3'
.\.venv\Scripts\python.exe -m uvicorn portal_app:app --host 127.0.0.1 --port 8081
```

Open http://127.0.0.1:8081 and create a local administrator with the initial setup
screen. This fresh copy does not include the production account or password.
Configure an authorized Odoo connection in the administrator UI when needed.

The app does not automatically load `.env` files. `.env.example` documents
supported process environment variables. Set actual values in your shell or
service configuration. Leave optional Odoo variables blank for initial local
setup. Use `COOKIE_SECURE=1` behind HTTPS in production. Set a private employee
bootstrap password before syncing employees; the original source retains its
existing fallback behavior.

## Upload to GitHub in a browser

1. Create a new repository in your GitHub account, for example `timesheet-portal`.
2. Choose **uploading an existing file** or **Add file > Upload files**.
3. Upload the contents of the `timesheet-portal` folder, including `.gitignore`
   and `.env.example`, then commit the upload. Upload the extracted files so
   GitHub displays the source; uploading just the ZIP stores an archive.
4. Choose repository visibility to suit your organization.

Do not upload the sibling `source-original` folder or the entire download folder;
the prepared `timesheet-portal` folder is the repository root.

If using Git locally instead of the browser, open a terminal inside this folder:

```text
git init
git add .
git commit -m "Import timesheet portal source"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/timesheet-portal.git
git push -u origin main
```

Replace `YOUR_ACCOUNT` with your GitHub username or organization. Use your own
GitHub authentication. No repository was created or published by this download.

## Verification performed

- Four downloaded files checked against server-side SHA-256 checksums.
- Running process confirmed as `portal_app:app` in the downloaded server folder.
- Python source parsed and compiled for syntax without executing the app.
- ZIP contents checked against the prepared files.
- Database, runtime files and the supplied access passwords excluded.

Application runtime, database migrations, Odoo connectivity and end-to-end
workflows were not tested by this source download.
