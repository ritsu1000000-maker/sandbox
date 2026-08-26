import hashlib
import hmac
import io
import os
import re
import shlex
import tarfile
from functools import wraps
from pathlib import PurePosixPath

import docker
from docker.errors import APIError, DockerException, NotFound
from flask import Flask, jsonify, request

from rental_core.config import Settings

settings = Settings.from_env()

app = Flask(__name__)
client = docker.from_env()

RUNNER_TOKEN = settings.runner_token
MAX_INSTANCES = settings.max_instances
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
LABEL_KEY = "rental.server.instance"
RUNTIME_VERSION = "2"
MAX_SYNC_FILES = 100
MAX_SYNC_FILE_BYTES = 512 * 1024
MAX_SYNC_TOTAL_BYTES = 5 * 1024 * 1024
MAX_COMMAND_LENGTH = 2000
MAX_OUTPUT_BYTES = 128 * 1024
MAX_ENV_VARS = 64
MAX_ENV_VALUE_LENGTH = 4096
RUNNER_PUBLIC_BASE_URL = os.environ.get("RUNNER_PUBLIC_BASE_URL", "http://127.0.0.1").strip().rstrip("/")
ALLOWED_EXECUTABLES = {
    "python", "python3", "node", "npm", "npx", "pip", "pip3",
    "ls", "pwd", "cat", "echo",
}

PLANS = {
    "free": {"display_name": "500MB", "storage_gb": 0.5, "price_yen": 0, "mem_limit": "128m", "nano_cpus": 100_000_000},
    "small": {"display_name": "1GB", "storage_gb": 1, "price_yen": 500, "mem_limit": "256m", "nano_cpus": 250_000_000},
    "medium": {"display_name": "10GB", "storage_gb": 10, "price_yen": 1500, "mem_limit": "512m", "nano_cpus": 500_000_000},
    "large": {"display_name": "50GB", "storage_gb": 50, "price_yen": 2000, "mem_limit": "1g", "nano_cpus": 1_000_000_000},
    "xlarge": {"display_name": "100GB", "storage_gb": 100, "price_yen": 4000, "mem_limit": "2g", "nano_cpus": 2_000_000_000},
}

TEMPLATES = {
    "python-web": {"image": "python:3.12-alpine", "port": 8080},
    "node-web": {"image": "node:22-alpine", "port": 3000},
    "nginx": {"image": "nginxinc/nginx-unprivileged:alpine", "port": 8080},
}

SUPERVISOR_COMMAND = r'''
set +e
child=""
cleanup() {
  if [ -n "$child" ]; then kill "$child" 2>/dev/null || true; fi
  exit 0
}
trap cleanup TERM INT
mkdir -p /workspace/project /workspace/runtime
while :; do
  if [ ! -f /workspace/runtime/enabled ]; then
    sleep 1
    continue
  fi
  if [ ! -s /workspace/runtime/start-command ]; then
    echo "[runtime] Start Command is empty" >> /workspace/runtime/app.log
    rm -f /workspace/runtime/enabled
    sleep 1
    continue
  fi
  [ -f /workspace/runtime/env.sh ] && . /workspace/runtime/env.sh
  root="$(cat /workspace/runtime/root-directory 2>/dev/null || printf '.')"
  if [ "$root" = "." ] || [ -z "$root" ]; then
    workdir="/workspace/project"
  else
    workdir="/workspace/project/$root"
  fi
  command="$(cat /workspace/runtime/start-command)"
  if [ ! -d "$workdir" ]; then
    echo "[runtime] Root Directory not found: $root" >> /workspace/runtime/app.log
    rm -f /workspace/runtime/enabled
    sleep 1
    continue
  fi
  echo "[runtime] starting: $command" >> /workspace/runtime/app.log
  cd "$workdir" || { rm -f /workspace/runtime/enabled; continue; }
  sh -lc "$command" >> /workspace/runtime/app.log 2>&1 &
  child=$!
  echo "$child" > /workspace/runtime/app.pid
  wait "$child"
  code=$?
  child=""
  rm -f /workspace/runtime/app.pid
  echo "[runtime] process exited with code $code" >> /workspace/runtime/app.log
  if [ ! -f /workspace/runtime/enabled ]; then
    continue
  fi
  always="$(cat /workspace/runtime/always-on 2>/dev/null || printf '0')"
  if [ "$always" != "1" ]; then
    rm -f /workspace/runtime/enabled
  else
    echo "[runtime] always-on restart in 2s" >> /workspace/runtime/app.log
    sleep 2
  fi
done
'''

