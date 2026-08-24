import base64
import hashlib
import hmac
import os
import re
import secrets
from urllib.parse import quote

import requests
from flask import Flask, jsonify, redirect, render_template, request

app = Flask(__name__)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")

PLANS = {
    "free": {"name": "500MB", "storage_gb": 0.5, "price_yen": 0, "memory": "128MB", "cpu": 0.1},
    "small": {"name": "1GB", "storage_gb": 1, "price_yen": 500, "memory": "256MB", "cpu": 0.25},
    "medium": {"name": "10GB", "storage_gb": 10, "price_yen": 1500, "memory": "512MB", "cpu": 0.5},
    "large": {"name": "50GB", "storage_gb": 50, "price_yen": 2000, "memory": "1GB", "cpu": 1.0},
    "xlarge": {"name": "100GB", "storage_gb": 100, "price_yen": 4000, "memory": "2GB", "cpu": 2.0},
}

RUNNER_URL = os.environ.get("RUNNER_URL", "http://runner:9000").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "change-this-runner-token")

BACKEND_PROVIDER = os.environ.get("BACKEND_PROVIDER", "runner").strip().lower()
RENDER_API_BASE = "https://api.render.com/v1"
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()
RENDER_OWNER_ID = os.environ.get("RENDER_OWNER_ID", "").strip()
RENDER_REPO = os.environ.get(
    "RENDER_TENANT_REPO",
    "https://github.com/ritsu1000000-maker/sandbox",
).strip()
RENDER_BRANCH = os.environ.get("RENDER_TENANT_BRANCH", "rental-server-mvp").strip()
RENDER_REGION = os.environ.get("RENDER_TENANT_REGION", "singapore").strip()
RENDER_SERVICE_PREFIX = os.environ.get("RENDER_SERVICE_PREFIX", "rental").strip().lower()
INSTANCE_KEY_SECRET = os.environ.get("INSTANCE_KEY_SECRET", "").strip()
ALLOW_PAID_RENDER_PLANS = os.environ.get("ALLOW_PAID_RENDER_PLANS", "false").lower() == "true"

RENDER_PLAN_MAP = {
    "free": "free",
    "small": "starter",
    "medium": "standard",
    "large": "pro",
    "xlarge": "pro_plus",
}
TEMPLATE_CODE = {"python-web": "py", "node-web": "node", "nginx": "nginx"}
CODE_TEMPLATE = {value: key for key, value in TEMPLATE_CODE.items()}


def validate_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def instance_key_from_request() -> str:
    return request.headers.get("X-Instance-Key", "").strip()


def runner_request(method: str, path: str, instance_key: str | None = None, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {RUNNER_TOKEN}"
    if instance_key:
        headers["X-Instance-Key"] = instance_key
    try:
        response = requests.request(
            method,
            f"{RUNNER_URL}{path}",
            headers=headers,
            timeout=20,
            **kwargs,
        )
    except requests.RequestException as exc:
        return None, (jsonify({"error": f"runner unavailable: {exc}"}), 502)
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text or "invalid runner response"}
    return payload, (jsonify(payload), response.status_code)


def render_config_error():
    missing = []
    if not RENDER_API_KEY:
        missing.append("RENDER_API_KEY")
    if not RENDER_OWNER_ID:
        missing.append("RENDER_OWNER_ID")
    if not missing:
        return None
    return jsonify({
        "error": "Render API is not configured",
        "missing": missing,
        "hint": "Set BACKEND_PROVIDER=render and add the missing variables in Render Environment.",
    }), 503


def render_headers():
    return {
        "Authorization": f"Bearer {RENDER_API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def render_request(method: str, path: str, **kwargs):
    config_error = render_config_error()
    if config_error:
        return None, config_error
    try:
        response = requests.request(
            method,
            f"{RENDER_API_BASE}{path}",
            headers=render_headers(),
            timeout=30,
            **kwargs,
        )
    except requests.RequestException as exc:
        return None, (jsonify({"error": f"Render API unavailable: {exc}"}), 502)
    if response.status_code == 204:
        return {}, (jsonify({"ok": True}), 204)
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text or f"Render API HTTP {response.status_code}"}
    if not response.ok:
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error") or payload
        else:
            detail = payload
        return payload, (jsonify({"error": f"Render API error: {detail}"}), response.status_code)
    return payload, (jsonify(payload), response.status_code)


def normalize_service(value):
    if not isinstance(value, dict):
        return {}
    service = value.get("service")
    return service if isinstance(service, dict) else value


def render_service_base(name: str) -> str:
    return f"{RENDER_SERVICE_PREFIX}-{name}-"


def render_service_name(name: str, plan: str, template: str) -> str:
    return f"{render_service_base(name)}{plan}-{TEMPLATE_CODE[template]}"


