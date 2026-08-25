import os
import re
import secrets
import uuid
from datetime import timedelta
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from rental_core import PLANS, RentalDatabase, RentalManager, RentalService, ServiceError, Settings
from rental_core.rate_limit import SlidingWindowLimiter


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
RESOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

app = Flask(__name__)
settings = Settings.from_env()
app.secret_key = settings.session_secret or settings.instance_key_secret or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER_SERVICE_ID")),
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

manager = RentalManager(settings)
database = RentalDatabase(settings.database_url)
rentals = RentalService(settings, database, manager)
create_limiter = SlidingWindowLimiter(settings.create_limit_per_hour, 3600)


def client_key():
    forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    return forwarded or request.remote_addr or "unknown"


def is_admin_user(user) -> bool:
    if not user:
        return False
    email = str(user.get("email", "")).strip().lower()
    return bool(email and email in settings.admin_emails)


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "ログインが必要です。"}), 401
            return redirect(url_for("login_page", next=request.path))
        return fn(*args, **kwargs)
    return wrapped


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "ログインが必要です。"}), 401
            return redirect(url_for("login_page", next=request.path))
        if not is_admin_user(g.user):
            raise ServiceError("Admin権限が必要です。", 403)
        return fn(*args, **kwargs)
    return wrapped


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def require_csrf():
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied and request.form:
        supplied = request.form.get("csrf_token", "")
    if not supplied or not secrets.compare_digest(str(supplied), str(csrf_token())):
        raise ServiceError("CSRF token is invalid", 403)


@app.before_request
def prepare_request():
    request.request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex
    user_id = session.get("user_id")
    g.user = database.get_user(int(user_id)) if user_id else None
    csrf_token()


@app.context_processor
def inject_global_context():
    return {
        "current_user": g.user,
        "current_is_admin": is_admin_user(g.user),
        "csrf_token": csrf_token(),
    }


@app.after_request
def add_response_headers(response):
    response.headers["X-Request-ID"] = getattr(request, "request_id", "")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


@app.errorhandler(ServiceError)
def handle_service_error(exc):
    if request.path.startswith("/api/"):
        response = jsonify(exc.to_dict())
        response.status_code = exc.status
        return response
    return render_template("error.html", active_page="", message=exc.message), exc.status


@app.errorhandler(404)
def handle_not_found(_exc):
    if request.path.startswith("/api/"):
        return jsonify({"error": "not found"}), 404
    return render_template("404.html", active_page=""), 404


# -----------------------------
# Public pages / accounts
# -----------------------------
@app.get("/")
def index():
    return render_template("index.html", active_page="home")


@app.get("/plans")
def plans_page():
    return render_template("plans.html", active_page="plans", plans=PLANS)


@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if g.user:
        return redirect(url_for("dashboard_page"))
    error = None
    email = ""
    if request.method == "POST":
        require_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if not EMAIL_RE.fullmatch(email):
            error = "正しいメールアドレスを入力してください。"
        elif len(password) < 8:
            error = "パスワードは8文字以上にしてください。"
        elif password != confirm:
            error = "確認用パスワードが一致しません。"
        elif database.get_user_by_email(email):
            error = "このメールアドレスはすでに登録されています。"
        else:
            try:
                user = database.create_user(email, generate_password_hash(password))
            except Exception:
                if database.get_user_by_email(email):
                    error = "このメールアドレスはすでに登録されています。"
                else:
                    raise
            else:
                session.clear()
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                return redirect(url_for("dashboard_page"))
    return render_template("signup.html", active_page="signup", error=error, email=email)


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if g.user:
        return redirect(url_for("dashboard_page"))
    error = None
    email = ""
    if request.method == "POST":
        require_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = database.get_user_by_email(email)
        if not user or not check_password_hash(user["password_hash"], password):
            error = "メールアドレスまたはパスワードが違います。"
        else:
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            target = request.args.get("next", "")
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("dashboard_page")
            return redirect(target)
    return render_template("login.html", active_page="login", error=error, email=email)


@app.post("/logout")
@login_required
def logout():
    require_csrf()
    session.clear()
    return redirect(url_for("index"))


# -----------------------------
# Shared hosting public routes
# -----------------------------
def _shared_public_lease(resource_name: str):
    if not RESOURCE_RE.fullmatch(resource_name):
        raise ServiceError("service not found", 404)
    lease = database.get_lease_by_resource_name(resource_name)
    if not lease or lease.get("provider") != "shared" or lease.get("status") == "canceled":
        raise ServiceError("service not found", 404)
    return lease


@app.get("/host/<resource_name>/")
def shared_host(resource_name):
    lease = _shared_public_lease(resource_name)
    running = lease.get("status") == "active"
    status_code = 200 if running else 503
    return render_template(
        "shared_host.html",
        active_page="",
        service=lease,
        running=running,
    ), status_code


@app.get("/host/<resource_name>/health")
def shared_host_health(resource_name):
    lease = _shared_public_lease(resource_name)
    running = lease.get("status") == "active"
    return jsonify({
        "ok": running,
        "service": lease.get("display_name"),
        "provider": "shared",
        "runtime": lease.get("template"),
        "status": "running" if running else "stopped",
    }), 200 if running else 503


