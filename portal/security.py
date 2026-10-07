import base64
import hashlib
import hmac
import os
import secrets


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    result = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return 'pbkdf2$600000$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(result).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt, digest = encoded.split('$')
        result = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(result, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def private_file(path):
    if os.name != 'nt':
        os.chmod(path, 0o600)

