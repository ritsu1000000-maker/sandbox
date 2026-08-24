import os

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/")
def index():
    name = os.environ.get("RENTAL_SERVER_NAME", "rental-server")
    plan = os.environ.get("RENTAL_PLAN", "free")
    return (
        "<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Rental Server</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:80px auto;padding:0 24px;color:#172033}"
        ".box{border:1px solid #dfe5ec;border-radius:14px;padding:28px;background:#fff}"
        "h1{margin-top:0}small{color:#667085}</style></head><body><div class='box'>"
        f"<h1>{name}</h1><p>Python Web サーバーは正常に稼働しています。</p>"
        f"<small>plan: {plan}</small></div></body></html>"
    )


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "rental-tenant-python"})
