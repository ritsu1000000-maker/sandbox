import base64
import hashlib
import hmac
import re


# 1-32 characters. Lowercase ASCII letters, numbers and hyphens.
# A hyphen cannot be the first or last character.
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


def validate_name(name: str) -> bool:
    return bool(NAME_RE.fullmatch(name or ""))


def management_key(secret: str, name: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), name.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_management_key(secret: str, name: str, supplied: str) -> bool:
    if not supplied or not secret:
        return False
    return hmac.compare_digest(management_key(secret, name), supplied)
