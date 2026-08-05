from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, account_name: str) -> Path:
        safe = "".join(ch for ch in account_name if ch.isalnum() or ch in {"-", "_"})
        return self.directory / f"{safe}.json"

    async def load(self, account_name: str) -> dict[str, Any] | None:
        path = self._path(account_name)
        if not path.exists():
            return None
        try:
            value = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
            if float(value.get("expires_at", 0)) <= time.time() + 30:
                return None
            return value
        except (OSError, ValueError, TypeError):
            return None

    async def save(self, account_name: str, token: str, expires_in: int) -> None:
        path = self._path(account_name)
        temporary = path.with_suffix(".tmp")
        payload = json.dumps(
            {"access_token": token, "expires_at": time.time() + max(60, expires_in)}
        )
        await asyncio.to_thread(temporary.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(os.replace, temporary, path)

    async def invalidate(self, account_name: str) -> None:
        path = self._path(account_name)
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(path.unlink)


class OrderStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    order_id TEXT,
                    status TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orders_account_time
                ON orders(account_name, created_at)
                """
            )
            connection.commit()

    async def count_successes_24h(self, account_name: str) -> int:
        async with self.lock:
            return await asyncio.to_thread(self._count_successes_24h_sync, account_name)

    def _count_successes_24h_sync(self, account_name: str) -> int:
        cutoff = int(time.time()) - 86_400
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM orders
                WHERE account_name = ?
                  AND status IN ('simulated', 'placed')
                  AND created_at >= ?
                """,
                (account_name, cutoff),
            ).fetchone()
        return int(row[0] if row else 0)

    async def record(
        self,
        *,
        account_name: str,
        product_id: str,
        order_id: str | None,
        status: str,
        dry_run: bool,
        details: dict[str, Any],
    ) -> None:
        async with self.lock:
            await asyncio.to_thread(
                self._record_sync,
                account_name,
                product_id,
                order_id,
                status,
                dry_run,
                details,
            )

    def _record_sync(
        self,
        account_name: str,
        product_id: str,
        order_id: str | None,
        status: str,
        dry_run: bool,
        details: dict[str, Any],
    ) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    account_name, product_id, order_id, status,
                    dry_run, created_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    account_name,
                    product_id,
                    order_id,
                    status,
                    int(dry_run),
                    int(time.time()),
                    json.dumps(details, ensure_ascii=False, default=str),
                ),
            )
            connection.commit()
