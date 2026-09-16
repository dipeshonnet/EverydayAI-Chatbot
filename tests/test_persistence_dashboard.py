"""Exercise conversation writes and dashboard reads against a temporary database."""

import importlib.util
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.templating import Jinja2Templates


class SQLitePool:
    """Use the dashboard's SQL unchanged with an asyncpg-shaped local connection."""

    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def fetch(self, query, *args):
        parameters = {str(index): value for index, value in enumerate(args, start=1)}
        return [dict(row) for row in self.connection.execute(query, parameters).fetchall()]

    async def fetchrow(self, query, *args):
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None


class PersistenceDashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_logged_conversation_is_visible_in_authenticated_dashboard(self):
        from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
        from everydayai_chatbot.conversation_db import CHAINLIT_SCHEMA_SQL

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "conversations.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(CHAINLIT_SCHEMA_SQL)
            layer = SQLAlchemyDataLayer(f"sqlite+aiosqlite:///{database.as_posix()}")
            try:
                thread_id = str(uuid.uuid4())
                await layer.update_thread(thread_id, name="Groq validation")
                for kind, text in [("user_message", "What services do you offer?"), ("assistant_message", "We build AI chatbots.")]:
                    # Call the actual persistence method without a websocket queue.
                    await SQLAlchemyDataLayer.create_step.__wrapped__(layer, {
                        "id": str(uuid.uuid4()), "threadId": thread_id,
                        "name": "User" if kind == "user_message" else "Assistant",
                        "type": kind, "output": text, "streaming": False,
                        "createdAt": "2026-09-16T10:00:00Z",
                    })

                dashboard_dir = Path(__file__).resolve().parents[1] / "dashboard"
                spec = importlib.util.spec_from_file_location("conversation_dashboard_test", dashboard_dir / "dashboard.py")
                dashboard = importlib.util.module_from_spec(spec)
                old_cwd = Path.cwd()
                try:
                    os.chdir(dashboard_dir)
                    with patch.object(sys, "path", [str(dashboard_dir), *sys.path]):
                        spec.loader.exec_module(dashboard)
                finally:
                    os.chdir(old_cwd)
                dashboard.templates = Jinja2Templates(directory=str(dashboard_dir / "templates"))
                pool = SQLitePool(database)
                try:
                    async def get_pool():
                        return pool

                    with patch.object(dashboard, "get_pool", get_pool), patch.dict(os.environ, {"DASHBOARD_USERNAME": "admin", "DASHBOARD_PASSWORD": "local-test-password"}):
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dashboard.app), base_url="http://test") as client:
                            self.assertEqual((await client.get("/healthz")).status_code, 200)
                            self.assertEqual((await client.get("/")).status_code, 401)
                            auth = ("admin", "local-test-password")
                            index = await client.get("/", auth=auth)
                            self.assertEqual(index.status_code, 200)
                            self.assertIn("What services do you offer?", index.text)
                            thread = await client.get(f"/threads/{thread_id}", auth=auth)
                            self.assertEqual(thread.status_code, 200)
                            self.assertIn("What services do you offer?", thread.text)
                            self.assertIn("We build AI chatbots.", thread.text)
                finally:
                    pool.connection.close()
            finally:
                await layer.engine.dispose()
