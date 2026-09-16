# Chainlit Conversation Logging And Dashboard On Railway

This runbook documents the reusable pattern used in this project to add conversation logging and a separate dashboard to a Chainlit chatbot deployed on Railway.

The important idea is simple:

- Keep the Chainlit chatbot as the primary service.
- Add Railway Postgres as the shared persistence layer.
- Use Chainlit's native `SQLAlchemyDataLayer` so conversations are stored in Chainlit's own tables.
- Add a second Railway service, a small FastAPI dashboard, that reads from those same Chainlit tables.

This avoids custom message interception in the chatbot and keeps the dashboard independent from chat traffic.

## References

- Chainlit SQLAlchemy data layer: https://docs.chainlit.io/data-layers/sqlalchemy
- Railway CLI deployment: https://docs.railway.com/cli/deploying
- Railway PostgreSQL: https://docs.railway.com/databases/postgresql
- Railway variables and reference variables: https://docs.railway.com/variables
- Railway deployment dependency ordering: https://docs.railway.com/deployments/deployment-actions

## Target Architecture

Use three Railway services in one Railway project:

| Service | Purpose | Example name |
| --- | --- | --- |
| Chatbot | Existing Chainlit app | `EverydayAI` |
| Database | PostgreSQL used by Chainlit and dashboard | `Postgres` |
| Dashboard | FastAPI app that reads Chainlit tables | `ConversationDashboard` |

The `DATABASE_URL` variable should be configured on both app services as a Railway reference variable:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

This keeps the database URL out of source code and lets Railway wire service startup order through the reference.

## Prerequisites

You need:

- A working Chainlit app.
- A Railway project.
- Railway CLI installed and logged in.
- The Chainlit app deployed as a Railway service.
- `GROQ_API_KEY` configured on the chatbot service for Groq replies. Knowledge search uses local FastEmbed embeddings, so no OpenAI key is required. See the README for model download/cache setup and live validation.

Check login:

```powershell
railway whoami
```

If this is a local install like this repo:

```powershell
.\.railway-cli\node_modules\.bin\railway.cmd whoami
```

## Step 1: Add Chainlit Persistence Dependencies

In the chatbot service requirements, add:

```text
SQLAlchemy
asyncpg
greenlet
```

For this project, the root `requirements.txt` contains:

```text
chainlit
llama-index-core
llama-index-llms-openai-like==0.8.0
llama-index-embeddings-fastembed==0.7.0
fastembed==0.8.0
tokenizers
openai
python-dotenv
SQLAlchemy
asyncpg
greenlet
```

The key packages are:

- `SQLAlchemy`: used by Chainlit's SQL data layer.
- `asyncpg`: PostgreSQL async driver.
- `greenlet`: required by SQLAlchemy's async integration.

## Step 2: Add The Chainlit Schema Helper

Create a helper file in the Chainlit app, for example `conversation_db.py`.

Purpose:

- Read `DATABASE_URL`.
- Convert Railway/Postgres URLs to formats accepted by SQLAlchemy and `asyncpg`.
- Ensure the Chainlit SQL tables exist before conversations are written.

Use this repo's implementation as the source of truth:

```text
conversation_db.py
```

The helper creates the native Chainlit tables:

- `users`
- `threads`
- `steps`
- `elements`
- `feedbacks`

Important schema note:

Chainlit has added columns to `steps` across versions, including `command`, `defaultOpen`, and `modes`. Keep this helper aligned with the current Chainlit SQLAlchemy data layer docs when applying the pattern to a different app.

## Step 3: Register Chainlit's Native SQLAlchemy Data Layer

In the Chainlit app file, usually `app.py`, import the data layer:

```python
import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from conversation_db import ensure_chainlit_schema, get_database_url, to_sqlalchemy_async_url
```

Register the data layer near the top of the app:

```python
@cl.data_layer
def get_data_layer():
    database_url = get_database_url()
    if not database_url:
        return None

    return SQLAlchemyDataLayer(conninfo=to_sqlalchemy_async_url(database_url))
```

Then initialize the schema when a chat starts:

```python
async def ensure_conversation_logging_ready() -> None:
    try:
        await ensure_chainlit_schema()
    except Exception as exc:
        print(f"Could not initialize conversation logging: {exc}")
```

Call it from your existing `@cl.on_chat_start` handler:

