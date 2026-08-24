from dataclasses import dataclass
import os

from .env_loader import load_local_environment


PLANS = {
    "free": {"name": "500MB", "storage_gb": 0.5, "price_yen": 0, "memory": "128MB", "cpu": 0.1},
    "small": {"name": "1GB", "storage_gb": 1, "price_yen": 500, "memory": "256MB", "cpu": 0.25},
    "medium": {"name": "10GB", "storage_gb": 10, "price_yen": 1500, "memory": "512MB", "cpu": 0.5},
    "large": {"name": "50GB", "storage_gb": 50, "price_yen": 2000, "memory": "1GB", "cpu": 1.0},
    "xlarge": {"name": "100GB", "storage_gb": 100, "price_yen": 4000, "memory": "2GB", "cpu": 2.0},
}

RENDER_PLAN_MAP = {
    "free": "free",
    "small": "starter",
    "medium": "standard",
    "large": "pro",
    "xlarge": "pro_plus",
}

TEMPLATE_CODE = {"python-web": "py", "node-web": "node", "nginx": "nginx"}
CODE_TEMPLATE = {value: key for key, value in TEMPLATE_CODE.items()}


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, value)


@dataclass(frozen=True)
class Settings:
    backend_provider: str
    app_host: str
    app_port: int
    runner_host: str
    runner_port: int
    runner_url: str
    runner_token: str
    max_instances: int
    render_api_key: str
    render_owner_id: str
    render_repo: str
    render_branch: str
    render_region: str
    render_service_prefix: str
    instance_key_secret: str
    session_secret: str
    database_url: str
    allow_paid_render_plans: bool
    create_limit_per_hour: int
    request_timeout_seconds: int
    log_level: str
    lease_days: int

    @classmethod
    def from_env(cls):
        # Local files never override real process variables, so Render/shell values win.
        load_local_environment()

        explicit_provider = os.environ.get("BACKEND_PROVIDER", "").strip().lower()
        on_render = os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"} or bool(os.environ.get("RENDER_SERVICE_ID"))
        backend_provider = explicit_provider or ("render" if on_render else "runner")

        runner_host = os.environ.get("RUNNER_HOST", "127.0.0.1").strip() or "127.0.0.1"
        runner_port = _int_env("RUNNER_PORT", 9000)
        runner_url = os.environ.get("RUNNER_URL", "").strip().rstrip("/") or f"http://{runner_host}:{runner_port}"

        return cls(
            backend_provider=backend_provider,
            app_host=os.environ.get("APP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            app_port=_int_env("PORT", 8080),
            runner_host=runner_host,
            runner_port=runner_port,
            runner_url=runner_url,
            runner_token=os.environ.get("RUNNER_TOKEN", "").strip(),
            max_instances=_int_env("MAX_INSTANCES", 10),
            render_api_key=os.environ.get("RENDER_API_KEY", "").strip(),
            render_owner_id=os.environ.get("RENDER_OWNER_ID", "").strip(),
            render_repo=os.environ.get("RENDER_TENANT_REPO", "https://github.com/ritsu1000000-maker/sandbox").strip(),
            render_branch=os.environ.get("RENDER_TENANT_BRANCH", "rental-server-mvp").strip(),
            render_region=os.environ.get("RENDER_TENANT_REGION", "singapore").strip(),
            render_service_prefix=os.environ.get("RENDER_SERVICE_PREFIX", "rental").strip().lower() or "rental",
            instance_key_secret=os.environ.get("INSTANCE_KEY_SECRET", "").strip(),
            session_secret=os.environ.get("SESSION_SECRET", "").strip(),
            database_url=os.environ.get("DATABASE_URL", "").strip(),
            allow_paid_render_plans=os.environ.get("ALLOW_PAID_RENDER_PLANS", "false").strip().lower() == "true",
            create_limit_per_hour=_int_env("CREATE_LIMIT_PER_HOUR", 10),
            request_timeout_seconds=_int_env("REQUEST_TIMEOUT_SECONDS", 30),
            log_level=(os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"),
            lease_days=_int_env("LEASE_DAYS", 30),
        )

    @property
    def provider_configured(self):
        if self.backend_provider == "render":
            return bool(self.render_api_key and self.render_owner_id and self.instance_key_secret)
        if self.backend_provider == "runner":
            return bool(self.runner_url and self.runner_token and self.instance_key_secret)
        return False
