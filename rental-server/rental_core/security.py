import base64
import hashlib
import hmac
import re


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")


def validate_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def management_key(name: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), name.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_management_key(name: str, supplied: str, secret: str) -> bool:
    if not supplied or not secret:
        return False
    return hmac.compare_digest(management_key(name, secret), supplied)