```python
@cl.on_chat_start
async def on_chat_start() -> None:
    await ensure_conversation_logging_ready()
    # Continue with the rest of your app startup logic.
```

Why this works:

- `@cl.data_layer` tells Chainlit where to persist users, threads, messages, elements, and feedback.
- `SQLAlchemyDataLayer` is Chainlit-native and avoids custom logging code.
- `to_sqlalchemy_async_url()` converts `postgresql://...` into `postgresql+asyncpg://...`, which Chainlit/SQLAlchemy expects.

## Step 4: Keep The Chainlit Railway Start Command

The chatbot service should run Chainlit on Railway's `$PORT`.

Use this `railway.toml` at the chatbot root:

```toml
[build]
builder = "RAILPACK"

[deploy]
startCommand = "chainlit run app.py --host 0.0.0.0 --port $PORT"
healthcheckPath = "/"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

If the app entry file is not `app.py`, change the start command accordingly.

## Step 5: Add The Dashboard App

Create a `dashboard/` folder beside the Chainlit app.

Required files:

```text
dashboard/
  dashboard.py
  db.py
  requirements.txt
  railway.toml
  static/
    dashboard.css
  templates/
    index.html
    thread.html
```

The dashboard service should:

- Read the same `DATABASE_URL`.
- Use HTTP Basic Auth.
- Expose `/healthz` for Railway health checks.
- Show recent threads on `/`.
- Show one conversation on `/threads/{thread_id}`.

For a new deployment, copy this repo's `dashboard/` folder and then customize branding/CSS if needed.

The dashboard should not store or mutate conversation data. It should only read Chainlit's tables.

## Step 6: Dashboard Dependencies

Use this `dashboard/requirements.txt`:

```text
fastapi
uvicorn[standard]
asyncpg
jinja2
python-dotenv
```

## Step 7: Dashboard Railway Config

Use this `dashboard/railway.toml`:

```toml
[build]
builder = "RAILPACK"

[deploy]
startCommand = "uvicorn dashboard:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/healthz"
healthcheckTimeout = 120
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

Important:

Deploy the `dashboard/` folder with `--path-as-root`. That makes Railway treat `dashboard/` as the app root, so `uvicorn dashboard:app` can import `dashboard.py`, and the relative `templates/` and `static/` directories resolve correctly.

## Step 8: Link Or Select The Railway Project

If the local folder is not linked yet:

```powershell
railway link
```

Confirm the target project and environment:

```powershell
railway status
```

For this repo's local CLI path:

```powershell
.\.railway-cli\node_modules\.bin\railway.cmd status
```

## Step 9: Add Postgres To The Railway Project

Add a PostgreSQL service:

```powershell
railway add --database postgres --json
```

Use a clear service name in the Railway dashboard if Railway does not name it `Postgres`.

If the Postgres service already exists, do not create a duplicate. Reuse the existing database service and note its exact service name.

## Step 10: Add The Dashboard Service

Create an empty service for the dashboard:

```powershell
railway add --service ConversationDashboard --json
```

Use any name you prefer, but keep it explicit. Examples:

- `ConversationDashboard`
- `ChatLogs`
- `AdminDashboard`

## Step 11: Configure Railway Variables

Set `DATABASE_URL` on the chatbot service:

```powershell
railway variable set --service <CHATBOT_SERVICE_NAME> 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
```

Set dashboard variables:

```powershell
railway variable set --service ConversationDashboard 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
railway variable set --service ConversationDashboard "DASHBOARD_USERNAME=admin" --skip-deploys
railway variable set --service ConversationDashboard "DASHBOARD_PASSWORD=<STRONG_PASSWORD>" --skip-deploys
```

Replace:

- `<CHATBOT_SERVICE_NAME>` with the existing Chainlit service name.
- `Postgres` with the actual Railway Postgres service name.
- `<STRONG_PASSWORD>` with a generated secret.

Generate a password locally:

```powershell
[System.Web.Security.Membership]::GeneratePassword(32, 6)
```

Or use another password manager/generator.

Security note:

Do not commit dashboard passwords or API keys. Keep them in Railway service variables.

## Step 12: Deploy The Chatbot

Deploy the Chainlit service:

```powershell
railway up --ci --service <CHATBOT_SERVICE_NAME> --message "Enable Chainlit conversation persistence"
```

