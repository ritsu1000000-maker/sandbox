import secrets
from urllib.parse import quote

import requests

from .config import CODE_TEMPLATE, PLANS, RENDER_PLAN_MAP, TEMPLATE_CODE
from .errors import ServiceError
from .security import management_key, validate_name, verify_management_key


class RunnerProvider:
    name = "runner"

    def __init__(self, settings):
        self.settings = settings
        self.session = requests.Session()

    @property
    def configured(self):
        return bool(self.settings.runner_url and self.settings.runner_token)

    def _request(self, method, path, instance_key=None, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.settings.runner_token}"
        if instance_key:
            headers["X-Instance-Key"] = instance_key
        try:
            response = self.session.request(
                method,
                f"{self.settings.runner_url}{path}",
                headers=headers,
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ServiceError(f"runner unavailable: {exc}", 502) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or "invalid runner response"}
        if not response.ok:
            raise ServiceError(str(payload.get("error", payload)), response.status_code, payload)
        return payload

    def create(self, data):
        manage_key = secrets.token_urlsafe(32)
        payload = {
            "name": data.get("name", ""),
            "template": data.get("template", "python-web"),
            "plan": data.get("plan", "free"),
            "manage_key": manage_key,
        }
        result = self._request("POST", "/instances", json=payload)
        result["manage_key"] = manage_key
        return result

    def get(self, name, key):
        return self._request("GET", f"/instances/{quote(name, safe='')}", instance_key=key)

    def action(self, name, action, key):
        return self._request("POST", f"/instances/{quote(name, safe='')}/{action}", instance_key=key)

    def delete(self, name, key):
        return self._request("DELETE", f"/instances/{quote(name, safe='')}", instance_key=key)

    def logs(self, name, key):
        return self._request("GET", f"/instances/{quote(name, safe='')}/logs", instance_key=key)

    def public_url(self, name):
        return None


