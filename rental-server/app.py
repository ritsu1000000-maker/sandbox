import os
from functools import wraps

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "change-this-session-secret")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me-now")
RUNNER_URL = os.environ.get("RUNNER_URL", "http://runner:9000").rstrip("/")
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "change-this-runner-token")


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "authentication required"}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def runner_request(method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {RUNNER_TOKEN}"
    try:
        response = requests.request(
            method,
            f"{RUNNER_URL}{path}",
            headers=headers,
            timeout=15,
            **kwargs,
        )
    except requests.RequestException as exc:
        return None, (jsonify({"error": f"runner unavailable: {exc}"}), 502)

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text or "invalid runner response"}
    return payload, (jsonify(payload), response.status_code)


@app.get("/login")
def login():
    return render_template("login.html")


@app.post("/login")
def login_post():
    if request.form.get("password", "") != ADMIN_PASSWORD:
        return render_template("login.html", error="パスワードが違います"), 401
    session["admin"] = True
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "rental-server-control"})


@app.get("/api/instances")
@login_required
def list_instances():
    _, result = runner_request("GET", "/instances")
    return result


@app.post("/api/instances")
@login_required
def create_instance():
    data = request.get_json(silent=True) or {}
    payload = {
        "name": data.get("name", ""),
        "template": data.get("template", "python-web"),
        "plan": data.get("plan", "small"),
    }
    _, result = runner_request("POST", "/instances", json=payload)
    return result


@app.post("/api/instances/<name>/<action>")
@login_required
def instance_action(name: str, action: str):
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "unsupported action"}), 400
    _, result = runner_request("POST", f"/instances/{name}/{action}")
    return result


@app.delete("/api/instances/<name>")
@login_required
def delete_instance(name: str):
    _, result = runner_request("DELETE", f"/instances/{name}")
    return result


@app.get("/api/instances/<name>/logs")
@login_required
def instance_logs(name: str):
    _, result = runner_request("GET", f"/instances/{name}/logs")
    return result


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
