import os
import secrets

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

RUNNER_URL = os.environ.get("RUNNER_URL", "http://runner:9000").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "change-this-runner-token")


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


def instance_key_from_request() -> str:
    return request.headers.get("X-Instance-Key", "").strip()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "rental-server-control"})


@app.get("/api/plans")
def plans():
    _, result = runner_request("GET", "/plans")
    return result


@app.post("/api/instances")
def create_instance():
    data = request.get_json(silent=True) or {}
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

    body, status = result
    if status == 201:
        response["manage_key"] = manage_key
        return jsonify(response), 201
    return result


@app.get("/api/instances/<name>")
def get_instance(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    _, result = runner_request("GET", f"/instances/{name}", instance_key=key)
    return result


@app.post("/api/instances/<name>/<action>")
def instance_action(name: str, action: str):
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "unsupported action"}), 400
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    _, result = runner_request("POST", f"/instances/{name}/{action}", instance_key=key)
    return result


@app.delete("/api/instances/<name>")
def delete_instance(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    _, result = runner_request("DELETE", f"/instances/{name}", instance_key=key)
    return result


@app.get("/api/instances/<name>/logs")
def instance_logs(name: str):
    key = instance_key_from_request()
    if not key:
        return jsonify({"error": "management key required"}), 401
    _, result = runner_request("GET", f"/instances/{name}/logs", instance_key=key)
    return result


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