class RenderProvider:
    name = "render"
    api_base = "https://api.render.com/v1"

    def __init__(self, settings):
        self.settings = settings
        self.session = requests.Session()

    @property
    def configured(self):
        return bool(self.settings.render_api_key and self.settings.render_owner_id)

    @property
    def key_secret(self):
        return self.settings.instance_key_secret or self.settings.render_api_key

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.settings.render_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method, path, **kwargs):
        if not self.configured:
            missing = []
            if not self.settings.render_api_key:
                missing.append("RENDER_API_KEY")
            if not self.settings.render_owner_id:
                missing.append("RENDER_OWNER_ID")
            raise ServiceError("Render API is not configured", 503, {"missing": missing})
        try:
            response = self.session.request(
                method,
                f"{self.api_base}{path}",
                headers=self._headers(),
                timeout=30,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ServiceError(f"Render API unavailable: {exc}", 502) from exc
        if response.status_code == 204:
            return {}
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text or f"Render API HTTP {response.status_code}"}
        if not response.ok:
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("error") or payload
            else:
                detail = payload
            raise ServiceError(f"Render API error: {detail}", response.status_code, payload)
        return payload

    @staticmethod
    def _normalize(value):
        if not isinstance(value, dict):
            return {}
        service = value.get("service")
        return service if isinstance(service, dict) else value

    def _service_base(self, name):
        return f"{self.settings.render_service_prefix}-{name}-"

    def _service_name(self, name, plan, template):
        return f"{self._service_base(name)}{plan}-{TEMPLATE_CODE[template]}"

    def _parse_name(self, full_name):
        prefix = f"{self.settings.render_service_prefix}-"
        if not full_name.startswith(prefix):
            return None
        parts = full_name[len(prefix):].rsplit("-", 2)
        if len(parts) != 3:
            return None
        user_name, plan, template_code = parts
        template = CODE_TEMPLATE.get(template_code)
        if plan not in PLANS or not template or not validate_name(user_name):
            return None
        return user_name, plan, template

    def _list_services(self):
        payload = self._request(
            "GET",
            "/services",
            params={"ownerId": self.settings.render_owner_id, "limit": 100, "includePreviews": "false"},
        )
        if not isinstance(payload, list):
            return []
        return [self._normalize(item) for item in payload]

    def _find(self, name, required=True):
        base = self._service_base(name)
        for service in self._list_services():
            full_name = str(service.get("name", ""))
            if full_name.startswith(base) and self._parse_name(full_name):
                return service
        if required:
            raise ServiceError("instance not found", 404)
        return None

    def _retrieve(self, service_id):
        return self._normalize(self._request("GET", f"/services/{quote(service_id, safe='')}"))

    def _serialize(self, service):
        parsed = self._parse_name(str(service.get("name", "")))
        if not parsed:
            raise ServiceError("unexpected Render service metadata", 502)
        name, plan_id, template = parsed
        plan = PLANS[plan_id]
        details = service.get("serviceDetails") if isinstance(service.get("serviceDetails"), dict) else {}
        url = service.get("url") or details.get("url")
        suspended = str(service.get("suspended", "not_suspended"))
        status = "exited" if suspended == "suspended" else "running"
        return {
            "name": name,
            "template": template,
            "plan": plan_id,
            "plan_name": plan["name"],
            "storage_gb": plan["storage_gb"],
            "price_yen": plan["price_yen"],
            "memory": plan["memory"],
            "cpu": plan["cpu"],
            "status": status,
            "url": url,
            "host_port": None,
            "container_id": service.get("id", "-"),
            "provider": "render",
            "region": details.get("region") or self.settings.render_region,
            "created_at": service.get("createdAt"),
            "updated_at": service.get("updatedAt"),
        }

    def _template_details(self, template, render_plan):
        common = {"plan": render_plan, "region": self.settings.render_region, "numInstances": 1}
        if template == "python-web":
            return {
                **common,
                "runtime": "python",
                "healthCheckPath": "/health",
                "envSpecificDetails": {
                    "buildCommand": "pip install -r rental-server/tenant-requirements.txt",
                    "startCommand": "gunicorn --chdir rental-server tenant_app:app --bind 0.0.0.0:$PORT",
                },
            }
        if template == "node-web":
            return {
                **common,
                "runtime": "node",
                "healthCheckPath": "/health",
                "envSpecificDetails": {
                    "buildCommand": "node --version",
                    "startCommand": "node rental-server/tenant_node.js",
                },
            }
        return {
            **common,
            "runtime": "docker",
            "healthCheckPath": "/",
            "envSpecificDetails": {
                "dockerContext": ".",
                "dockerfilePath": "rental-server/tenant-nginx.Dockerfile",
            },
        }

    def _verify(self, name, key):
        if not validate_name(name):
            raise ServiceError("invalid server name", 400)
        if not verify_management_key(name, key, self.key_secret):
            raise ServiceError("invalid management key", 403)

    def create(self, data):
        name = str(data.get("name", "")).strip().lower()
        template = str(data.get("template", "python-web"))
        plan_id = str(data.get("plan", "free"))
        if not validate_name(name):
            raise ServiceError("name must be 3-32 chars: a-z, 0-9, hyphen", 400)
        if template not in TEMPLATE_CODE:
            raise ServiceError("unknown template", 400)
        if plan_id not in PLANS:
            raise ServiceError("unknown plan", 400)
        if plan_id != "free" and not self.settings.allow_paid_render_plans:
            raise ServiceError("有料プランは決済確認を実装するまで自動作成できません。", 402)
        if self._find(name, required=False):
            raise ServiceError("instance already exists", 409)
        payload = {
            "type": "web_service",
            "name": self._service_name(name, plan_id, template),
            "ownerId": self.settings.render_owner_id,
            "repo": self.settings.render_repo,
            "branch": self.settings.render_branch,
            "autoDeploy": "no",
            "envVars": [
                {"key": "RENTAL_SERVER_NAME", "value": name},
                {"key": "RENTAL_PLAN", "value": plan_id},
                {"key": "RENTAL_TEMPLATE", "value": template},
            ],
            "serviceDetails": self._template_details(template, RENDER_PLAN_MAP[plan_id]),
        }
        created = self._normalize(self._request("POST", "/services", json=payload))
        return {"instance": self._serialize(created), "manage_key": management_key(name, self.key_secret)}

    def get(self, name, key):
        self._verify(name, key)
        service = self._find(name)
        service_id = str(service.get("id", ""))
        if service_id:
            service = self._retrieve(service_id)
        return {"instance": self._serialize(service)}

    def action(self, name, action, key):
        self._verify(name, key)
        service = self._find(name)
        service_id = str(service.get("id", ""))
        endpoint = {"start": "resume", "stop": "suspend", "restart": "restart"}.get(action)
        if not endpoint:
            raise ServiceError("unsupported action", 400)
        self._request("POST", f"/services/{quote(service_id, safe='')}/{endpoint}")
        try:
            fresh = self._retrieve(service_id)
            return {"instance": self._serialize(fresh)}
        except ServiceError:
            return {"ok": True}

    def delete(self, name, key):
        self._verify(name, key)
        service = self._find(name)
        service_id = str(service.get("id", ""))
        self._request("DELETE", f"/services/{quote(service_id, safe='')}")
        return {"ok": True}

    def logs(self, name, key):
        self._verify(name, key)
        service = self._find(name)
        return {
            "logs": (
                "Render APIモードの簡易ログ表示です。\n"
                f"Service ID: {service.get('id', '-')}\n"
                "詳細なアプリログはRender DashboardのLogsで確認できます。"
            )
        }

    def public_url(self, name):
        if not validate_name(name):
            raise ServiceError("not found", 404)
        service = self._find(name)
        details = service.get("serviceDetails") if isinstance(service.get("serviceDetails"), dict) else {}
        url = service.get("url") or details.get("url")
        if not url:
            raise ServiceError("service URL is not ready yet", 503)
        return url
