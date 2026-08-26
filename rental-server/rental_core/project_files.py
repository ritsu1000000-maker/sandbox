from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


class ProjectFileError(ValueError):
    pass


class ProjectFileStore:
    MAX_FILES = 100
    MAX_FILE_BYTES = 512 * 1024
    MAX_PATH_LENGTH = 120

    def __init__(self, database, local_root: str = "data/projects") -> None:
        self.database = database
        self.is_redis = bool(getattr(database, "is_redis", False))
        self.local_root = Path(local_root)
        if not self.is_redis:
            self.local_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _redis_prefix(database) -> str:
        return getattr(database, "prefix", "hosting:v1")

    def _redis_key(self, lease_id: int) -> str:
        return f"{self._redis_prefix(self.database)}:project-files:{int(lease_id)}"

    def normalize_path(self, value: str) -> str:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw or len(raw) > self.MAX_PATH_LENGTH or raw.startswith("/"):
            raise ProjectFileError("ファイル名が正しくありません。")
        path = PurePosixPath(raw)
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ProjectFileError("相対パス .. は使用できません。")
        if len(path.parts) > 8:
            raise ProjectFileError("フォルダ階層が深すぎます。")
        return path.as_posix()

    def _local_path(self, lease_id: int, path: str) -> Path:
        normalized = self.normalize_path(path)
        base = (self.local_root / str(int(lease_id))).resolve()
        target = (base / normalized).resolve()
        if target != base and base not in target.parents:
            raise ProjectFileError("ファイルパスが正しくありません。")
        return target

    def list_files(self, lease_id: int) -> list[dict[str, Any]]:
        if self.is_redis:
            rows = self.database.client.hgetall(self._redis_key(lease_id))
            return [
                {"path": path, "size": len(content.encode("utf-8"))}
                for path, content in sorted(rows.items())
            ]

        base = self.local_root / str(int(lease_id))
        if not base.exists():
            return []
        rows = []
        for item in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = item.relative_to(base).as_posix()
            rows.append({"path": rel, "size": item.stat().st_size})
        return rows

    def read_text(self, lease_id: int, path: str) -> str | None:
        normalized = self.normalize_path(path)
        if self.is_redis:
            return self.database.client.hget(self._redis_key(lease_id), normalized)
        target = self._local_path(lease_id, normalized)
        if not target.exists() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def write_text(self, lease_id: int, path: str, content: str) -> dict[str, Any]:
        normalized = self.normalize_path(path)
        text = str(content or "")
        size = len(text.encode("utf-8"))
        if size > self.MAX_FILE_BYTES:
            raise ProjectFileError("1ファイルは512KBまでです。")

        existing = {item["path"] for item in self.list_files(lease_id)}
        if normalized not in existing and len(existing) >= self.MAX_FILES:
            raise ProjectFileError("1サービスにつき100ファイルまでです。")

        if self.is_redis:
            self.database.client.hset(self._redis_key(lease_id), normalized, text)
        else:
            target = self._local_path(lease_id, normalized)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return {"path": normalized, "size": size}

    def delete(self, lease_id: int, path: str) -> bool:
        normalized = self.normalize_path(path)
        if self.is_redis:
            return bool(self.database.client.hdel(self._redis_key(lease_id), normalized))
        target = self._local_path(lease_id, normalized)
        if not target.exists() or not target.is_file():
            return False
        target.unlink()
        return True

    def ensure_defaults(self, lease: dict) -> None:
        if self.list_files(int(lease["id"])):
            return

        name = str(lease.get("display_name") or "My Hosting")
        template = str(lease.get("template") or "nginx")
        index_html = f"""<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>{name}</title>
  <link rel=\"stylesheet\" href=\"style.css\">
</head>
<body>
  <main class=\"card\">
    <p class=\"eyebrow\">HOSTING SERVICE</p>
    <h1>{name}</h1>
    <p>コードエディタからこのページを編集できます。</p>
    <button id=\"hello\">クリック</button>
  </main>
  <script src=\"script.js\"></script>
</body>
</html>
"""
        style_css = """*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,sans-serif;background:#f4f7fb;color:#172033}.card{width:min(620px,calc(100% - 32px));padding:42px;background:#fff;border:1px solid #dfe6ee;border-radius:18px;box-shadow:0 18px 45px rgba(31,45,61,.08)}.eyebrow{color:#1768c4;font-weight:800;font-size:12px;letter-spacing:.12em}h1{margin:.2em 0;font-size:40px}p{color:#66758a}button{border:0;border-radius:9px;padding:11px 18px;background:#1768c4;color:#fff;font-weight:800;cursor:pointer}
"""
        script_js = """document.querySelector('#hello')?.addEventListener('click',()=>alert('Hello from your hosted site!'));
"""
        self.write_text(int(lease["id"]), "index.html", index_html)
        self.write_text(int(lease["id"]), "style.css", style_css)
        self.write_text(int(lease["id"]), "script.js", script_js)

        if template == "python-web":
            self.write_text(int(lease["id"]), "app.py", "from flask import Flask\n\napp = Flask(__name__)\n\n@app.get('/')\ndef index():\n    return 'Hello from Python'\n")
            self.write_text(int(lease["id"]), "requirements.txt", "Flask==3.1.2\ngunicorn==23.0.0\n")
        elif template == "node-web":
            self.write_text(int(lease["id"]), "server.js", "const http=require('http');\nhttp.createServer((req,res)=>{res.end('Hello from Node.js');}).listen(process.env.PORT||3000);\n")
            self.write_text(int(lease["id"]), "package.json", '{\n  "name": "hosted-app",\n  "private": true,\n  "scripts": {"start": "node server.js"}\n}\n')