Railway's `up` command scans and uploads the local app, builds it with Railpack or Dockerfile, and deploys it to the selected service.

## Step 13: Deploy The Dashboard

Deploy only the dashboard folder:

```powershell
railway up dashboard --path-as-root --ci --service ConversationDashboard --message "Deploy conversation dashboard"
```

The `--path-as-root` flag is important. Without it, the dashboard may deploy with the wrong root path and fail to find templates, static files, or imports.

## Step 14: Generate Railway Domains

Generate or fetch a domain for the chatbot:

```powershell
railway domain --service <CHATBOT_SERVICE_NAME> --json
```

Generate or fetch a domain for the dashboard:

```powershell
railway domain --service ConversationDashboard --json
```

Railway allows one Railway-provided domain per service. If a domain already exists, the command returns it.

## Step 15: Verify Service Status

Check all services:

```powershell
railway service status --all --json
```

Expected:

- Chatbot service: `SUCCESS` or sleeping if intentionally paused.
- Dashboard service: `SUCCESS`.
- Postgres service: `SUCCESS`.

## Step 16: Verify Public Endpoints

Check the chatbot:

```powershell
Invoke-WebRequest -Uri "https://<CHATBOT_DOMAIN>/" -UseBasicParsing -TimeoutSec 30
```

Expected:

```text
StatusCode: 200
```

Check the dashboard health endpoint:

```powershell
Invoke-WebRequest -Uri "https://<DASHBOARD_DOMAIN>/healthz" -UseBasicParsing -TimeoutSec 30
```

Expected:

```json
{"status":"ok"}
```

Check that the dashboard is protected:

```powershell
try {
  Invoke-WebRequest -Uri "https://<DASHBOARD_DOMAIN>/" -UseBasicParsing -TimeoutSec 30
} catch {
  [int]$_.Exception.Response.StatusCode
}
```

Expected:

```text
401
```

Then open the dashboard URL in the browser and log in with:

- Username: the `DASHBOARD_USERNAME` Railway variable.
- Password: the `DASHBOARD_PASSWORD` Railway variable.

## Step 17: Test Conversation Logging End To End

1. Open the deployed Chainlit chatbot.
2. Send a test message.
3. Wait for the assistant response.
4. Open the dashboard.
5. Confirm a new row appears in recent conversations.
6. Click the conversation row.
7. Confirm the detail page shows the user message and assistant response.

If the dashboard is empty but Postgres has data, check the `steps.type` values used by the Chainlit version. The dashboard can be adjusted to display all steps with non-empty `input` or `output`, not only `user_message` and `assistant_message`.

## Step 18: Useful Debug Commands

Dashboard runtime logs:

```powershell
railway logs --service ConversationDashboard --lines 100 --json
```

Chatbot runtime logs:

```powershell
railway logs --service <CHATBOT_SERVICE_NAME> --lines 100 --json
```

HTTP logs:

```powershell
railway logs --service ConversationDashboard --http --status ">=400" --lines 50
```

Service variables:

```powershell
railway variable list --service ConversationDashboard --json
```

Do not paste secret values into tickets, chat, or docs.

## Common Issues And Fixes

### Dashboard returns 401 before login

This is expected. The dashboard uses HTTP Basic Auth.

### Dashboard returns 500 after login

Check logs:

```powershell
railway logs --service ConversationDashboard --lines 100 --json
```

If the error includes:

```text
TypeError: unhashable type: 'dict'
```

Then the dashboard is using the old `TemplateResponse` call style with a newer FastAPI/Starlette version.

Use this style:

```python
return templates.TemplateResponse(
    request,
    "index.html",
    {
        "request": request,
        "stats": stats,
        "threads": threads,
    },
)
```

Do not use this old style:

```python
return templates.TemplateResponse(
    "index.html",
    {
        "request": request,
    },
)
```

### Dashboard starts but cannot find templates or static files

Most likely the service was deployed from the repository root instead of the dashboard root.

Redeploy with:

```powershell
railway up dashboard --path-as-root --ci --service ConversationDashboard
```

### Chainlit starts but conversations are not logged

Check these items:

