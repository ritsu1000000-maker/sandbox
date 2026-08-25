from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import redis


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RedisRentalDatabase:
    """Redis/Valkey-backed account and hosting metadata store.

    This mirrors the RentalDatabase methods used by the Flask app, allowing
    Render Key Value to survive web-service redeploys without changing the
    application/service layer.
    """

    prefix = "hosting:v1"
    is_postgres = False
    is_redis = True

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url.strip()
        self.client = redis.Redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        self.client.ping()

    def _key(self, *parts: Any) -> str:
        return ":".join([self.prefix, *(str(p) for p in parts)])

    @staticmethod
    def _coerce_user(row: dict | None) -> dict | None:
        if not row:
            return None
        result = dict(row)
        if "id" in result:
            result["id"] = int(result["id"])
        return result

    @staticmethod
    def _coerce_lease(row: dict | None) -> dict | None:
        if not row:
            return None
        result = dict(row)
        if "id" in result:
            result["id"] = int(result["id"])
        if "user_id" in result:
            result["user_id"] = int(result["user_id"])
        return result

    def create_user(self, email: str, password_hash: str) -> dict:
        email = email.strip().lower()
        email_key = self._key("user-email", email)
        user_id = int(self.client.incr(self._key("seq", "user")))
        if not self.client.set(email_key, str(user_id), nx=True):
            raise ValueError("email already exists")

        row = {
            "id": str(user_id),
            "email": email,
            "password_hash": password_hash,
            "created_at": utcnow(),
        }
        pipe = self.client.pipeline()
        pipe.hset(self._key("user", user_id), mapping=row)
        pipe.sadd(self._key("users"), str(user_id))
        try:
            pipe.execute()
        except Exception:
            self.client.delete(email_key)
            raise
        return self._coerce_user(row) or {}

    def get_user_by_email(self, email: str) -> dict | None:
        user_id = self.client.get(self._key("user-email", email.strip().lower()))
        return self.get_user(int(user_id)) if user_id else None

    def get_user(self, user_id: int) -> dict | None:
        return self._coerce_user(self.client.hgetall(self._key("user", user_id)))

    def list_users_admin(self) -> list[dict]:
        users = []
        for raw_id in self.client.smembers(self._key("users")):
            user = self.get_user(int(raw_id))
            if not user:
                continue
            leases = self.list_leases(user["id"])
            user["service_count"] = sum(1 for item in leases if item.get("status") != "canceled")
            users.append(user)
        return sorted(users, key=lambda item: int(item["id"]), reverse=True)

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
        name_key = self._key("lease-name", user_id, display_name)
        resource_key = self._key("lease-resource", resource_name)
        lease_id = int(self.client.incr(self._key("seq", "lease")))

        if not self.client.set(name_key, str(lease_id), nx=True):
            raise ValueError("service name already exists")
        if not self.client.set(resource_key, str(lease_id), nx=True):
            self.client.delete(name_key)
            raise ValueError("resource name already exists")

        row = {
            "id": str(lease_id),
            "user_id": str(user_id),
            "display_name": display_name,
            "resource_name": resource_name,
            "plan_id": plan_id,
            "template": template,
            "status": status,
            "provider": provider,
            "public_url": "",
            "created_at": utcnow(),
            "renews_at": renews_at or "",
            "canceled_at": "",
        }
        pipe = self.client.pipeline()
        pipe.hset(self._key("lease", lease_id), mapping=row)
        pipe.sadd(self._key("leases"), str(lease_id))
        pipe.sadd(self._key("user-leases", user_id), str(lease_id))
        try:
            pipe.execute()
        except Exception:
            self.client.delete(name_key, resource_key)
            raise
        return self._coerce_lease(row) or {}

    def list_leases(self, user_id: int) -> list[dict]:
        rows = []
        for raw_id in self.client.smembers(self._key("user-leases", user_id)):
            row = self.get_lease(user_id, int(raw_id))
            if row:
                rows.append(row)
        return sorted(rows, key=lambda item: int(item["id"]), reverse=True)

    def list_leases_admin(self) -> list[dict]:
        rows = []
        for raw_id in self.client.smembers(self._key("leases")):
            row = self.get_lease_admin(int(raw_id))
            if not row:
                continue
            user = self.get_user(int(row["user_id"]))
            row["owner_email"] = user.get("email", "") if user else ""
            rows.append(row)
        return sorted(rows, key=lambda item: int(item["id"]), reverse=True)

    def get_lease(self, user_id: int, lease_id: int) -> dict | None:
        row = self.get_lease_admin(lease_id)
        if not row or int(row.get("user_id", -1)) != int(user_id):
            return None
        return row

    def get_lease_admin(self, lease_id: int) -> dict | None:
        return self._coerce_lease(self.client.hgetall(self._key("lease", lease_id)))

    def get_lease_by_name(self, user_id: int, display_name: str) -> dict | None:
        lease_id = self.client.get(self._key("lease-name", user_id, display_name))
        return self.get_lease(user_id, int(lease_id)) if lease_id else None

    def get_lease_by_resource_name(self, resource_name: str) -> dict | None:
        lease_id = self.client.get(self._key("lease-resource", resource_name))
        return self.get_lease_admin(int(lease_id)) if lease_id else None

    def update_lease(self, lease_id: int, **fields: Any) -> None:
        allowed = {"status", "provider", "public_url", "renews_at", "canceled_at"}
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        key = self._key("lease", lease_id)
        mapping = {k: str(v) for k, v in updates.items() if v is not None}
        if mapping:
            self.client.hset(key, mapping=mapping)
        null_fields = [k for k, v in updates.items() if v is None]
        if null_fields:
            self.client.hdel(key, *null_fields)

    def cancel_lease(self, user_id: int, lease_id: int) -> dict | None:
        lease = self.get_lease(user_id, lease_id)
        if not lease:
            return None
        self.update_lease(lease_id, status="canceled", canceled_at=utcnow())
        return self.get_lease(user_id, lease_id)
