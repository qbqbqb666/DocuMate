import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    jwt_private_key_path: str
    jwt_public_key_path: str
    jwt_issuer: str = "documate-auth"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = ""
    smtp_tls: str = "ssl"
    email_code_secret: str = field(default="", repr=False)

    @property
    def email_ready(self) -> bool:
        return bool(self.smtp_host and self.smtp_username and self.smtp_password and self.smtp_from
                    and self.smtp_tls in {"ssl", "starttls"} and len(self.email_code_secret) >= 32)

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
            smtp_host=os.getenv("DOCUMATE_SMTP_HOST", "").strip(),
            smtp_port=int(os.getenv("DOCUMATE_SMTP_PORT", "465")),
            smtp_username=os.getenv("DOCUMATE_SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("DOCUMATE_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("DOCUMATE_SMTP_FROM", "").strip(),
            smtp_tls=os.getenv("DOCUMATE_SMTP_TLS", "ssl").strip(),
            email_code_secret=os.getenv("DOCUMATE_EMAIL_CODE_SECRET", ""),
        )

