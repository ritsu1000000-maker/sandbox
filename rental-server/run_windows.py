import sys

from waitress import serve

from rental_core.config import Settings


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"control", "runner"}:
        raise SystemExit("usage: python run_windows.py <control|runner>")

    settings = Settings.from_env()
    mode = sys.argv[1]

    if mode == "runner":
        from runner import app
        host = settings.runner_host
        port = settings.runner_port
    else:
        from app import app
        host = settings.app_host
        port = settings.app_port

    print(f"Starting {mode} on http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4)


if __name__ == "__main__":
    main()
