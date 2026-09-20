"""PostgreSQL persistence for scan arrays, anchor chains and results.

A single ``projects`` table stores everything as JSONB, so a restarted API
process picks up unfinished/finished work without recomputation.
"""

from __future__ import annotations

import os
from typing import Any

from psycopg import AsyncConnectionPool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id         BIGSERIAL PRIMARY KEY,
    left_scan  JSONB NOT NULL,
    right_scan JSONB NOT NULL,
    anchors    JSONB NOT NULL,
    result     JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://film:film@db:5432/film",
    )


async def init_db() -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=database_url(),
        min_size=int(os.environ.get("DB_POOL_MIN", "2")),
        max_size=int(os.environ.get("DB_POOL_MAX", "10")),
        timeout=30,
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open()
    # Wait for a freshly started database: retries are handled by callers via
    # the lifespan; pool.open() itself retries connection attempts.
    async with pool.connection() as conn:
        await conn.execute(_SCHEMA)
    return pool


async def close_db(pool: AsyncConnectionPool) -> None:
    await pool.close()


async def create_project(
    pool: AsyncConnectionPool,
    left: list[str],
    right: list[str],
    anchors: list[list[int]],
    result: list[list[int]],
) -> int:
    async with pool.connection() as conn:
        row = await conn.execute(
            """
            INSERT INTO projects (left_scan, right_scan, anchors, result)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (left, right, anchors, result),
        )
        return (await row.fetchone())[0]


async def get_project(pool: AsyncConnectionPool, project_id: int) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        row = await conn.execute(
            """
            SELECT id, left_scan, right_scan, anchors, result
            FROM projects WHERE id = %s
            """,
            (project_id,),
        )
        record = await row.fetchone()
    if record is None:
        return None
    return {
        "id": record[0],
        "left": record[1],
        "right": record[2],
        "anchors": record[3],
        "result": record[4],
        "length": len(record[4]),
    }


async def replace_anchors(
    pool: AsyncConnectionPool,
    project_id: int,
    anchors: list[list[int]],
    result: list[list[int]],
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE projects SET anchors = %s, result = %s WHERE id = %s",
            (anchors, result, project_id),
        )