def parse_render_service_name(full_name: str):
    prefix = f"{RENDER_SERVICE_PREFIX}-"
    if not full_name.startswith(prefix):
        return None
    rest = full_name[len(prefix):]
    parts = rest.rsplit("-", 2)
    if len(parts) != 3:
        return None
    user_name, plan, template_code = parts
    template = CODE_TEMPLATE.get(template_code)
    if plan not in PLANS or not template or not validate_name(user_name):
        return None
    return user_name, plan, template


def render_management_key(name: str) -> str:
    secret = INSTANCE_KEY_SECRET or RENDER_API_KEY
    digest = hmac.new(secret.encode("utf-8"), name.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_render_key(name: str, supplied: str) -> bool:
    if not supplied or not RENDER_API_KEY:
        return False
    return hmac.compare_digest(render_management_key(name), supplied)


def list_render_services():
    payload, result = render_request(
        "GET",
        "/services",
        params={"ownerId": RENDER_OWNER_ID, "limit": 100, "includePreviews": "false"},
    )
    if payload is None:
        return None, result
    if not isinstance(payload, list):
        return [], None
    return [normalize_service(item) for item in payload], None


def find_render_service(name: str):
    services, error = list_render_services()
    if error:
        return None, error
    base = render_service_base(name)
    for service in services:
        full_name = str(service.get("name", ""))
        if full_name.startswith(base) and parse_render_service_name(full_name):
            return service, None
    return None, (jsonify({"error": "instance not found"}), 404)


def retrieve_render_service(service_id: str):
    payload, result = render_request("GET", f"/services/{quote(service_id, safe='')}")
    if payload is None:
        return None, result
    return normalize_service(payload), None


def serialize_render_service(service):
    parsed = parse_render_service_name(str(service.get("name", "")))
    if not parsed:
        return None
    name, plan_id, template = parsed
    plan = PLANS[plan_id]
    service_details = service.get("serviceDetails") if isinstance(service.get("serviceDetails"), dict) else {}
    url = service.get("url") or service_details.get("url")
    suspended = str(service.get("suspended", "not_suspended"))
    status = "exited" if suspended == "suspended" else "running"
    return {
        "name": name,
        "template": template,
        "plan": plan_id,
        "plan_name": plan["name"],
        "storage_gb": plan["storage_gb"],
        "price_yen": plan["price_yen"],
        "status": status,
        "host_port": None,
        "url": url,
        "container_id": service.get("id", "-"),
        "provider": "render",
    }


def render_template_details(template: str, render_plan: str):
    common = {"plan": render_plan, "region": RENDER_REGION, "numInstances": 1}
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


def create_render_instance(data):
    name = str(data.get("name", "")).strip().lower()
    template = str(data.get("template", "python-web"))
    plan_id = str(data.get("plan", "free"))
    if not validate_name(name):
        return jsonify({"error": "name must be 3-32 chars: a-z, 0-9, hyphen"}), 400
    if template not in TEMPLATE_CODE:
        return jsonify({"error": "unknown template"}), 400
    if plan_id not in PLANS:
        return jsonify({"error": "unknown plan"}), 400
    if plan_id != "free" and not ALLOW_PAID_RENDER_PLANS:
        return jsonify({
            "error": "有料プランの自動作成はまだ無効です。決済確認なしでRenderの有料サービスを作成すると運営側に課金されるため、現在は500MB無料プランのみ自動作成できます。"
        }), 402
    existing, error = find_render_service(name)
    if existing:
        return jsonify({"error": "instance already exists"}), 409
    if error and error[1] != 404:
        return error
    render_plan = RENDER_PLAN_MAP[plan_id]
    payload = {
        "type": "web_service",
        "name": render_service_name(name, plan_id, template),
        "ownerId": RENDER_OWNER_ID,
        "repo": RENDER_REPO,
        "branch": RENDER_BRANCH,
        "autoDeploy": "no",
        "envVars": [
            {"key": "RENTAL_SERVER_NAME", "value": name},
            {"key": "RENTAL_PLAN", "value": plan_id},
            {"key": "RENTAL_TEMPLATE", "value": template},
        ],
        "serviceDetails": render_template_details(template, render_plan),
    }
    created, result = render_request("POST", "/services", json=payload)
    if created is None:
        return result
    service = normalize_service(created)
    instance = serialize_render_service(service)
    if not instance:
        return jsonify({"error": "Render created the service but returned an unexpected response"}), 502
    return jsonify({"instance": instance, "manage_key": render_management_key(name)}), 201


def render_instance(name: str, key: str):
    if not validate_name(name):
        return None, (jsonify({"error": "invalid name"}), 400)
    if not verify_render_key(name, key):
        return None, (jsonify({"error": "invalid management key"}), 403)
    service, error = find_render_service(name)
    if error:
        return None, error
    service_id = str(service.get("id", ""))
    if service_id:
        fresh, fresh_error = retrieve_render_service(service_id)
        if fresh_error is None and fresh:
            service = fresh
    return service, None


# -----------------------------
# Web pages
# -----------------------------
@app.get("/")
def index():
    return render_template("index.html", active_page="home")


@app.get("/plans")
def plans_page():
    return render_template("plans.html", active_page="plans")


@app.get("/create")
def create_page():
    return render_template("create.html", active_page="create")


@app.get("/servers")
def servers_page():
    return render_template("servers.html", active_page="servers")


@app.get("/import")
def import_page():
    return render_template("import.html", active_page="import")


# -----------------------------
# Health / public API
# -----------------------------
@app.get("/health")
def health():
    configured = True
    if BACKEND_PROVIDER == "render":
        configured = bool(RENDER_API_KEY and RENDER_OWNER_ID)
    return jsonify({
        "ok": True,
        "service": "rental-server-control",
        "provider": BACKEND_PROVIDER,
        "provider_configured": configured,
    })


@app.get("/api/plans")
def plans():
    return jsonify({
        "plans": [
            {
                "id": key,
                "name": value["name"],
                "storage_gb": value["storage_gb"],
                "price_yen": value["price_yen"],
                "memory": value["memory"],
                "cpu": value["cpu"],
            }
            for key, value in PLANS.items()
        ],
        "provider": BACKEND_PROVIDER,
    })


@app.post("/api/instances")
def create_instance():
    data = request.get_json(silent=True) or {}
    if BACKEND_PROVIDER == "render":
        config_error = render_config_error()
        if config_error:
            return config_error
        return create_render_instance(data)
    manage_key = secrets.token_urlsafe(32)
    payload = {
        "name": data.get("name", ""),
        "template": data.get("template", "python-web"),
        "plan": data.get("plan", "free"),
        "manage_key": manage_key,
    }
    response, result = runner_request("POST", "/instances", json=payload)
    if response is None:
        return result
    _, status = result
    if status == 201:
        response["manage_key"] = manage_key
        return jsonify(response), 201
    return result


@app.get("/api/instances/<name>")
def get_instance(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    if BACKEND_PROVIDER == "render":
        service, error = render_instance(name, key)
        if error:
            return error
        return jsonify({"instance": serialize_render_service(service)})
    _, result = runner_request("GET", f"/instances/{name}", instance_key=key)
    return result


@app.post("/api/instances/<name>/<action>")
def instance_action(name: str, action: str):
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "unsupported action"}), 400
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    if BACKEND_PROVIDER == "render":
        service, error = render_instance(name, key)
        if error:
            return error
        service_id_raw = str(service.get("id", ""))
        service_id = quote(service_id_raw, safe="")
        endpoint = {"start": "resume", "stop": "suspend", "restart": "restart"}[action]
        _, result = render_request("POST", f"/services/{service_id}/{endpoint}")
        if result[1] >= 400:
            return result
        fresh, fresh_error = retrieve_render_service(service_id_raw)
        if fresh_error:
            return jsonify({"ok": True}), 200
        return jsonify({"instance": serialize_render_service(fresh)})
    _, result = runner_request("POST", f"/instances/{name}/{action}", instance_key=key)
    return result


