import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_private_key_path: str
    jwt_public_key_path: str
    jwt_issuer: str = "documate-auth"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "database_url": os.getenv("DOCUMATE_DATABASE_URL", "").strip(),
            "jwt_private_key_path": os.getenv("DOCUMATE_JWT_PRIVATE_KEY_PATH", "").strip(),
            "jwt_public_key_path": os.getenv("DOCUMATE_JWT_PUBLIC_KEY_PATH", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing settings: {', '.join(missing)}")
        return cls(
            **required,
            jwt_issuer=os.getenv("DOCUMATE_JWT_ISSUER", "documate-auth").strip(),
            access_token_minutes=int(os.getenv("DOCUMATE_ACCESS_TOKEN_MINUTES", "30")),
            refresh_token_days=int(os.getenv("DOCUMATE_REFRESH_TOKEN_DAYS", "30")),
        )

