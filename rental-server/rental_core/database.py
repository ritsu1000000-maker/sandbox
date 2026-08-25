from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import sqlite3
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RentalDatabase:
    """Small database layer supporting SQLite locally and PostgreSQL in production."""

    def __init__(self, database_url: str = "") -> None:
        self.database_url = (database_url or "").strip()
        self.is_postgres = self.database_url.startswith(("postgres://", "postgresql://"))
        if not self.is_postgres:
            raw_path = self.database_url
            if raw_path.startswith("sqlite:///"):
                raw_path = raw_path[len("sqlite:///"):]
            self.sqlite_path = raw_path or os.environ.get("DATABASE_PATH", "data/rental.db")
            Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        if self.is_postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self.database_url, row_factory=dict_row)
        else:
            conn = sqlite3.connect(self.sqlite_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.is_postgres else query

    def init_schema(self) -> None:
        if self.is_postgres:
            statements = [
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS leases (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    resource_name TEXT NOT NULL UNIQUE,
                    plan_id TEXT NOT NULL,
                    template TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    public_url TEXT,
                    created_at TEXT NOT NULL,
                    renews_at TEXT,
                    canceled_at TEXT,
                    UNIQUE(user_id, display_name)
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_leases_user_id ON leases(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_leases_resource_name ON leases(resource_name)",
            ]
        else:
            statements = [
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS leases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    resource_name TEXT NOT NULL UNIQUE,
                    plan_id TEXT NOT NULL,
                    template TEXT NOT NULL,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    public_url TEXT,
                    created_at TEXT NOT NULL,
                    renews_at TEXT,
                    canceled_at TEXT,
                    UNIQUE(user_id, display_name)
                )
                """,
                "CREATE INDEX IF NOT EXISTS idx_leases_user_id ON leases(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_leases_resource_name ON leases(resource_name)",
            ]
        with self.connect() as conn:
            for statement in statements:
                conn.execute(statement)

    @staticmethod
    def _dict(row: Any) -> dict | None:
        return dict(row) if row is not None else None

    def create_user(self, email: str, password_hash: str) -> dict:
        now = utcnow()
        with self.connect() as conn:
            if self.is_postgres:
                row = conn.execute(
                    "INSERT INTO users(email,password_hash,created_at) VALUES(%s,%s,%s) RETURNING *",
                    (email, password_hash, now),
                ).fetchone()
            else:
                cursor = conn.execute(
                    "INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)",
                    (email, password_hash, now),
                )
                row = conn.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
        return self._dict(row) or {}

    def get_user_by_email(self, email: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(self._sql("SELECT * FROM users WHERE email=?"), (email,)).fetchone()
        return self._dict(row)

    def get_user(self, user_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(self._sql("SELECT * FROM users WHERE id=?"), (user_id,)).fetchone()
        return self._dict(row)

    def list_users_admin(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.email, u.created_at, COUNT(l.id) AS service_count
                FROM users u
                LEFT JOIN leases l ON l.user_id = u.id AND l.status != 'canceled'
                GROUP BY u.id, u.email, u.created_at
                ORDER BY u.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def create_lease(
        self,
        user_id: int,
        display_name: str,
        resource_name: str,
        plan_id: str,
        template: str,
        status: str,
        provider: str,
        renews_at: str | None = None,
    ) -> dict:
        now = utcnow()
        values = (user_id, display_name, resource_name, plan_id, template, status, provider, now, renews_at)
        with self.connect() as conn:
            if self.is_postgres:
                row = conn.execute(
                    """
                    INSERT INTO leases(user_id,display_name,resource_name,plan_id,template,status,provider,created_at,renews_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """,
                    values,
                ).fetchone()
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO leases(user_id,display_name,resource_name,plan_id,template,status,provider,created_at,renews_at)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    values,
                )
                row = conn.execute("SELECT * FROM leases WHERE id=?", (cursor.lastrowid,)).fetchone()
        return self._dict(row) or {}

    def list_leases(self, user_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                self._sql("SELECT * FROM leases WHERE user_id=? ORDER BY id DESC"),
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_leases_admin(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*, u.email AS owner_email
                FROM leases l
                JOIN users u ON u.id = l.user_id
                ORDER BY l.id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_lease(self, user_id: int, lease_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM leases WHERE id=? AND user_id=?"),
                (lease_id, user_id),
            ).fetchone()
        return self._dict(row)

    def get_lease_admin(self, lease_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM leases WHERE id=?"),
                (lease_id,),
            ).fetchone()
        return self._dict(row)

    def get_lease_by_name(self, user_id: int, display_name: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM leases WHERE user_id=? AND display_name=?"),
                (user_id, display_name),
            ).fetchone()
        return self._dict(row)

    def get_lease_by_resource_name(self, resource_name: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                self._sql("SELECT * FROM leases WHERE resource_name=?"),
                (resource_name,),
            ).fetchone()
        return self._dict(row)

    def update_lease(self, lease_id: int, **fields: Any) -> None:
        allowed = {"status", "provider", "public_url", "renews_at", "canceled_at"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key}=?" for key in updates)
        params: list[Any] = list(updates.values()) + [lease_id]
        with self.connect() as conn:
            conn.execute(self._sql(f"UPDATE leases SET {assignments} WHERE id=?"), params)

    def cancel_lease(self, user_id: int, lease_id: int) -> dict | None:
        lease = self.get_lease(user_id, lease_id)
        if not lease:
            return None
        self.update_lease(lease_id, status="canceled", canceled_at=utcnow())
        return self.get_lease(user_id, lease_id)
