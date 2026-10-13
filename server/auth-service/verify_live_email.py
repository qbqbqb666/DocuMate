"""Interactive, real-mail check against the local production auth service."""

import getpass
import http.client
import json
import time


HOST = "127.0.0.1"
PORT = 8766


def call(path: str, data: dict | None = None, access_token: str | None = None,
         expected: int = 200) -> dict:
    connection = http.client.HTTPConnection(HOST, PORT, timeout=20)
    headers = {"Content-Type": "application/json"}
    if access_token:
        headers["Authorization"] = "Bearer " + access_token
    connection.request("POST" if data is not None else "GET", path,
                       body=json.dumps(data) if data is not None else None, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    connection.close()
    if response.status != expected:
        try:
            detail = json.loads(raw).get("detail", "")
        except (ValueError, AttributeError):
            detail = ""
        raise RuntimeError(f"{path}: HTTP {response.status}，{detail}")
    return json.loads(raw) if raw else {}


def wait_until(ready_at: float) -> None:
    remaining = ready_at - time.monotonic()
    if remaining > 0:
        print(f"等待发送间隔 {remaining:.0f} 秒…")
        time.sleep(remaining + 1)


def code_for(email: str, purpose: str, password: str | None = None) -> tuple[str, str, float]:
    payload = {"email": email, "purpose": purpose}
    if password is not None:
        payload["password"] = password
    result = call("/api/auth/email-code", payload)
    ready_at = time.monotonic() + result["retry_after"]
    print(f"已请求发送{purpose}验证码，请检查 {email} 的收件箱。")
    code = getpass.getpass("请输入收到的 6 位验证码：").strip()
    return result["verification_id"], code, ready_at


def credentials(email: str, password: str, challenge: tuple[str, str, float]) -> dict:
    return {"email": email, "password": password,
            "verification_id": challenge[0], "code": challenge[1]}


def main() -> None:
    if not call("/health").get("email_ready"):
        raise RuntimeError("邮箱服务尚未配置完成")
    email = input("实际收信邮箱 [18982756463@163.com]：").strip() or "18982756463@163.com"
    password = getpass.getpass("为测试账号设置密码（至少 6 位）：")
    if len(password) < 6 or password != getpass.getpass("再次输入密码："):
        raise RuntimeError("密码长度不足或两次输入不一致")
    register_code = code_for(email, "register")
    account = call("/api/auth/register", credentials(email, password, register_code))
    call("/api/user/me", access_token=account["access_token"])
    rotated = call("/api/auth/refresh", {"refresh_token": account["refresh_token"]})
    call("/api/auth/refresh", {"refresh_token": account["refresh_token"]}, expected=401)
    call("/api/auth/logout", {"refresh_token": rotated["refresh_token"]}, expected=204)
    call("/api/auth/refresh", {"refresh_token": rotated["refresh_token"]}, expected=401)
    print("实际邮件注册、刷新轮换和退出通过。")

    logged_in = call("/api/auth/login", {"email": email, "password": password})
    call("/api/user/me", access_token=logged_in["access_token"])
    print("邮箱密码登录通过，无需验证码。")

    wait_until(register_code[2])
    reset_code = code_for(email, "reset")
    new_password = getpass.getpass("设置新密码（至少 6 位）：")
    if len(new_password) < 6 or new_password != getpass.getpass("再次输入新密码："):
        raise RuntimeError("新密码长度不足或两次输入不一致")
    call("/api/auth/reset-password", credentials(email, new_password, reset_code), expected=204)
    call("/api/user/me", access_token=logged_in["access_token"], expected=401)
    call("/api/auth/refresh", {"refresh_token": logged_in["refresh_token"]}, expected=401)
    print("实际邮件重设密码及旧会话撤销通过。")

    final_login = call("/api/auth/login", {"email": email, "password": new_password})
    call("/api/auth/logout", {"refresh_token": final_login["refresh_token"]}, expected=204)
    print("新密码重新登录通过；实际邮箱完整流程验证成功。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        raise SystemExit(f"验证未完成：{error}") from None
