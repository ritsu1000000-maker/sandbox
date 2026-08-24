from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets

from .config import PLANS, TEMPLATE_CODE
from .errors import ServiceError
from .security import management_key


DISPLAY_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


class RentalService:
    def __init__(self, settings, database, manager):
        self.settings = settings
        self.database = database
        self.manager = manager

    def normalize_name(self, value: str) -> str:
        name = str(value or "").strip().lower()
        name = re.sub(r"\s+", "-", name)
        name = re.sub(r"[^a-z0-9-]", "", name)
        name = re.sub(r"-+", "-", name).strip("-")[:32]
        return name

    def _resource_name(self, user_id: int, display_name: str) -> str:
        # Provider names are global. Keep the user's friendly name separate.
        suffix = secrets.token_hex(3)
        prefix = f"u{user_id}-"
        max_slug = 32 - len(prefix) - len(suffix) - 1
        slug = display_name[:max(1, max_slug)].strip("-") or "server"
        return f"{prefix}{slug}-{suffix}"[:32].strip("-")

    def _renewal(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=self.settings.lease_days)).isoformat(timespec="seconds")

    def create_contract(self, user_id: int, data: dict) -> dict:
        display_name = self.normalize_name(data.get("name", ""))
        plan_id = str(data.get("plan", "free"))
        template = str(data.get("template", "python-web"))

        if not display_name or not DISPLAY_NAME_RE.fullmatch(display_name):
            raise ServiceError("サーバー名は英小文字・数字・ハイフンで1〜32文字にしてください。", 400)
        if plan_id not in PLANS:
            raise ServiceError("unknown plan", 400)
        if template not in TEMPLATE_CODE:
            raise ServiceError("unknown template", 400)
        if self.database.get_lease_by_name(user_id, display_name):
            raise ServiceError("同じ名前の契約がすでにあります。", 409)

        plan = PLANS[plan_id]
        paid = int(plan["price_yen"]) > 0
        resource_name = self._resource_name(user_id, display_name)
        initial_status = "pending_payment" if paid else "provisioning"
        lease = self.database.create_lease(
            user_id=user_id,
            display_name=display_name,
            resource_name=resource_name,
            plan_id=plan_id,
            template=template,
            status=initial_status,
            provider=self.manager.provider_name,
            renews_at=self._renewal(),
        )

        if paid:
            return self.serialize_contract(lease)

        try:
            result = self.manager.create({"name": resource_name, "plan": plan_id, "template": template})
            instance = result.get("instance", {})
            self.database.update_lease(
                lease["id"],
                status="active",
                public_url=instance.get("url"),
            )
        except Exception:
            self.database.update_lease(lease["id"], status="provision_failed")
            raise

        return self.serialize_contract(self.database.get_lease(user_id, lease["id"]) or lease)

    def activate_paid_contract(self, user_id: int, lease_id: int) -> dict:
        """Internal hook for a future verified payment webhook."""
        lease = self.require_contract(user_id, lease_id)
        if lease["status"] != "pending_payment":
            raise ServiceError("この契約は支払い待ちではありません。", 409)
        if not self.settings.allow_paid_render_plans and self.manager.provider_name == "render":
            raise ServiceError("Render有料プランの発行が無効です。", 409)
        self.database.update_lease(lease_id, status="provisioning")
        result = self.manager.create({
            "name": lease["resource_name"],
            "plan": lease["plan_id"],
            "template": lease["template"],
        })
        instance = result.get("instance", {})
        self.database.update_lease(lease_id, status="active", public_url=instance.get("url"))
        return self.serialize_contract(self.require_contract(user_id, lease_id))

    def list_contracts(self, user_id: int) -> list[dict]:
        return [self.serialize_contract(row) for row in self.database.list_leases(user_id)]

    def require_contract(self, user_id: int, lease_id: int) -> dict:
        lease = self.database.get_lease(user_id, lease_id)
        if not lease:
            raise ServiceError("契約が見つかりません。", 404)
        return lease

    def instance_for_contract(self, user_id: int, lease_id: int) -> dict:
        lease = self.require_contract(user_id, lease_id)
        payload = {"contract": self.serialize_contract(lease), "instance": None}
        if lease["status"] not in {"active", "provisioning"}:
            return payload
        key = management_key(self.settings.instance_key_secret, lease["resource_name"])
        try:
            result = self.manager.get(lease["resource_name"], key)
            instance = result.get("instance")
            if instance:
                self.database.update_lease(
                    lease_id,
                    status="active",
                    public_url=instance.get("url") or lease.get("public_url"),
                )
                payload["contract"] = self.serialize_contract(self.require_contract(user_id, lease_id))
                payload["instance"] = instance
        except ServiceError as exc:
            if exc.status == 404 and lease["status"] == "provisioning":
                return payload
            raise
        return payload

    def action(self, user_id: int, lease_id: int, action: str) -> dict:
        lease = self.require_contract(user_id, lease_id)
        if lease["status"] != "active":
            raise ServiceError("利用中の契約だけ操作できます。", 409)
        key = management_key(self.settings.instance_key_secret, lease["resource_name"])
        result = self.manager.action(lease["resource_name"], action, key)
        return {"contract": self.serialize_contract(lease), **result}

    def cancel(self, user_id: int, lease_id: int) -> dict:
        lease = self.require_contract(user_id, lease_id)
        if lease["status"] == "canceled":
            return self.serialize_contract(lease)
        if lease["status"] == "active":
            key = management_key(self.settings.instance_key_secret, lease["resource_name"])
            try:
                self.manager.delete(lease["resource_name"], key)
            except ServiceError as exc:
                if exc.status != 404:
                    raise
        canceled = self.database.cancel_lease(user_id, lease_id)
        return self.serialize_contract(canceled or lease)

    def serialize_contract(self, lease: dict) -> dict:
        plan = PLANS.get(lease.get("plan_id"), {})
        return {
            "id": lease.get("id"),
            "name": lease.get("display_name"),
            "plan": lease.get("plan_id"),
            "plan_name": plan.get("name", lease.get("plan_id")),
            "price_yen": plan.get("price_yen", 0),
            "storage_gb": plan.get("storage_gb"),
            "memory": plan.get("memory"),
            "cpu": plan.get("cpu"),
            "template": lease.get("template"),
            "status": lease.get("status"),
            "provider": lease.get("provider"),
            "public_url": lease.get("public_url"),
            "created_at": lease.get("created_at"),
            "renews_at": lease.get("renews_at"),
            "canceled_at": lease.get("canceled_at"),
        }
