from __future__ import annotations

import secrets

from flask import Blueprint, g, jsonify, request, session

from .errors import ServiceError
from .project_files import ProjectFileError
from .runtime import RuntimeController
from .security import management_key
from .service_config import ServiceConfigError, ServiceConfigStore


def build_runtime_blueprint(settings, database, rentals, project_files, manager):
    bp = Blueprint("runtime_api", __name__)
    configs = ServiceConfigStore(database)
    runtime = RuntimeController(settings, manager.provider_name)

    def require_user():
        if not g.user:
            raise ServiceError("ログインが必要です。", 401)
        return int(g.user["id"])

    def require_csrf():
        expected = str(session.get("csrf_token") or "")
        supplied = str(request.headers.get("X-CSRF-Token", "") or "")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            raise ServiceError("CSRF token is invalid", 403)

    def require_lease(contract_id: int):
        user_id = require_user()
        lease = rentals.require_contract(user_id, contract_id)
        if lease.get("status") == "canceled":
            raise ServiceError("利用終了済みサービスです。", 409)
        return user_id, lease

    def project_snapshot(contract_id: int) -> list[dict]:
        files = []
        total = 0
        for item in project_files.list_files(contract_id):
            path = str(item.get("path", ""))
            try:
                content = project_files.read_text(contract_id, path)
            except ProjectFileError:
                continue
            if content is None:
                continue
            size = len(content.encode("utf-8"))
            total += size
            if total > 5 * 1024 * 1024:
                raise ServiceError("Deploy可能なプロジェクトサイズは5MBまでです。", 413)
            files.append({"path": path, "content": content})
        return files

    @bp.get("/api/contracts/<int:contract_id>/settings")
    def get_runtime_settings(contract_id):
        _user_id, lease = require_lease(contract_id)
        config = configs.load(contract_id, str(lease.get("template") or "python-web"))
        return jsonify({
            "settings": config,
            "provider": lease.get("provider"),
            "runtime_available": bool(runtime.available and lease.get("provider") == "runner"),
        })

    @bp.put("/api/contracts/<int:contract_id>/settings")
    def put_runtime_settings(contract_id):
        require_csrf()
        _user_id, lease = require_lease(contract_id)
        payload = request.get_json(silent=True) or {}
        try:
            config = configs.save(contract_id, str(lease.get("template") or "python-web"), payload)
        except ServiceConfigError as exc:
            raise ServiceError(str(exc), 400) from exc
        return jsonify({"settings": config})

    @bp.post("/api/contracts/<int:contract_id>/deploy")
    def deploy_runtime(contract_id):
        require_csrf()
        _user_id, lease = require_lease(contract_id)
        if lease.get("provider") != "runner" or manager.provider_name != "runner":
            raise ServiceError("Deploy機能は隔離Docker Runnerで発行されたサービスのみ利用できます。", 409)

        project_files.ensure_defaults(lease)
        config = configs.load(contract_id, str(lease.get("template") or "python-web"))
        data = request.get_json(silent=True) or {}
        if isinstance(data, dict) and data:
            try:
                config = configs.save(contract_id, str(lease.get("template") or "python-web"), data)
            except ServiceConfigError as exc:
                raise ServiceError(str(exc), 400) from exc

        key = management_key(settings.instance_key_secret, lease["resource_name"])
        result = runtime.deploy(
            lease["resource_name"],
            key,
            {
                "files": project_snapshot(contract_id),
                "build_command": config.get("build_command", ""),
                "start_command": config.get("start_command", ""),
                "root_directory": config.get("root_directory", "."),
                "always_on": bool(config.get("always_on", True)),
                "env": config.get("env", {}),
            },
        )
        result["settings"] = config
        return jsonify(result)

    @bp.get("/api/contracts/<int:contract_id>/runtime")
    def get_runtime_status(contract_id):
        _user_id, lease = require_lease(contract_id)
        if lease.get("provider") != "runner" or manager.provider_name != "runner":
            return jsonify({
                "runtime": {
                    "app_running": lease.get("status") == "active",
                    "deployed": lease.get("provider") == "shared",
                    "always_on": lease.get("provider") == "shared",
                    "status": "shared" if lease.get("provider") == "shared" else "unavailable",
                }
            })
        key = management_key(settings.instance_key_secret, lease["resource_name"])
        return jsonify(runtime.runtime_status(lease["resource_name"], key))

    @bp.get("/api/contracts/<int:contract_id>/runtime-logs")
    def get_runtime_logs(contract_id):
        _user_id, lease = require_lease(contract_id)
        if lease.get("provider") != "runner" or manager.provider_name != "runner":
            return jsonify({"logs": "このProviderでは隔離Runnerの実行ログはありません。"})
        key = management_key(settings.instance_key_secret, lease["resource_name"])
        return jsonify(runtime.logs(lease["resource_name"], key))

    return bp
