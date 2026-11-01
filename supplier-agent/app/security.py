import base64
import hashlib
import hmac
import json
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from . import config

_PBKDF2_ROUNDS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_b64, dk_b64 = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def _load_or_create(path, factory) -> bytes:
    config.ensure_dirs()
    if path.exists():
        return path.read_bytes().strip()
    key = factory()
    path.write_bytes(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def fernet() -> Fernet:
    return Fernet(_load_or_create(config.DATA_DIR / "secret.key", Fernet.generate_key))


def session_secret() -> str:
    return _load_or_create(config.DATA_DIR / "session.key", lambda: secrets.token_hex(32).encode()).decode()


def encrypt_json(data: dict) -> str:
    return fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(fernet().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        return {}
