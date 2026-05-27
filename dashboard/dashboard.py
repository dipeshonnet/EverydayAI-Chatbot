import os
import secrets
from datetime import datetime
from typing import Any

import asyncpg
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import ensure_chainlit_schema, get_pool


app = FastAPI(title="Everyday AI Conversations")
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


def require_dashboard_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    expected_username = os.getenv("DASHBOARD_USERNAME", "admin")
    expected_password = os.getenv("DASHBOARD_PASSWORD")

    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_PASSWORD is not configured.",
        )

    username_ok = secrets.compare_digest(credentials.username, expected_username)
    password_ok = secrets.compare_digest(credentials.password, expected_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid dashboard credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.on_event("startup")
async def startup() -> None:
    await ensure_chainlit_schema()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


def display_datetime(value: Any) -> str:
    if not value:
        return "Unknown"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _: str = Depends(require_dashboard_auth)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        stats = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM threads) AS threads,
                (SELECT COUNT(*) FROM steps WHERE type = 'user_message') AS user_messages,
                (SELECT COUNT(*) FROM steps WHERE type = 'assistant_message') AS assistant_messages,
                (SELECT COUNT(*) FROM feedbacks) AS feedbacks
            """
        )
        threads = await conn.fetch(
            """
            SELECT
                t."id",
                t."name",
                t."userIdentifier",
                t."createdAt",
                COUNT(s."id") AS step_count,
                MAX(s."createdAt") AS last_activity,
                MIN(NULLIF(COALESCE(s."input", s."output"), '')) FILTER (WHERE s."type" = 'user_message') AS first_message
            FROM threads t
            LEFT JOIN steps s ON s."threadId" = t."id"
            GROUP BY t."id", t."name", t."userIdentifier", t."createdAt"
            ORDER BY COALESCE(MAX(s."createdAt"), t."createdAt") DESC NULLS LAST
            LIMIT 100
            """
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "stats": dict(stats or {}),
            "threads": threads,
            "display_datetime": display_datetime,
        },
    )


@app.get("/threads/{thread_id}", response_class=HTMLResponse)
async def thread_detail(request: Request, thread_id: str, _: str = Depends(require_dashboard_auth)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        thread = await conn.fetchrow(
            """
            SELECT "id", "name", "userIdentifier", "createdAt", "metadata"
            FROM threads
            WHERE "id" = $1
            """,
            thread_id,
        )
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")

        steps = await conn.fetch(
            """
            SELECT "id", "name", "type", "input", "output", "createdAt", "isError"
            FROM steps
            WHERE "threadId" = $1
            ORDER BY COALESCE("createdAt", "start", "end") ASC NULLS LAST
            """,
            thread_id,
        )

    return templates.TemplateResponse(
        request,
        "thread.html",
        {
            "request": request,
            "thread": thread,
            "steps": steps,
            "display_datetime": display_datetime,
        },
    )