@app.delete("/api/instances/<name>")
def delete_instance(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    if BACKEND_PROVIDER == "render":
        service, error = render_instance(name, key)
        if error:
            return error
        service_id = quote(str(service.get("id", "")), safe="")
        _, result = render_request("DELETE", f"/services/{service_id}")
        if result[1] >= 400:
            return result
        return jsonify({"ok": True})
    _, result = runner_request("DELETE", f"/instances/{name}", instance_key=key)
    return result


@app.get("/api/instances/<name>/logs")
def instance_logs(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    if BACKEND_PROVIDER == "render":
        service, error = render_instance(name, key)
        if error:
            return error
        return jsonify({
            "logs": (
                "Render APIモードでは、この画面のログ取得はまだ簡易表示です。\n"
                f"Service ID: {service.get('id', '-')}\n"
                "実ログはRender DashboardのLogsから確認できます。"
            )
        })
    _, result = runner_request("GET", f"/instances/{name}/logs", instance_key=key)
    return result


@app.get("/s/<name>")
def open_render_instance(name: str):
    if BACKEND_PROVIDER != "render" or not validate_name(name):
        return jsonify({"error": "not found"}), 404
    service, error = find_render_service(name)
    if error:
        return error
    service_details = service.get("serviceDetails") if isinstance(service.get("serviceDetails"), dict) else {}
    url = service.get("url") or service_details.get("url")
    if not url:
        return jsonify({"error": "service URL is not ready yet"}), 503
    return redirect(url, code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
