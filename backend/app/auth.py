"""Minimal signed bearer sessions and PBKDF2 password hashing.

For production, prefer a mature identity provider, email verification, password
reset flow, MFA for administrators, and a managed secret store.
"""
import base64, hashlib, hmac, json, secrets, time
from .config import settings

ITERATIONS = 310_000

def hash_password(password: str) -> str:
    if len(password) < 10 or len(password) > 256:
        raise ValueError("Password must contain 10-256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt, expected = encoded.split("$")
        if scheme != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(base64.urlsafe_b64encode(actual).decode(), expected)
    except Exception:
        return False

def _secret() -> bytes:
    secret = settings.auth_secret
    if len(secret) < 32:
        raise RuntimeError("AUTH_SECRET must be configured with at least 32 characters")
    return secret.encode()

def create_access_token(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "exp": int(time.time()) + settings.auth_token_minutes*60}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return payload + "." + signature

def read_access_token(token: str) -> int | None:
    try:
        payload, signature = token.split(".", 1)
        expected = base64.urlsafe_b64encode(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected): return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if int(data["exp"]) < int(time.time()): return None
        return int(data["sub"])
    except Exception:
        return None
