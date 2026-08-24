from .config import PLANS
from .errors import ServiceError
from .providers import RenderProvider, RunnerProvider


class RentalManager:
    def __init__(self, settings):
        self.settings = settings
        if settings.backend_provider == "render":
            self.provider = RenderProvider(settings)
        elif settings.backend_provider == "runner":
            self.provider = RunnerProvider(settings)
        else:
            raise ServiceError(f"unknown backend provider: {settings.backend_provider}", 500)

    @property
    def provider_name(self):
        return self.provider.name

    @property
    def configured(self):
        return self.provider.configured

    def plans(self):
        return {
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
            "provider": self.provider_name,
        }

    def create(self, data):
        if not isinstance(data, dict):
            raise ServiceError("invalid JSON body", 400)
        return self.provider.create(data)

    def get(self, name, key):
        if not key:
            raise ServiceError("management key required", 401)
        return self.provider.get(name, key)

    def action(self, name, action, key):
        if action not in {"start", "stop", "restart"}:
            raise ServiceError("unsupported action", 400)
        if not key:
            raise ServiceError("management key required", 401)
        return self.provider.action(name, action, key)

    def delete(self, name, key):
        if not key:
            raise ServiceError("management key required", 401)
        return self.provider.delete(name, key)

    def public_url(self, name):
        return self.provider.public_url(name)
