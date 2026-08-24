import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = max(1, int(os.environ.get("WEB_CONCURRENCY", "2")))
threads = max(1, int(os.environ.get("GUNICORN_THREADS", "4")))
timeout = max(15, int(os.environ.get("GUNICORN_TIMEOUT", "60")))
graceful_timeout = max(10, int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30")))
keepalive = max(1, int(os.environ.get("GUNICORN_KEEPALIVE", "5")))
max_requests = max(0, int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000")))
max_requests_jitter = max(0, int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "100")))
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "INFO").lower()
capture_output = True
preload_app = False
