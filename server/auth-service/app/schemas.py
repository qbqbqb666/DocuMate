import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailAddress(ApiModel):
    email: EmailStr = Field(max_length=254)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return str(value).lower()


class SendEmailCode(EmailAddress):
    purpose: Literal["register", "login", "reset"]
    password: str | None = Field(default=None, min_length=6, max_length=128)


class EmailPasswordCredentials(EmailAddress):
    password: str = Field(min_length=6, max_length=128)


class EmailCredentials(EmailPasswordCredentials):
    verification_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    code: str = Field(pattern=r"^[0-9]{6}$")


class Credentials(ApiModel):
    username: str = Field(min_length=8, max_length=32)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise ValueError("账号只能包含字母、数字和下划线")
        return normalized


class RefreshRequest(ApiModel):
    refresh_token: str = Field(min_length=32)


class UserResponse(ApiModel):
    id: int
    username: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None
    has_api_key: bool
    sf_api_key_last4: str | None
    api_key_provider: Literal["siliconflow", "deepseek"] | None
    seen_welcome: bool
    status: Literal["active", "suspended", "banned"]
    created_at: datetime


class AuthResponse(ApiModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse

