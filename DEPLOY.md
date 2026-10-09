# Deploying FieldServicePro to Render

This setup uses **paid plans** for both the web service and the PostgreSQL
database. The database is provisioned **separately** from the blueprint so
its lifecycle is independent of the web service.

## Prerequisites

- GitHub repository connected to Render
- Branch to deploy: `master`
- A Render account with billing enabled

---

## Step 1 — Create the PostgreSQL database (manual, one-time)

1. Render Dashboard → **New** → **PostgreSQL**
2. Settings:
   - **Name**: `fieldservicepro-db`
   - **Database**: `fieldservicepro`
   - **User**: `fsp_admin`
   - **Region**: pick the same region you'll use for the web service (defaults
     in `render.yaml` to `oregon` — change both together if needed)
   - **Plan**: any paid plan (Basic-256MB or higher)
3. After provisioning, copy the **Internal Connection String** (starts with
   `postgresql://...internal`). You'll paste this in Step 3.

> Internal Connection String is preferred — it doesn't traverse the public
> internet and isn't bandwidth-metered.

---

## Step 2 — Deploy the web service via Blueprint

1. Render Dashboard → **New** → **Blueprint**
2. Connect the GitHub repo and select the `master` branch
3. Render auto-detects `render.yaml` and creates:
   - **Web Service**: `fieldservicepro` (Starter plan)
   - **Persistent Disk**: `fsp-uploads` (10 GB, mounted at `/var/data/uploads`)
4. The following env vars are auto-configured by the blueprint:
   - `PYTHON_VERSION` = `3.11.4`
   - `FLASK_ENV` = `production`
   - `SECRET_KEY` (auto-generated)
   - `UPLOAD_FOLDER` = `/var/data/uploads`

---

## Step 3 — Set required env vars in the Render dashboard

Open the web service → **Environment** tab and set:

| Variable | Required? | Value |
|---|---|---|
| `DATABASE_URL` | **YES** | Internal Connection String from Step 1 |
| `ANTHROPIC_API_KEY` | optional | Shared Anthropic API key (see below) — enables AI chat panel |
| `MAIL_SERVER` | optional | SMTP host (e.g. `smtp.sendgrid.net`) |
| `MAIL_PORT` | optional | usually `587` |
| `MAIL_USE_TLS` | optional | `true` |
| `MAIL_USERNAME` | optional | SMTP username |
| `MAIL_PASSWORD` | optional | SMTP password |
| `MAIL_DEFAULT_SENDER` | optional | `noreply@yourdomain.com` |

Without `ANTHROPIC_API_KEY` the AI chat returns 503 (graceful).

**LLM API key:** the key is the shared secret `Demo-Apps-Share-API-Key` in Azure Key Vault `kv-demo-apps-shared` (subscription "Demo Apps"). Fetch it with:

```
az keyvault secret show --vault-name kv-demo-apps-shared --name Demo-Apps-Share-API-Key --subscription "Demo Apps" --query value -o tsv
```

The model defaults to `claude-sonnet-5-5` (override with `CLAUDE_MODEL`).

Without `MAIL_*` all emails log to console only (no failure).

Click **Save Changes** — Render will redeploy.

---

## Step 4 — Post-deploy verification

1. **Watch deploy logs** — look for:
   - `==> Build complete.`
   - `Database tables initialized successfully.`
   - `FieldServicePro app initialized (production=True)`
   - `Listening at: http://0.0.0.0:$PORT (gunicorn)`
2. **Health check** — `GET https://your-app.onrender.com/health` → `{"status":"healthy","database":"connected"}`
3. **Demo account** — visit `/demo` to auto-create a pre-loaded demo org
4. **Register a real account** at `/auth/register`
5. **Upload a file** (any document) → reload after a few minutes → confirm it persists (validates the disk mount)
6. **AI chat** (only if `ANTHROPIC_API_KEY` set) — open the chat panel from the dashboard

---

## Notes & Operations

- **Schema**: tables are auto-created on first startup via SQLAlchemy
  `Base.metadata.create_all()` in `init_db()`. No Alembic migrations needed
  for a fresh deploy.
- **Future schema changes**: the `migrate_*.py` scripts in the repo are
  SQLite-only. For production schema changes, either (a) add columns via
  manual `psql` ALTER TABLE, or (b) introduce Alembic.
- **Uploads**: stored on the persistent disk at `/var/data/uploads`. Disk is
  zone-pinned and survives deploys/restarts.
- **Backups**: Render paid Postgres includes daily backups; verify the
  retention policy on your plan.
- **Region affinity**: web service and database must be in the same Render
  region for the Internal Connection String to work. Default in this
  blueprint is `oregon` — update `render.yaml` if you provision the DB in
  another region.
- **Scaling**: bump `plan:` in `render.yaml` (starter → standard → pro) and
  consider raising `--workers` in the start command once the instance has
  more RAM. Rule of thumb: `(2 × CPU) + 1` workers.
- **Custom domain & TLS**: add it in the dashboard under **Settings →
  Custom Domains**. Talisman in `web/app.py` already enforces HTTPS-redirect
  and HSTS when `FLASK_ENV=production`.
