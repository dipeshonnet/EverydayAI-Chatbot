import asyncio
import os
from urllib.parse import urlsplit, urlunsplit

import asyncpg


CHAINLIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    "autoCollapse" BOOLEAN,
    "modes" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""

# CREATE TABLE does not update databases created by older Chainlit versions.
CHAINLIT_MIGRATIONS_SQL = """
ALTER TABLE steps ADD COLUMN IF NOT EXISTS "autoCollapse" BOOLEAN;
"""


def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL", "").strip() or None


def to_sqlalchemy_async_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    return url


def to_asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url.removeprefix("postgresql+asyncpg://")
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


def strip_unsupported_asyncpg_params(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url

    kept_params = []
    for param in parts.query.split("&"):
        if not param.startswith("sslmode="):
            kept_params.append(param)

    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept_params), parts.fragment))


async def ensure_chainlit_schema(attempts: int = 5, retry_delay_seconds: float = 2.0) -> None:
    database_url = get_database_url()
    if not database_url:
        return

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            conn = await asyncpg.connect(strip_unsupported_asyncpg_params(to_asyncpg_url(database_url)))
            try:
                await conn.execute(CHAINLIT_SCHEMA_SQL)
                await conn.execute(CHAINLIT_MIGRATIONS_SQL)
                return
            finally:
                await conn.close()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            await asyncio.sleep(retry_delay_seconds)

    raise RuntimeError("Could not initialize Chainlit database schema.") from last_error
