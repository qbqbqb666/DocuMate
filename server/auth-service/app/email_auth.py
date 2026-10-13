import hashlib
import hmac
import logging
import math
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import HTTPException
from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import Settings
from .database import AuthRateBucket, EmailChallenge, User


CODE_ERROR = "验证码错误、已过期或已使用，请重新获取"
logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def code_hash(secret: str, challenge_id: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def limit(db: Session, key: str, maximum: int, seconds: int) -> None:
    now = utcnow()
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(AuthRateBucket).values(
        key=hashlib.sha256(key.encode()).hexdigest(), count=1,
        expires_at=now + timedelta(seconds=seconds),
    )
    expired = AuthRateBucket.expires_at <= now
    statement = statement.on_conflict_do_update(
        index_elements=[AuthRateBucket.key],
        set_={"count": case((expired, 1), else_=AuthRateBucket.count + 1),
              "expires_at": case((expired, statement.excluded.expires_at), else_=AuthRateBucket.expires_at)},
    ).returning(AuthRateBucket.count)
    count = db.scalar(statement)
    db.commit()
    if count > maximum:
        expires = db.get(AuthRateBucket, hashlib.sha256(key.encode()).hexdigest()).expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        remaining = max(1, math.ceil((expires - utcnow()).total_seconds()))
        raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": str(remaining)})


class SMTPMailer:
    def __init__(self, config: Settings):
        self.config = config

    def send(self, email: str, code: str, purpose: str) -> None:
        if not self.config.email_ready:
            raise HTTPException(503, "邮件服务尚未配置")
        message = EmailMessage()
        message["From"] = f"DocuMate <{self.config.smtp_from}>"
        message["To"] = email
        label = {"register": "注册", "login": "登录", "reset": "重设密码"}[purpose]
        message["Subject"] = f"DocuMate {label}验证码"
        message.set_content(f"你的 DocuMate {label}验证码是：{code}\n\n5 分钟内有效，仅可使用一次。")
        context = ssl.create_default_context()
        stage = "connect"
        try:
            if self.config.smtp_tls == "ssl":
                client = smtplib.SMTP_SSL(self.config.smtp_host, self.config.smtp_port,
                                         timeout=15, context=context)
            else:
                client = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15)
            with client:
                if self.config.smtp_tls == "starttls":
                    stage = "starttls"
                    client.starttls(context=context)
                stage = "login"
                client.login(self.config.smtp_username, self.config.smtp_password)
                stage = "send"
                if client.send_message(message):
                    logger.warning("SMTP recipients refused stage=send")
                    raise HTTPException(503, "邮件暂时无法发送，请稍后重试")
                stage = "quit"
        except smtplib.SMTPRecipientsRefused as error:
            responses = list(error.recipients.values())
            logger.warning("SMTP recipient refused codes=%s", [item[0] for item in responses])
            if responses and all(item[0] in (550, 551, 553) and
                                 any(term in item[1].lower() for term in
                                     (b"user not found", b"no such user", b"user unknown", b"mailbox not found"))
                                 for item in responses):
                raise HTTPException(400, "该邮箱不存在，请检查邮箱地址") from None
            raise HTTPException(503, "收件邮箱被邮件服务拒绝，请检查邮箱地址或稍后重试") from None
        except (smtplib.SMTPException, OSError) as error:
            logger.warning("SMTP failed stage=%s type=%s smtp_code=%s errno=%s",
                           stage, type(error).__name__, getattr(error, "smtp_code", None),
                           getattr(error, "errno", None))
            if stage != "quit":
                raise HTTPException(503, "邮件暂时无法发送，请稍后重试") from None


def send_code(db: Session, config: Settings, mailer, email: str, purpose: str,
              user: User | None, eligible: bool) -> dict:
    now = utcnow()
    interval_key = hashlib.sha256(f"send:interval:{email}".encode()).hexdigest()
    existing = db.get(AuthRateBucket, interval_key)
    if existing:
        expires = existing.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > now:
            remaining = max(1, math.ceil((expires - now).total_seconds()))
            raise HTTPException(429, "验证码已发送，请等待后再试", headers={"Retry-After": str(remaining)})
    reservation = None
    if eligible:
        limit(db, f"send:interval:{email}", 1, 60)
        reservation = db.get(AuthRateBucket, interval_key).expires_at
    challenge_id = secrets.token_hex(16)
    code = f"{secrets.randbelow(1000000):06d}"
    db.execute(update(EmailChallenge).where(
        EmailChallenge.email == email, EmailChallenge.purpose == purpose,
        EmailChallenge.consumed_at.is_(None),
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    record = EmailChallenge(id=challenge_id, email=email, purpose=purpose,
                            user_id=user.id if user else None, auth_version=user.auth_version if user else 0,
                            code_hash=code_hash(config.email_code_secret, challenge_id, code),
                            expires_at=now + timedelta(minutes=5))
    db.add(record)
    db.commit()
    if eligible:
        try:
            mailer.send(email, code, purpose)
        except HTTPException:
            record.consumed_at = utcnow()
            db.execute(delete(AuthRateBucket).where(AuthRateBucket.key == interval_key,
                       AuthRateBucket.expires_at == reservation))
            db.commit()
            raise
        record.delivered = True
        db.execute(update(AuthRateBucket).where(AuthRateBucket.key == interval_key,
                   AuthRateBucket.expires_at == reservation).values(expires_at=utcnow() + timedelta(seconds=60)))
        db.commit()
    return {"verification_id": challenge_id, "expires_in": 300, "retry_after": 60 if eligible else 0,
            "message": "如邮箱符合条件，验证码已发送，请检查收件箱。"}


def consume_code(db: Session, config: Settings, email: str, purpose: str,
                 challenge_id: str, code: str) -> EmailChallenge:
    now = utcnow()
    record = db.scalar(select(EmailChallenge).where(
        EmailChallenge.id == challenge_id, EmailChallenge.email == email,
        EmailChallenge.purpose == purpose, EmailChallenge.delivered.is_(True),
        EmailChallenge.consumed_at.is_(None), EmailChallenge.expires_at > now,
        EmailChallenge.attempts < 5,
    ).with_for_update())
    if record is None:
        raise HTTPException(400, CODE_ERROR)
    if not hmac.compare_digest(record.code_hash, code_hash(config.email_code_secret, challenge_id, code)):
        db.execute(update(EmailChallenge).where(EmailChallenge.id == challenge_id).values(
            attempts=EmailChallenge.attempts + 1))
        db.commit()
        raise HTTPException(400, CODE_ERROR)
    result = db.execute(update(EmailChallenge).where(
        EmailChallenge.id == challenge_id, EmailChallenge.consumed_at.is_(None),
        EmailChallenge.attempts < 5, EmailChallenge.expires_at > now,
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise HTTPException(400, CODE_ERROR)
    return record
