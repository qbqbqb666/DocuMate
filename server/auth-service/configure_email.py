"""Configure the production SMTP sender without exposing its authorization code."""

import getpass
import os
import secrets
import smtplib
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ENV_FILE = Path("/etc/documate-auth/auth.env")
SENDER = "documate@163.com"
SETTINGS = {
    "DOCUMATE_SMTP_HOST": "smtp.163.com",
    "DOCUMATE_SMTP_PORT": "465",
    "DOCUMATE_SMTP_USERNAME": SENDER,
    "DOCUMATE_SMTP_FROM": SENDER,
    "DOCUMATE_SMTP_TLS": "ssl",
}


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit("请使用 sudo 运行")
    if not ENV_FILE.is_file():
        raise SystemExit(f"配置文件不存在：{ENV_FILE}")
    owner = ENV_FILE.stat()
    password = getpass.getpass("请输入 163 邮箱 SMTP 授权码（输入时不显示）：").strip()
    if not password or any(char.isspace() or char in "'\"\\" for char in password):
        raise SystemExit("授权码格式无效；配置未修改")
    try:
        with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=15,
                              context=ssl.create_default_context()) as client:
            client.login(SENDER, password)
    except (smtplib.SMTPException, OSError):
        raise SystemExit("SMTP 登录验证失败；配置未修改") from None
    old = ENV_FILE.read_text()
    existing_secret = next((line.partition("=")[2].strip() for line in old.splitlines()
                            if line.startswith("DOCUMATE_EMAIL_CODE_SECRET=")), "")
    settings = {
        **SETTINGS,
        "DOCUMATE_SMTP_PASSWORD": password,
        "DOCUMATE_EMAIL_CODE_SECRET": existing_secret if len(existing_secret) >= 32 else secrets.token_urlsafe(48),
    }
    kept = [line for line in old.splitlines() if line.partition("=")[0].strip() not in settings]
    updated = "\n".join([*kept, *(f"{key}={value}" for key, value in settings.items()), ""])
    backup = ENV_FILE.with_name(ENV_FILE.name + ".bak-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(backup_fd, "w") as output:
        output.write(old)
    fd, temporary = tempfile.mkstemp(prefix="auth.env.", dir=ENV_FILE.parent)
    try:
        os.fchown(fd, owner.st_uid, owner.st_gid)
        with os.fdopen(fd, "w") as output:
            output.write(updated)
        os.chmod(temporary, 0o600)
        os.replace(temporary, ENV_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("SMTP 登录验证成功；服务端配置已更新。授权码未显示。")


if __name__ == "__main__":
    main()
