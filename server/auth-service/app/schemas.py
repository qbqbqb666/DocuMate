import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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