NGINX_COMMAND = r'''
cat > /tmp/hosting-nginx.conf <<'EOF'
events {}
http {
  access_log /dev/stdout;
  error_log /dev/stderr warn;
  server {
    listen 8080;
    server_name _;
    root /workspace/project;
    index index.html;
    location / {
      try_files $uri $uri/ /index.html =404;
    }
  }
}
EOF
exec nginx -c /tmp/hosting-nginx.conf -g 'daemon off;'
'''


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not RUNNER_TOKEN:
            return jsonify({"error": "runner token is not configured"}), 503
        value = request.headers.get("Authorization", "")
        expected = f"Bearer {RUNNER_TOKEN}"
        if not hmac.compare_digest(value, expected):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper


def container_name(name: str) -> str:
    return f"rental-{name}"


def volume_name(name: str) -> str:
    return f"rental-data-{name}"


def validate_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def managed_containers(all_states=True):
    return client.containers.list(all=all_states, filters={"label": f"{LABEL_KEY}=true"})


def get_managed_container(name: str):
    container = client.containers.get(container_name(name))
    if container.labels.get(LABEL_KEY) != "true":
        raise PermissionError("not a managed instance")
    return container


def verify_instance_key(container) -> bool:
    supplied = request.headers.get("X-Instance-Key", "").strip()
    expected = container.labels.get("rental.server.manage_sha256", "")
    if not supplied or not expected:
        return False
    return hmac.compare_digest(key_hash(supplied), expected)


def normalize_project_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or len(raw) > 120 or raw.startswith("/"):
        raise ValueError("invalid project path")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts) or len(path.parts) > 8:
        raise ValueError("invalid project path")
    return path.as_posix()


def normalize_root_directory(value: str) -> str:
    raw = str(value or ".").strip().replace("\\", "/")
    if raw in {"", "."}:
        return "."
    if raw.startswith("/") or len(raw) > 120:
        raise ValueError("invalid root directory")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts) or len(path.parts) > 8:
        raise ValueError("invalid root directory")
    return path.as_posix()


def normalize_shell_command(value, label: str, allow_empty=True) -> str:
    command = str(value or "").strip()
    if not command and allow_empty:
        return ""
    if not command or len(command) > MAX_COMMAND_LENGTH or "\x00" in command or "\r" in command or "\n" in command:
        raise ValueError(f"invalid {label}")
    return command


def normalize_environment(value) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_ENV_VARS:
        raise ValueError("invalid environment variables")
    result = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        text = str(raw_value if raw_value is not None else "")
        if not ENV_KEY_RE.fullmatch(key) or len(text) > MAX_ENV_VALUE_LENGTH or "\x00" in text:
            raise ValueError(f"invalid environment variable: {key}")
        if key in {"PORT", "HOST", "HOME", "PIP_TARGET", "PYTHONPATH", "npm_config_cache"}:
            raise ValueError(f"reserved environment variable: {key}")
        result[key] = text
    return result


