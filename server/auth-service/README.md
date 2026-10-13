# DocuMate Auth Service

Independent FastAPI authentication service for DocuMate. User passwords are hashed
with Argon2id. Access tokens are short-lived RS256 JWTs and refresh tokens are opaque,
hashed in PostgreSQL, rotated on refresh, and revoked on logout.

Required environment variables:

- `DOCUMATE_DATABASE_URL`
- `DOCUMATE_JWT_PRIVATE_KEY_PATH`
- `DOCUMATE_JWT_PUBLIC_KEY_PATH`

## 邮箱认证（v0.5.1）

新账号以邮箱注册。登录仅需邮箱和密码；注册和重设密码使用 6 位邮箱验证码。验证码 5 分钟有效，使用一次即失效。邮件服务接受邮件后，同一邮箱进入 60 秒重发等待；发送失败释放等待限制，成功发送前的并发请求仍会被阻止。请求总量、邮箱与 IP 的配额以及验证码尝试限制继续保留。已注册邮箱请求注册验证码时明确提示直接登录；邮件服务明确返回邮箱不存在时提示检查地址。旧用户名账号保留原有登录与刷新令牌行为，不自动绑定邮箱。兼容 v0.5.0 客户端原有的验证码登录请求。

服务端配置文件 `/etc/documate-auth/auth.env` 需要以下变量，授权码仅保存在这台服务器：

```text
DOCUMATE_SMTP_HOST=smtp.163.com
DOCUMATE_SMTP_PORT=465
DOCUMATE_SMTP_USERNAME=documate@163.com
DOCUMATE_SMTP_FROM=documate@163.com
DOCUMATE_SMTP_TLS=ssl
DOCUMATE_SMTP_PASSWORD=<163 邮箱的 SMTP 授权码>
DOCUMATE_EMAIL_CODE_SECRET=<随机且至少 32 字符的服务端密钥>
```

部署文件后，以 root 在服务器运行 `python3 /opt/documate-auth/configure_email.py`，工具会隐藏授权码输入、验证 SMTP 登录、生成验证码密钥，并以权限 0600 写入配置；旧配置会保存在同目录的权限 0600 备份。不要把授权码放进命令参数、桌面应用、Git 或日志。

## 数据库迁移及回退

1. 停止 `documate-auth`，保存当前 `/opt/documate-auth` 的代码和 `/etc/documate-auth/auth.env`，用 `sudo -u postgres pg_dump -Fc documate_auth > /root/documate_auth_before_email.dump` 做数据库备份。备份文件仅限 root 读取。
2. 复制新代码和依赖，在现有 `/opt/documate-auth/.venv` 中安装 `requirements.txt`。以 root 在服务器运行 `sudo -u postgres psql -X -v ON_ERROR_STOP=1 -d documate_auth < /opt/documate-auth/migrations/005_email_auth.sql`。迁移会临时切换到现有表的拥有者 `documate_auth`，新增列和表，不重命名或删除旧数据。重复执行是安全的。
3. 运行 `configure_email.py`，重启服务，检查 `/health` 的 `email_ready=true`；使用真实邮箱走通注册、登录、重设密码、刷新和退出，再发布桌面包。

如果新版服务有问题，恢复备份的旧代码并重启。旧版可使用迁移后的数据库；新增列和表可以留在库中，不必删除任何用户或会话。只有需要完整恢复数据库状态时才使用数据库备份，且应先另外备份当时的新数据。已在独立 PostgreSQL 数据库演练迁移重复执行、旧数据保留、只读权限和旧版代码回退。

