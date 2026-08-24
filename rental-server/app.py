import os
import uuid

from flask import Flask, jsonify, redirect, render_template, request

from rental_core import RentalManager, ServiceError, Settings
from rental_core.rate_limit import SlidingWindowLimiter


app = Flask(__name__)
settings = Settings.from_env()
manager = RentalManager(settings)
create_limiter = SlidingWindowLimiter(settings.create_limit_per_hour, 3600)


def instance_key():
    return request.headers.get("X-Instance-Key", "").strip()


def client_key():
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote_addr or "unknown"


@app.before_request
def assign_request_id():
    request.request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex


@app.after_request
def add_response_headers(response):
    response.headers["X-Request-ID"] = getattr(request, "request_id", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    return response


@app.errorhandler(ServiceError)
def handle_service_error(exc):
    response = jsonify(exc.to_dict())
    response.status_code = exc.status
    return response


@app.errorhandler(404)
def handle_not_found(_exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("404.html", active_page=""), 404


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


@app.get("/servers/<name>")
def server_detail_page(name):
    return render_template("server_detail.html", active_page="servers", server_name=name)


@app.get("/import")
def import_page():
    return render_template("import.html", active_page="import")


# -----------------------------
# Health / system API
# -----------------------------
@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "rental-server-control",
        "provider": manager.provider_name,
        "provider_configured": manager.configured,
    })


@app.get("/api/system")
def system_info():
    return jsonify({
        "service": "rental-server-control",
        "provider": manager.provider_name,
        "provider_configured": manager.configured,
        "create_limit_per_hour": settings.create_limit_per_hour,
        "features": {
            "server_detail": True,
            "management_keys": True,
            "rate_limit": True,
            "render_provider": True,
            "runner_provider": True,
        },
    })


@app.get("/api/plans")
def plans():
    return jsonify(manager.plans())


# -----------------------------
# Instance API
# -----------------------------
@app.post("/api/instances")
def create_instance():
    allowed, retry_after = create_limiter.allow(client_key())
    if not allowed:
        response = jsonify({
            "error": "サーバー作成回数の上限に達しました。しばらく待ってから再試行してください。",
            "retry_after": retry_after,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    data = request.get_json(silent=True) or {}
    return jsonify(manager.create(data)), 201


@app.get("/api/instances/<name>")
def get_instance(name):
    return jsonify(manager.get(name, instance_key()))


@app.post("/api/instances/<name>/<action>")
def instance_action(name, action):
    return jsonify(manager.action(name, action, instance_key()))


@app.delete("/api/instances/<name>")
def delete_instance(name):
    return jsonify(manager.delete(name, instance_key()))


@app.get("/api/instances/<name>/logs")
def instance_logs(name):
    return jsonify(manager.logs(name, instance_key()))


@app.get("/s/<name>")
def open_instance(name):
    url = manager.public_url(name)
    if not url:
        raise ServiceError("service URL is not available", 404)
    return redirect(url, code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
