import hmac
import os
import re
from functools import wraps

import docker
from docker.errors import APIError, DockerException, NotFound
from flask import Flask, jsonify, request

app = Flask(__name__)
client = docker.from_env()

RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "change-this-runner-token")
MAX_INSTANCES = int(os.environ.get("MAX_INSTANCES", "10"))
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
LABEL_KEY = "rental.server.instance"

PLANS = {
    "small": {"mem_limit": "256m", "nano_cpus": 250_000_000},
    "medium": {"mem_limit": "512m", "nano_cpus": 500_000_000},
}

TEMPLATES = {
    "python-web": {
        "image": "python:3.12-alpine",
        "port": 8080,
        "command": ["python", "-m", "http.server", "8080", "--bind", "0.0.0.0"],
    },
    "node-web": {
        "image": "node:22-alpine",
        "port": 3000,
        "command": [
            "node",
            "-e",
            "require('http').createServer((q,s)=>{s.end('Node rental server is running\\n')}).listen(3000,'0.0.0')",
        ],
    },
    "nginx": {
        "image": "nginxinc/nginx-unprivileged:alpine",
        "port": 8080,
        "command": None,
    },
}


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        value = request.headers.get("Authorization", "")
        expected = f"Bearer {RUNNER_TOKEN}"
        if not hmac.compare_digest(value, expected):
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def container_name(name: str) -> str:
    return f"rental-{name}"


def validate_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def managed_containers(all_states=True):
    return client.containers.list(
        all=all_states,
        filters={"label": f"{LABEL_KEY}=true"},
    )


def serialize(container):
    container.reload()
    ports = container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
    published = None
    for bindings in ports.values():
        if bindings:
            published = bindings[0].get("HostPort")
            break
    return {
        "name": container.labels.get("rental.server.name", container.name),
        "template": container.labels.get("rental.server.template", "unknown"),
        "plan": container.labels.get("rental.server.plan", "unknown"),
        "status": container.status,
        "host_port": int(published) if published else None,
        "container_id": container.short_id,
    }


@app.get("/health")
def health():
    try:
        client.ping()
        docker_ok = True
    except DockerException:
        docker_ok = False
    return jsonify({"ok": docker_ok, "service": "rental-server-runner"}), (200 if docker_ok else 503)


@app.get("/instances")
@auth_required
def list_instances():
    try:
        items = [serialize(c) for c in managed_containers()]
        return jsonify({"instances": items})
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances")
@auth_required
def create_instance():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip().lower()
    template_name = str(data.get("template", "python-web"))
    plan_name = str(data.get("plan", "small"))

    if not validate_name(name):
        return jsonify({"error": "name must be 3-32 chars: a-z, 0-9, hyphen"}), 400
    if template_name not in TEMPLATES:
        return jsonify({"error": "unknown template"}), 400
    if plan_name not in PLANS:
        return jsonify({"error": "unknown plan"}), 400

    try:
        if len(managed_containers()) >= MAX_INSTANCES:
            return jsonify({"error": "instance limit reached"}), 409

        try:
            client.containers.get(container_name(name))
            return jsonify({"error": "instance already exists"}), 409
        except NotFound:
            pass

        template = TEMPLATES[template_name]
        plan = PLANS[plan_name]
        internal_port = template["port"]

        container = client.containers.run(
            template["image"],
            command=template["command"],
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
                "/tmp": "rw,noexec,nosuid,size=64m",
                "/var/cache/nginx": "rw,noexec,nosuid,size=16m",
                "/var/run": "rw,noexec,nosuid,size=4m",
            },
            ports={f"{internal_port}/tcp": None},
            labels={
                LABEL_KEY: "true",
                "rental.server.name": name,
                "rental.server.template": template_name,
                "rental.server.plan": plan_name,
            },
        )
        return jsonify({"instance": serialize(container)}), 201
    except (APIError, DockerException) as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/instances/<name>/<action>")
@auth_required
def instance_action(name: str, action: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    if action not in {"start", "stop", "restart"}:
        return jsonify({"error": "unsupported action"}), 400

    try:
        container = client.containers.get(container_name(name))
        if container.labels.get(LABEL_KEY) != "true":
            return jsonify({"error": "not a managed instance"}), 403
        if action == "start":
            container.start()
        elif action == "stop":
            container.stop(timeout=8)
        else:
            container.restart(timeout=8)
        return jsonify({"instance": serialize(container)})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.delete("/instances/<name>")
@auth_required
def delete_instance(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = client.containers.get(container_name(name))
        if container.labels.get(LABEL_KEY) != "true":
            return jsonify({"error": "not a managed instance"}), 403
        container.remove(force=True)
        return jsonify({"ok": True})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/instances/<name>/logs")
@auth_required
def logs(name: str):
    if not validate_name(name):
        return jsonify({"error": "invalid name"}), 400
    try:
        container = client.containers.get(container_name(name))
        if container.labels.get(LABEL_KEY) != "true":
            return jsonify({"error": "not a managed instance"}), 403
        text = container.logs(tail=200, timestamps=True).decode("utf-8", errors="replace")
        return jsonify({"logs": text})
    except NotFound:
        return jsonify({"error": "instance not found"}), 404
    except DockerException as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("RUNNER_PORT", "9000")))
