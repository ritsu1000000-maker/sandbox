from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


class ServiceConfigError(ValueError):
    pass


ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


DEFAULTS = {
    "python-web": {
        "build_command": "pip install -r requirements.txt",
        "start_command": "python -m gunicorn app:app --bind 0.0.0.0:$PORT",
    },
    "node-web": {
        "build_command": "npm install",
        "start_command": "npm start",
    },
    "nginx": {
        "build_command": "",
        "start_command": "",
    },
}


class ServiceConfigStore:
    """Private per-service settings.

    Config is intentionally stored separately from ProjectFileStore so environment
    variables and runtime commands can never be served as public project assets.
    Redis deployments use a private Redis key; local deployments use data/configs.
    """

    MAX_COMMAND_LENGTH = 2000
    MAX_ENV_VARS = 64
    MAX_ENV_VALUE_LENGTH = 4096
    MAX_ROOT_LENGTH = 120

    def __init__(self, database, local_root: str = "data/configs") -> None:
        self.database = database
        self.is_redis = bool(getattr(database, "is_redis", False))
        self.local_root = Path(local_root)
        if not self.is_redis:
            self.local_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _redis_prefix(database) -> str:
        return getattr(database, "prefix", "hosting:v1")

    def _redis_key(self, lease_id: int) -> str:
        return f"{self._redis_prefix(self.database)}:service-config:{int(lease_id)}"

    def _local_path(self, lease_id: int) -> Path:
        return self.local_root / f"{int(lease_id)}.json"

    def normalize_root(self, value: str) -> str:
        raw = str(value or ".").strip().replace("\\", "/")
        if raw in {"", "."}:
            return "."
        if raw.startswith("/") or len(raw) > self.MAX_ROOT_LENGTH:
            raise ServiceConfigError("Root Directory が正しくありません。")
        path = PurePosixPath(raw)
        if any(part in {"", ".", ".."} for part in path.parts) or len(path.parts) > 8:
            raise ServiceConfigError("Root Directory に .. や深すぎる階層は使用できません。")
        return path.as_posix()

    def normalize_command(self, value: str, field_name: str) -> str:
        command = str(value or "").strip()
        if len(command) > self.MAX_COMMAND_LENGTH:
            raise ServiceConfigError(f"{field_name} は2000文字までです。")
        if "\x00" in command or "\r" in command or "\n" in command:
            raise ServiceConfigError(f"{field_name} に改行やNUL文字は使用できません。")
        return command

    def normalize_env(self, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ServiceConfigError("環境変数は key/value のオブジェクトで指定してください。")
        if len(value) > self.MAX_ENV_VARS:
            raise ServiceConfigError("環境変数は64個までです。")
        result: dict[str, str] = {}
        for key, raw_value in value.items():
            name = str(key or "").strip()
            if not ENV_KEY_RE.fullmatch(name):
                raise ServiceConfigError(f"環境変数名が正しくありません: {name}")
            if name in {"PORT", "HOST", "HOME", "PIP_TARGET", "PYTHONPATH", "npm_config_cache"}:
                raise ServiceConfigError(f"{name} はシステム予約済みです。")
            text = str(raw_value if raw_value is not None else "")
            if len(text) > self.MAX_ENV_VALUE_LENGTH or "\x00" in text:
                raise ServiceConfigError(f"{name} の値が長すぎるか不正です。")
            result[name] = text
        return result

    def defaults_for(self, template: str) -> dict[str, Any]:
        runtime = DEFAULTS.get(str(template or ""), DEFAULTS["python-web"])
        return {
            "build_command": runtime["build_command"],
            "start_command": runtime["start_command"],
            "root_directory": ".",
            "always_on": True,
            "auto_deploy": False,
            "env": {},
            "updated_at": None,
        }

    def load(self, lease_id: int, template: str) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.is_redis:
            raw = self.database.client.get(self._redis_key(lease_id))
            if raw:
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    data = {}
        else:
            path = self._local_path(lease_id)
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}

        merged = self.defaults_for(template)
        if isinstance(data, dict):
            merged.update({key: data[key] for key in merged if key in data})
        merged["env"] = dict(merged.get("env") or {})
        return merged

    def save(self, lease_id: int, template: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ServiceConfigError("設定データが正しくありません。")
        current = self.load(lease_id, template)
        if "build_command" in payload:
            current["build_command"] = self.normalize_command(payload.get("build_command", ""), "Build Command")
        if "start_command" in payload:
            current["start_command"] = self.normalize_command(payload.get("start_command", ""), "Start Command")
        if "root_directory" in payload:
            current["root_directory"] = self.normalize_root(payload.get("root_directory", "."))
        if "always_on" in payload:
            current["always_on"] = bool(payload.get("always_on"))
        if "auto_deploy" in payload:
            current["auto_deploy"] = bool(payload.get("auto_deploy"))
        if "env" in payload:
            current["env"] = self.normalize_env(payload.get("env"))
        current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        encoded = json.dumps(current, ensure_ascii=False, separators=(",", ":"))
        if self.is_redis:
            self.database.client.set(self._redis_key(lease_id), encoded)
        else:
            path = self._local_path(lease_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(encoded, encoding="utf-8")
        return current

    def delete(self, lease_id: int) -> None:
        if self.is_redis:
            self.database.client.delete(self._redis_key(lease_id))
            return
        path = self._local_path(lease_id)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