def _archive_files(entries: list[tuple[str, bytes, int]], root_name=None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        if root_name:
            root = tarfile.TarInfo(root_name)
            root.type = tarfile.DIRTYPE
            root.mode = 0o775
            root.uid = 65534
            root.gid = 65534
            archive.addfile(root)
        for path, content, mode in entries:
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = mode
            info.uid = 65534
            info.gid = 65534
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def sync_project_files(container, files, preserve_dependencies=True):
    if not isinstance(files, list) or len(files) > MAX_SYNC_FILES:
        raise ValueError("too many project files")
    total = 0
    entries = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("invalid project file")
        path = normalize_project_path(item.get("path", ""))
        content = str(item.get("content", "")).encode("utf-8")
        if len(content) > MAX_SYNC_FILE_BYTES:
            raise ValueError("project file too large")
        total += len(content)
        if total > MAX_SYNC_TOTAL_BYTES:
            raise ValueError("project sync exceeds 5MB")
        entries.append((f"project/{path}", content, 0o644))

    container.exec_run(["sh", "-lc", "mkdir -p /workspace/project /workspace/runtime && chown -R 65534:65534 /workspace"], user="0")
    if preserve_dependencies:
        cleanup = r'''
for item in /workspace/project/* /workspace/project/.[!.]* /workspace/project/..?*; do
  [ -e "$item" ] || continue
  case "$item" in
    /workspace/project/.python|/workspace/project/.npm-cache|/workspace/project/node_modules) ;;
    *) rm -rf "$item" ;;
  esac
done
'''
    else:
        cleanup = "rm -rf /workspace/project && mkdir -p /workspace/project && chown 65534:65534 /workspace/project"
    container.exec_run(["sh", "-lc", cleanup], user="0")
    container.put_archive("/workspace", _archive_files(entries, root_name="project"))


def _container_command(template_name: str):
    if template_name == "nginx":
        return ["sh", "-lc", NGINX_COMMAND]
    return ["sh", "-lc", SUPERVISOR_COMMAND]


def _run_managed_container(name: str, template_name: str, plan_name: str, manage_sha256: str):
    template = TEMPLATES[template_name]
    plan = PLANS[plan_name]
    internal_port = template["port"]
    volume = client.volumes.create(name=volume_name(name), labels={LABEL_KEY: "true", "rental.server.name": name})
    container = client.containers.run(
        template["image"],
        command=_container_command(template_name),
        name=container_name(name),
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        mem_limit=plan["mem_limit"],
        nano_cpus=plan["nano_cpus"],
        pids_limit=128,
        read_only=True,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        tmpfs={
            "/tmp": "rw,nosuid,size=128m",
            "/var/cache/nginx": "rw,noexec,nosuid,size=16m",
            "/var/run": "rw,noexec,nosuid,size=4m",
        },
        volumes={volume.name: {"bind": "/workspace", "mode": "rw"}},
        ports={f"{internal_port}/tcp": None},
        labels={
            LABEL_KEY: "true",
            "rental.server.runtime_version": RUNTIME_VERSION,
            "rental.server.name": name,
            "rental.server.template": template_name,
            "rental.server.plan": plan_name,
            "rental.server.storage_gb": str(plan["storage_gb"]),
            "rental.server.price_yen": str(plan["price_yen"]),
            "rental.server.manage_sha256": manage_sha256,
        },
    )
    try:
        container.exec_run(["sh", "-lc", "mkdir -p /workspace/project /workspace/runtime && chown -R 65534:65534 /workspace"], user="0")
    except DockerException:
        pass
    return container


def recreate_legacy_container(container):
    if container.labels.get("rental.server.runtime_version") == RUNTIME_VERSION:
        return container
    name = container.labels.get("rental.server.name", "")
    template_name = container.labels.get("rental.server.template", "python-web")
    plan_name = container.labels.get("rental.server.plan", "free")
    manage_sha256 = container.labels.get("rental.server.manage_sha256", "")
    if not validate_name(name) or template_name not in TEMPLATES or plan_name not in PLANS or not manage_sha256:
        raise ValueError("legacy instance metadata is invalid")
    try:
        container.remove(force=True)
    except DockerException:
        pass
    return _run_managed_container(name, template_name, plan_name, manage_sha256)


def serialize(container):
    container.reload()
    ports = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
    published = None
    for bindings in ports.values():
        if bindings:
            published = bindings[0].get("HostPort")
            break
    plan_id = container.labels.get("rental.server.plan", "unknown")
    plan = PLANS.get(plan_id, {})
    storage = container.labels.get("rental.server.storage_gb")
    price = container.labels.get("rental.server.price_yen")
    try:
        storage_value = float(storage) if storage is not None else plan.get("storage_gb")
    except ValueError:
        storage_value = plan.get("storage_gb")
    if isinstance(storage_value, float) and storage_value.is_integer():
        storage_value = int(storage_value)
    try:
        price_value = int(price) if price is not None else plan.get("price_yen")
    except ValueError:
        price_value = plan.get("price_yen")
    host_port = int(published) if published else None
    return {
        "name": container.labels.get("rental.server.name", container.name),
        "template": container.labels.get("rental.server.template", "unknown"),
        "plan": plan_id,
        "plan_name": plan.get("display_name", plan_id),
        "storage_gb": storage_value,
        "price_yen": price_value,
        "status": container.status,
        "host_port": host_port,
        "url": f"{RUNNER_PUBLIC_BASE_URL}:{host_port}" if host_port else None,
        "container_id": container.short_id,
        "provider": "runner",
        "runtime_version": container.labels.get("rental.server.runtime_version", "1"),
    }


def _runtime_env(template_name: str, user_env: dict[str, str]) -> dict[str, str]:
    port = str(TEMPLATES[template_name]["port"])
    env = {
        "PORT": port,
        "HOST": "0.0.0.0",
        "HOME": "/workspace/project",
        "PIP_TARGET": "/workspace/project/.python",
        "PYTHONPATH": "/workspace/project/.python",
        "npm_config_cache": "/workspace/project/.npm-cache",
    }
    env.update(user_env)
    return env


def _write_runtime_config(container, template_name: str, start_command: str, root_directory: str, always_on: bool, env: dict[str, str]):
    runtime_env = _runtime_env(template_name, env)
    env_script = "\n".join(f"export {key}={shlex.quote(str(value))}" for key, value in runtime_env.items()) + "\n"
    entries = [
        ("runtime/start-command", (start_command + "\n").encode("utf-8"), 0o600),
        ("runtime/root-directory", (root_directory + "\n").encode("utf-8"), 0o600),
        ("runtime/always-on", ("1\n" if always_on else "0\n").encode("ascii"), 0o600),
        ("runtime/env.sh", env_script.encode("utf-8"), 0o600),
    ]
    container.exec_run(["sh", "-lc", "mkdir -p /workspace/runtime && chown -R 65534:65534 /workspace/runtime"], user="0")
    container.put_archive("/workspace", _archive_files(entries, root_name="runtime"))


def _stop_runtime(container):
    command = r'''
rm -f /workspace/runtime/enabled
if [ -f /workspace/runtime/app.pid ]; then
  pid="$(cat /workspace/runtime/app.pid 2>/dev/null || true)"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
fi
sleep 0.2
rm -f /workspace/runtime/app.pid
'''
    container.exec_run(["sh", "-lc", command], user="0")


def _tail_runtime_log(container, lines=300) -> str:
    result = container.exec_run(
        ["sh", "-lc", f"tail -n {int(lines)} /workspace/runtime/app.log 2>/dev/null || true"],
        user="0",
    )
    output = result.output or b""
    return output[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")


@app.get("/health")
def health():
    try:
        client.ping()
        docker_ok = True
    except DockerException:
        docker_ok = False
    return jsonify({"ok": docker_ok and bool(RUNNER_TOKEN), "service": "rental-server-runner", "docker": docker_ok, "configured": bool(RUNNER_TOKEN), "max_instances": MAX_INSTANCES, "runtime_version": RUNTIME_VERSION}), (200 if docker_ok and RUNNER_TOKEN else 503)


@app.get("/plans")
@auth_required
def list_plans():
    return jsonify({"plans": [{"id": key, "name": value["display_name"], "storage_gb": value["storage_gb"], "price_yen": value["price_yen"], "memory": value["mem_limit"], "cpu": value["nano_cpus"] / 1_000_000_000} for key, value in PLANS.items()]})


@app.get("/instances")
@auth_required
def list_instances_internal():
    try:
        return jsonify({"instances": [serialize(c) for c in managed_containers()]})
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/instances/<name>")
@auth_required
def get_instance(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        return jsonify({"instance": serialize(container)})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances")
@auth_required
def create_instance():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip().lower()
    template_name = str(data.get("template", "python-web"))
    plan_name = str(data.get("plan", "free"))
    manage_key = str(data.get("manage_key", ""))
    if not validate_name(name):
        return jsonify({"error": "name must be 1-32 chars: a-z, 0-9, hyphen"}), 400
    if template_name not in TEMPLATES:
        return jsonify({"error": "unknown template"}), 400
    if plan_name not in PLANS:
        return jsonify({"error": "unknown plan"}), 400
    if len(manage_key) < 24:
        return jsonify({"error": "invalid management key"}), 400
    try:
        if len(managed_containers()) >= MAX_INSTANCES:
            return jsonify({"error": "instance limit reached"}), 409
        try:
            client.containers.get(container_name(name))
            return jsonify({"error": "instance already exists"}), 409
        except NotFound:
            pass
        container = _run_managed_container(name, template_name, plan_name, key_hash(manage_key))
        return jsonify({"instance": serialize(container)}), 201
    except (APIError, DockerException) as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances/<name>/deploy")
@auth_required
def deploy_instance(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    data = request.get_json(silent=True) or {}
    try:
        build_command = normalize_shell_command(data.get("build_command", ""), "build command", allow_empty=True)
        start_command = normalize_shell_command(data.get("start_command", ""), "start command", allow_empty=True)
        root_directory = normalize_root_directory(data.get("root_directory", "."))
        user_env = normalize_environment(data.get("env", {}))
        always_on = bool(data.get("always_on", True))
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        container = recreate_legacy_container(container)
        container.reload()
        if container.status != "running":
            container.start()
            container.reload()

        template_name = container.labels.get("rental.server.template", "python-web")
        steps = []
        _stop_runtime(container)
        steps.append({"id": "stop", "status": "done", "message": "previous runtime stopped"})

        sync_project_files(container, data.get("files", []), preserve_dependencies=True)
        steps.append({"id": "sync", "status": "done", "message": "project files synced"})

        if root_directory != ".":
            check = container.exec_run(["sh", "-lc", f"test -d {shlex.quote('/workspace/project/' + root_directory)}"], user="65534:65534")
            if int(check.exit_code) != 0:
                return jsonify({"error": f"Root Directory not found: {root_directory}", "steps": steps}), 400
        workdir = "/workspace/project" if root_directory == "." else f"/workspace/project/{root_directory}"
        runtime_env = _runtime_env(template_name, user_env)

        build_output = ""
        if build_command:
            result = container.exec_run(
                ["timeout", "120s", "sh", "-lc", build_command],
                workdir=workdir,
                user="65534:65534",
                environment=runtime_env,
            )
            raw = result.output or b""
            build_output = raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
            if int(result.exit_code) != 0:
                steps.append({"id": "build", "status": "failed", "message": f"Build Command exited with {int(result.exit_code)}"})
                return jsonify({"error": "Build Command failed", "exit_code": int(result.exit_code), "output": build_output, "steps": steps}), 422
            steps.append({"id": "build", "status": "done", "message": "Build Command completed"})
        else:
            steps.append({"id": "build", "status": "skipped", "message": "Build Command is empty"})

        if template_name == "nginx":
            steps.append({"id": "start", "status": "done", "message": "Nginx serves /workspace/project directly"})
            return jsonify({"ok": True, "instance": serialize(container), "steps": steps, "build_output": build_output, "runtime": {"app_running": container.status == "running", "always_on": True, "root_directory": root_directory}})

        if not start_command:
            return jsonify({"error": "Start Command is required for this runtime", "steps": steps}), 400
        _write_runtime_config(container, template_name, start_command, root_directory, always_on, user_env)
        container.exec_run(["sh", "-lc", "touch /workspace/runtime/enabled && chown 65534:65534 /workspace/runtime/enabled"], user="0")
        steps.append({"id": "start", "status": "done", "message": "Start Command scheduled"})
        return jsonify({"ok": True, "instance": serialize(container), "steps": steps, "build_output": build_output, "runtime": {"app_running": True, "always_on": always_on, "root_directory": root_directory}})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/instances/<name>/runtime")
@auth_required
def runtime_status(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        container.reload()
        template_name = container.labels.get("rental.server.template", "python-web")
        if template_name == "nginx":
            return jsonify({"runtime": {"app_running": container.status == "running", "deployed": True, "always_on": True, "status": container.status}})
        result = container.exec_run(["sh", "-lc", "if [ -f /workspace/runtime/app.pid ] && kill -0 \"$(cat /workspace/runtime/app.pid)\" 2>/dev/null; then printf running; elif [ -f /workspace/runtime/enabled ]; then printf starting; else printf stopped; fi"], user="0")
        state = (result.output or b"").decode("utf-8", errors="replace").strip() or "stopped"
        always_result = container.exec_run(["sh", "-lc", "cat /workspace/runtime/always-on 2>/dev/null || printf 0"], user="0")
        always_on = (always_result.output or b"").decode("utf-8", errors="replace").strip() == "1"
        return jsonify({"runtime": {"app_running": state in {"running", "starting"}, "deployed": state != "stopped", "always_on": always_on, "status": state}})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances/<name>/exec")
@auth_required
def exec_instance(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    data = request.get_json(silent=True) or {}
    command = str(data.get("command", "")).strip()
    if not command or len(command) > MAX_COMMAND_LENGTH:
        return jsonify({"error": "invalid command"}), 400
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return jsonify({"error": "command parse error"}), 400
    if not argv or argv[0] not in ALLOWED_EXECUTABLES:
        return jsonify({"error": "command not allowed in project terminal"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        container = recreate_legacy_container(container)
        container.reload()
        if container.status != "running":
            return jsonify({"error": "instance is not running"}), 409
        sync_project_files(container, data.get("files", []), preserve_dependencies=True)
        template_name = container.labels.get("rental.server.template", "python-web")
        result = container.exec_run(
            ["timeout", "20s", *argv],
            workdir="/workspace/project",
            user="65534:65534",
            environment=_runtime_env(template_name, {}),
        )
        output = result.output or b""
        truncated = len(output) > MAX_OUTPUT_BYTES
        output = output[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return jsonify({"exit_code": int(result.exit_code), "output": output, "truncated": truncated, "cwd": "/workspace/project"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances/<name>/<action>")
@auth_required
def instance_action(name: str, action: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "unsupported action"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop(timeout=8)
        else:
            container.restart(timeout=8)
        return jsonify({"instance": serialize(container)})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.delete("/instances/<name>")
@auth_required
def delete_instance(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        container.remove(force=True)
        try:
            client.volumes.get(volume_name(name)).remove(force=True)
        except (NotFound, DockerException):
            pass
        return jsonify({"ok": True})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/instances/<name>/logs")
@auth_required
def logs(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = get_managed_container(name)
        if not verify_instance_key(container):
            return jsonify({"error": "invalid management key"}), 403
        container_text = container.logs(tail=200, timestamps=True).decode("utf-8", errors="replace")
        app_text = _tail_runtime_log(container)
        text = app_text if app_text else container_text
        if app_text and container_text:
            text = f"--- application ---\n{app_text}\n--- container ---\n{container_text}"
        return jsonify({"logs": text[-MAX_OUTPUT_BYTES:]})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host=settings.runner_host, port=settings.runner_port)