# -----------------------------
# Hosting customer pages
# -----------------------------
@app.get("/dashboard")
@login_required
def dashboard_page():
    contracts = rentals.list_contracts(g.user["id"])
    return render_template("dashboard.html", active_page="dashboard", contracts=contracts)


@app.get("/create")
@login_required
def create_page():
    return render_template("create.html", active_page="create")


@app.get("/servers")
@login_required
def servers_page():
    return redirect(url_for("dashboard_page"))


@app.get("/servers/<int:contract_id>")
@login_required
def server_detail_page(contract_id):
    contract = rentals.require_contract(g.user["id"], contract_id)
    return render_template(
        "server_detail.html",
        active_page="dashboard",
        contract=rentals.serialize_contract(contract),
    )


@app.get("/billing")
@login_required
def billing_page():
    contracts = rentals.list_contracts(g.user["id"])
    return render_template("billing.html", active_page="billing", contracts=contracts)


@app.get("/import")
def import_page():
    return redirect(url_for("dashboard_page") if g.user else url_for("login_page"))


# -----------------------------
# Admin dashboard
# -----------------------------
@app.get("/admin")
@admin_required
def admin_page():
    users = database.list_users_admin()
    service_rows = database.list_leases_admin()
    services = []
    for row in service_rows:
        item = rentals.serialize_contract(row)
        item["owner_email"] = row.get("owner_email")
        item["user_id"] = row.get("user_id")
        services.append(item)
    stats = {
        "users": len(users),
        "services": len(services),
        "active": sum(1 for item in services if item.get("status") == "active"),
        "shared": sum(1 for item in services if item.get("provider") == "shared"),
    }
    return render_template(
        "admin.html",
        active_page="admin",
        users=users,
        services=services,
        stats=stats,
    )


@app.post("/api/admin/services/<int:contract_id>/<action>")
@admin_required
def admin_service_action(contract_id, action):
    require_csrf()
    lease = database.get_lease_admin(contract_id)
    if not lease:
        raise ServiceError("サービスが見つかりません。", 404)
    owner_id = int(lease["user_id"])
    if action in {"start", "stop", "restart"}:
        return jsonify(rentals.action(owner_id, contract_id, action))
    if action == "retry":
        return jsonify({"contract": rentals.retry_provision(owner_id, contract_id)})
    if action == "cancel":
        return jsonify({"contract": rentals.cancel(owner_id, contract_id)})
    raise ServiceError("unsupported admin action", 400)


# -----------------------------
# Health / system API
# -----------------------------
@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "hosting-control",
        "provider": manager.provider_name,
        "provider_configured": manager.configured,
        "shared_fallback": True,
        "admin_configured": bool(settings.admin_emails),
        "database": "postgres" if database.is_postgres else "sqlite",
    })


@app.get("/api/system")
def system_info():
    return jsonify({
        "service": "hosting-control",
        "provider": manager.provider_name,
        "provider_configured": manager.configured,
        "database": "postgres" if database.is_postgres else "sqlite",
        "create_limit_per_hour": settings.create_limit_per_hour,
        "features": {
            "accounts": True,
            "contracts": True,
            "ownership": True,
            "csrf": True,
            "postgres": True,
            "render_provider": True,
            "runner_provider": True,
            "shared_hosting_fallback": True,
            "admin_dashboard": True,
        },
    })


@app.get("/api/plans")
def plans():
    return jsonify(manager.plans())


# -----------------------------
# Hosting service API
# -----------------------------
@app.get("/api/contracts")
@login_required
def list_contracts():
    return jsonify({"contracts": rentals.list_contracts(g.user["id"])})


@app.post("/api/contracts")
@login_required
def create_contract():
    require_csrf()
    allowed, retry_after = create_limiter.allow(f"user:{g.user['id']}:{client_key()}")
    if not allowed:
        response = jsonify({
            "error": "サービス作成回数の上限に達しました。しばらく待ってから再試行してください。",
            "retry_after": retry_after,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        return response
    data = request.get_json(silent=True) or {}
    contract = rentals.create_contract(g.user["id"], data)
    return jsonify({"contract": contract}), 201


@app.get("/api/contracts/<int:contract_id>")
@login_required
def get_contract(contract_id):
    return jsonify(rentals.instance_for_contract(g.user["id"], contract_id))


@app.post("/api/contracts/<int:contract_id>/<action>")
@login_required
def contract_action(contract_id, action):
    require_csrf()
    if action not in {"start", "stop", "restart"}:
        raise ServiceError("unsupported action", 400)
    return jsonify(rentals.action(g.user["id"], contract_id, action))


@app.post("/api/contracts/<int:contract_id>/cancel")
@login_required
def cancel_contract(contract_id):
    require_csrf()
    return jsonify({"contract": rentals.cancel(g.user["id"], contract_id)})


@app.get("/s/<int:contract_id>")
@login_required
def open_instance(contract_id):
    payload = rentals.instance_for_contract(g.user["id"], contract_id)
    instance = payload.get("instance") or {}
    url = instance.get("url") or payload["contract"].get("public_url")
    if not url:
        raise ServiceError("公開URLはまだ準備中です。", 404)
    return redirect(url, code=302)


if __name__ == "__main__":
    app.run(host=settings.app_host, port=settings.app_port)
