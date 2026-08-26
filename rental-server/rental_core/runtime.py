from __future__ import annotations

from urllib.parse import quote

import requests

from .errors import ServiceError


class RuntimeController:
    """Control deploy/log operations that are only available on Docker Runner.

    Regular lifecycle actions still go through RentalManager. Keeping deploy control
    separate means Render/shared services keep their existing behavior unchanged.
    """

    def __init__(self, settings, provider_name: str) -> None:
        self.settings = settings
        self.provider_name = provider_name
        self.session = requests.Session()

    @property
    def available(self) -> bool:
        return bool(
            self.provider_name == "runner"
            and self.settings.runner_url
            and self.settings.runner_token
            and self.settings.instance_key_secret
        )

    def _request(self, method: str, path: str, instance_key: str, **kwargs):
        if not self.available:
            raise ServiceError("Deploy機能は隔離Docker Runner接続時のみ利用できます。", 409)
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.settings.runner_token}"
        headers["X-Instance-Key"] = instance_key
        try:
            response = self.session.request(
                method,
                f"{self.settings.runner_url}{path}",
                headers=headers,
                timeout=max(180, int(self.settings.request_timeout_seconds)),
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

    def deploy(self, name: str, instance_key: str, payload: dict):
        return self._request(
            "POST",
            f"/instances/{quote(name, safe='')}/deploy",
            instance_key,
            json=payload,
        )

    def runtime_status(self, name: str, instance_key: str):
        return self._request(
            "GET",
            f"/instances/{quote(name, safe='')}/runtime",
            instance_key,
        )

    def logs(self, name: str, instance_key: str):
        return self._request(
            "GET",
            f"/instances/{quote(name, safe='')}/logs",
            instance_key,
        )
