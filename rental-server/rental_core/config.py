from dataclasses import dataclass
import os


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


@dataclass(frozen=True)
class Settings:
    backend_provider: str
    runner_url: str
    runner_token: str
    render_api_key: str
    render_owner_id: str
    render_repo: str
    render_branch: str
    render_region: str
    render_service_prefix: str
    instance_key_secret: str
    allow_paid_render_plans: bool
    create_limit_per_hour: int

    @classmethod
    def from_env(cls):
        return cls(
            backend_provider=os.environ.get("BACKEND_PROVIDER", "runner").strip().lower(),
            runner_url=os.environ.get("RUNNER_URL", "http://runner:9000").rstrip("/"),
            runner_token=os.environ.get("RUNNER_TOKEN", "change-this-runner-token"),
            render_api_key=os.environ.get("RENDER_API_KEY", "").strip(),
            render_owner_id=os.environ.get("RENDER_OWNER_ID", "").strip(),
            render_repo=os.environ.get("RENDER_TENANT_REPO", "https://github.com/ritsu1000000-maker/sandbox").strip(),
            render_branch=os.environ.get("RENDER_TENANT_BRANCH", "rental-server-mvp").strip(),
            render_region=os.environ.get("RENDER_TENANT_REGION", "singapore").strip(),
            render_service_prefix=os.environ.get("RENDER_SERVICE_PREFIX", "rental").strip().lower(),
            instance_key_secret=os.environ.get("INSTANCE_KEY_SECRET", "").strip(),
            allow_paid_render_plans=os.environ.get("ALLOW_PAID_RENDER_PLANS", "false").lower() == "true",
            create_limit_per_hour=max(1, int(os.environ.get("CREATE_LIMIT_PER_HOUR", "10"))),
        )

    @property
    def provider_configured(self):
        if self.backend_provider == "render":
            return bool(self.render_api_key and self.render_owner_id)
        return bool(self.runner_url and self.runner_token)
