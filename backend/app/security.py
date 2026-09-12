import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

SECRET_KEY = os.getenv("JWT_SECRET", "development-only-change-me")
TOKEN_TTL_HOURS = 24


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    salt_hex, digest_hex = encoded.split(":", 1)
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: int) -> str:
    header = _encode(b'{"alg":"HS256","typ":"JWT"}')
    payload = _encode(json.dumps({"sub": str(user_id), "exp": int((datetime.now(timezone.utc) + timedelta(hours=TOKEN_TTL_HOURS)).timestamp())}, separators=(",", ":")).encode())
    signature = hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_encode(signature)}"


def decode_access_token(token: str) -> int:
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signature)):
            raise ValueError("invalid signature")
        claims = json.loads(_decode(payload))
        if claims["exp"] < datetime.now(timezone.utc).timestamp():
            raise ValueError("expired token")
        return int(claims["sub"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from error
