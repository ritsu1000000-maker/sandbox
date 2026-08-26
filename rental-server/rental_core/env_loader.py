from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_local_environment() -> list[Path]:
    """Load local env files without overriding real OS/Render variables.

    Priority is:
      1. Existing process environment (Render / shell)
      2. RENTAL_ENV_FILE, when explicitly set
      3. server.env
      4. .env

    The returned list contains env files that existed and were considered.
    """
    loaded: list[Path] = []

    custom = os.environ.get("RENTAL_ENV_FILE", "").strip()
    candidates: list[Path] = []
    if custom:
        custom_path = Path(custom).expanduser()
        if not custom_path.is_absolute():
            custom_path = PROJECT_ROOT / custom_path
        candidates.append(custom_path)
    else:
        candidates.extend([PROJECT_ROOT / "server.env", PROJECT_ROOT / ".env"])

    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)
            loaded.append(path)

    return loaded
