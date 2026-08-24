import os
import sys

from waitress import serve


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"control", "runner"}:
        raise SystemExit("usage: python run_windows.py <control|runner>")

    mode = sys.argv[1]
    if mode == "runner":
        from runner import app

        host = "127.0.0.1"
        port = int(os.environ.get("RUNNER_PORT", "9000"))
    else:
        from app import app

        host = "0.0.0.0"
        port = int(os.environ.get("PORT", "8080"))

    print(f"Starting {mode} on http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4)


if __name__ == "__main__":
    main()