- `DATABASE_URL` exists on the chatbot service.
- `DATABASE_URL` references the correct Postgres service.
- `SQLAlchemy`, `asyncpg`, and `greenlet` are installed in the chatbot requirements.
- The app has a `@cl.data_layer` function.
- The data layer uses `postgresql+asyncpg://`, not plain `postgresql://`, for SQLAlchemy.
- The Chainlit schema exists in Postgres.
- Railway variables have been deployed, not just staged.

### Postgres connection fails with an SSL query parameter error

Some Postgres URLs include parameters such as `sslmode`.

`asyncpg.connect()` can reject unsupported query parameters. The helper in this repo strips unsupported parameters before opening a direct `asyncpg` connection for schema initialization.

Keep the SQLAlchemy URL and direct `asyncpg` URL conversion separate:

- SQLAlchemy data layer: `postgresql+asyncpg://...`
- Direct `asyncpg.connect()`: `postgresql://...`

### Chatbot is sleeping

If Railway reports the chatbot as sleeping or stopped intentionally, open the chatbot URL or resume it from Railway depending on your service settings. The dashboard can still run and read existing Postgres conversations while the chatbot is paused.

## Production Hardening Checklist

Before using this pattern for sensitive or high-volume production traffic:

- Restrict dashboard access beyond Basic Auth if needed, for example VPN, SSO, or Railway private networking.
- Rotate `DASHBOARD_PASSWORD` periodically.
- Avoid exposing the dashboard domain publicly if internal-only access is required.
- Enable or configure Postgres backups.
- Add indexes if conversation volume grows.
- Consider pagination beyond the latest 100 threads.
- Decide retention policy for old conversations.
- Avoid logging secrets or user-sensitive data in application logs.
- Review compliance requirements before storing user conversations.

Suggested indexes for larger deployments:

```sql
CREATE INDEX IF NOT EXISTS idx_steps_thread_id ON steps ("threadId");
CREATE INDEX IF NOT EXISTS idx_steps_created_at ON steps ("createdAt");
CREATE INDEX IF NOT EXISTS idx_threads_created_at ON threads ("createdAt");
```

## Porting Checklist For Another Chainlit Deployment

Use this checklist to repeat the setup:

- Add `SQLAlchemy`, `asyncpg`, and `greenlet` to the Chainlit app requirements.
- Copy or recreate `conversation_db.py`.
- Add `@cl.data_layer` to the Chainlit app.
- Call schema initialization during app startup or chat startup.
- Confirm the Chainlit service start command uses `$PORT`.
- Copy the `dashboard/` folder.
- Create or reuse Railway Postgres.
- Create a separate Railway dashboard service.
- Set `DATABASE_URL=${{Postgres.DATABASE_URL}}` on both app services.
- Set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` on the dashboard service.
- Deploy the chatbot service.
- Deploy the dashboard with `railway up dashboard --path-as-root`.
- Generate or fetch Railway domains.
- Verify `/`, `/healthz`, login, and a conversation detail page.
- Check Railway logs for any `500` before handing off.

## Commands Summary

Replace placeholders before running.

Assumptions in this summary:

- Chatbot service: `<CHATBOT_SERVICE_NAME>`
- Dashboard service: `ConversationDashboard`
- Postgres service: `Postgres`
- Dashboard password: `<STRONG_PASSWORD>`

```powershell
railway status
railway add --database postgres --json
railway add --service ConversationDashboard --json

railway variable set --service <CHATBOT_SERVICE_NAME> 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
railway variable set --service ConversationDashboard 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
railway variable set --service ConversationDashboard "DASHBOARD_USERNAME=admin" --skip-deploys
railway variable set --service ConversationDashboard "DASHBOARD_PASSWORD=<STRONG_PASSWORD>" --skip-deploys

railway up --ci --service <CHATBOT_SERVICE_NAME> --message "Enable Chainlit conversation persistence"
railway up dashboard --path-as-root --ci --service ConversationDashboard --message "Deploy conversation dashboard"

railway domain --service <CHATBOT_SERVICE_NAME> --json
railway domain --service ConversationDashboard --json
railway service status --all --json
railway logs --service ConversationDashboard --lines 100 --json
```

PowerShell note:

Use single quotes around Railway reference variables so PowerShell does not try to interpret the `$` characters:

```powershell
railway variable set --service EverydayAI 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
railway variable set --service ConversationDashboard 'DATABASE_URL=${{Postgres.DATABASE_URL}}' --skip-deploys
```
