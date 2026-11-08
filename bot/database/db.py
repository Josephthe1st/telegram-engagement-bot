from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Iterable, Optional

import aiosqlite

from bot.logger import get_logger

logger = get_logger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


class Database:
    """Thin async wrapper around a single shared aiosqlite connection.

    A single connection with a write-lock is sufficient for the throughput
    a Telegram engagement bot needs, and keeps deployment simple (no
    external DB server). WAL mode is enabled for concurrent readers.
    """

    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        await self._conn.commit()
        await self._run_migrations()
        logger.info("Database connected at %s", self._db_path)

    async def _run_migrations(self) -> None:
        """Lightweight, additive migrations for databases created before a
        column existed. `CREATE TABLE IF NOT EXISTS` in schema.sql only
        covers brand-new databases, so pre-existing ones need an explicit
        ALTER TABLE. Each migration is wrapped so it's a no-op if the column
        is already present.
        """
        migrations = [
            "ALTER TABLE groups ADD COLUMN rules3 TEXT",
            "ALTER TABLE x_ownership ADD COLUMN last_seen_at TEXT",
        ]
        for statement in migrations:
            try:
                await self._conn.execute(statement)
                await self._conn.commit()
            except Exception:  # noqa: BLE001 - column already exists
                pass

        # Backfill: any x_ownership row from before last_seen_at existed
        # should start out treated as "last used when first seen".
        try:
            await self._conn.execute(
                "UPDATE x_ownership SET last_seen_at = first_seen_at WHERE last_seen_at IS NULL"
            )
            await self._conn.commit()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            logger.info("Database connection closed")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected yet")
        return self._conn

    async def execute(self, query: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        async with self._write_lock:
            cur = await self.conn.execute(query, params)
            await self.conn.commit()
            return cur

    async def executemany(self, query: str, seq_params: Iterable[Iterable[Any]]) -> None:
        async with self._write_lock:
            await self.conn.executemany(query, seq_params)
            await self.conn.commit()

    async def fetchone(self, query: str, params: Iterable[Any] = ()) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, query: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return list(rows)
