import hmac
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteSessionError(ValueError):
    pass


class RemoteSessionService:
    """Keeps the remotely verified desktop session in the loopback backend memory."""

    def __init__(self, auth_service_url: str | None) -> None:
        self.auth_service_url = (auth_service_url or "").rstrip("/")
        self._access_token: str | None = None
        self._username: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.auth_service_url)

    def set_token(self, access_token: str, expected_username: str | None = None) -> str:
        if not self.enabled:
            raise RemoteSessionError("远程认证服务未配置")
        request = Request(
            f"{self.auth_service_url}/api/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise RemoteSessionError("远程登录令牌校验失败") from error
        username = str(payload.get("username", ""))
        if not username or (expected_username and username != expected_username):
            raise RemoteSessionError("远程登录身份不匹配")
        self._access_token = access_token
        self._username = username
        return username

    def authorize(self, access_token: str | None) -> bool:
        return bool(
            access_token
            and self._access_token
            and hmac.compare_digest(access_token, self._access_token)
        )

    def clear(self) -> None:
        self._access_token = None
        self._username = None

