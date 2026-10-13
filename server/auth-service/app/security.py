import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return PASSWORDS.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORDS.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenSigner:
    def __init__(self, private_key_path: str, public_key_path: str, issuer: str) -> None:
        self.private_key = Path(private_key_path).read_text(encoding="utf-8")
        self.public_key = Path(public_key_path).read_text(encoding="utf-8")
        self.issuer = issuer

    def access_token(self, user_id: int, username: str, minutes: int, auth_version: int = 0) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": str(user_id),
                "username": username,
                "ver": auth_version,
                "iss": self.issuer,
                "iat": now,
                "exp": now + timedelta(minutes=minutes),
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": "documate-1"},
        )

    def decode(self, token: str) -> dict[str, object]:
        return jwt.decode(token, self.public_key, algorithms=["RS256"], issuer=self.issuer)

    def jwks(self) -> dict[str, object]:
        key = serialization.load_pem_public_key(self.public_key.encode("utf-8"))
        if not isinstance(key, rsa.RSAPublicKey):
            raise RuntimeError("JWT public key must be RSA")
        numbers = key.public_numbers()
        return {
            "keys": [{
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "documate-1",
                "n": _b64uint(numbers.n),
                "e": _b64uint(numbers.e),
            }]
        }


def _b64uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
