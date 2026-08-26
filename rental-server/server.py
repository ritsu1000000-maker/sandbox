from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import sys

from rental_core.env_loader import PROJECT_ROOT, load_local_environment


def env_path() -> Path:
    custom = os.environ.get("RENTAL_ENV_FILE", "").strip()
    if custom:
        path = Path(custom).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path
    return PROJECT_ROOT / "server.env"


def init_env(force: bool = False) -> int:
    target = env_path()
    template = PROJECT_ROOT / "server.env.example"
    if target.exists() and not force:
        print(f"server env already exists: {target}")
        return 0
    if not template.exists():
        print("server.env.example is missing", file=sys.stderr)
        return 1

    text = template.read_text(encoding="utf-8")
    text = text.replace("SESSION_SECRET=CHANGE_ME_GENERATED", f"SESSION_SECRET={secrets.token_hex(32)}")
    text = text.replace("INSTANCE_KEY_SECRET=CHANGE_ME_GENERATED", f"INSTANCE_KEY_SECRET={secrets.token_hex(32)}")
    text = text.replace("RUNNER_TOKEN=CHANGE_ME_GENERATED", f"RUNNER_TOKEN={secrets.token_hex(32)}")
    target.write_text(text, encoding="utf-8")
    print(f"created: {target}")
    print("Local mode uses SQLite automatically.")
    print("For Render, set RENDER_API_KEY / RENDER_OWNER_ID / DATABASE_URL in Render Environment.")
    return 0


def check_config() -> int:
    loaded = load_local_environment()
    from rental_core.config import Settings

    settings = Settings.from_env()
    database_kind = "postgres" if settings.database_url.startswith(("postgres://", "postgresql://")) else "sqlite"
    print("Rental Server configuration")
    print(f"  provider             : {settings.backend_provider}")
    print(f"  provider configured  : {settings.provider_configured}")
    print(f"  database             : {database_kind}")
    print(f"  web                  : {settings.app_host}:{settings.app_port}")
    print(f"  runner               : {settings.runner_host}:{settings.runner_port}")
    print(f"  max instances        : {settings.max_instances}")
    print(f"  create limit/hour    : {settings.create_limit_per_hour}")
    print(f"  lease days           : {settings.lease_days}")
    print(f"  log level            : {settings.log_level}")
    print(f"  env files            : {', '.join(str(x) for x in loaded) or '(none)'}")

    warnings: list[str] = []
    if settings.backend_provider not in {"runner", "render"}:
        warnings.append("BACKEND_PROVIDER must be runner or render")
    if settings.backend_provider == "runner":
        if not settings.runner_token or settings.runner_token == "change-this-runner-token":
            warnings.append("RUNNER_TOKEN is missing or unsafe")
    if settings.backend_provider == "render":
        if not settings.render_api_key:
            warnings.append("RENDER_API_KEY is missing")
        if not settings.render_owner_id:
            warnings.append("RENDER_OWNER_ID is missing")
        if database_kind != "postgres":
            warnings.append("Production Render should use PostgreSQL DATABASE_URL so customer contracts survive deploys")
    if not settings.instance_key_secret:
        warnings.append("INSTANCE_KEY_SECRET is missing")
    if not settings.session_secret:
        warnings.append("SESSION_SECRET is missing")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")
        return 2

    print("\nConfiguration looks usable.")
    return 0


def run_web() -> int:
    load_local_environment()
    from rental_core.config import Settings
    from app_ext import app

    settings = Settings.from_env()
    try:
        from waitress import serve
        print(f"Starting web on http://{settings.app_host}:{settings.app_port}")
        serve(app, host=settings.app_host, port=settings.app_port, threads=4)
    except KeyboardInterrupt:
        pass
    return 0


def run_runner() -> int:
    load_local_environment()
    from rental_core.config import Settings
    from runner import app

    settings = Settings.from_env()
    try:
        from waitress import serve
        print(f"Starting runner on http://{settings.runner_host}:{settings.runner_port}")
        serve(app, host=settings.runner_host, port=settings.runner_port, threads=4)
    except KeyboardInterrupt:
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Rental Server configuration and runtime CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init-env", help="create server.env with generated secrets")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing server.env")
    sub.add_parser("check", help="validate environment configuration")
    sub.add_parser("web", help="run the control web service")
    sub.add_parser("runner", help="run the local Docker runner")

    args = parser.parse_args()
    if args.command == "init-env":
        return init_env(force=args.force)
    if args.command == "check":
        return check_config()
    if args.command == "web":
        return run_web()
    if args.command == "runner":
        return run_runner()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
