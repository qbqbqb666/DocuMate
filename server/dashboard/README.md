# DocuMate 只读数据看板

独立运行，不改现有 auth-service。页面只读取 `users`、`refresh_sessions` 的允许字段；
密码哈希、会话令牌不授予数据库读取权限。数据库查询事务为 READ ONLY，无数据库写入接口。
“有效会话”表示未撤销且未过期的刷新会话，不代表用户当前在线。

## 密码转哈希

登录后在页面底部的“密码转哈希”输入 6 至 128 个字符的应用用户密码，点击生成，
再复制完整结果。接口为 `POST /api/password-hash`，需看板登录 Cookie 与同源请求。
算法与 auth-service 相同：Argon2id，time_cost=3、memory_cost=65536、parallelism=2。
该操作仅计算哈希，不连接数据库，不创建用户，不保存输入密码；结果和输入不会缓存。
同一密码每次生成的哈希不同（随机盐），仍可由现有登录算法校验，不能反向恢复密码。
生成结果保留在当前页面内存中，点击清空、退出登录或刷新页面后移除。
HTTP 页面复制时使用兼容方式；若浏览器不允许自动复制，则选中结果后手动复制。

## 部署位置

- 网页：`http://1.14.67.230:8081/`
- 程序及静态页面：`/opt/documate-dashboard/`
- 看板配置：`/etc/documate-dashboard/dashboard.env`（root 所有，0600）
- systemd 服务：`/etc/systemd/system/documate-dashboard.service`
- 数据源：PostgreSQL 数据库 `documate_auth`，专用只读角色 `documate_dashboard`
- 看板登录初始账号和密码：均为 `qbqb`，不使用应用用户或数据库登录账号。

首次部署：安装本目录代码和依赖到 `/opt/documate-dashboard`，创建无登录系统用户
`documate-dashboard`，以 root 执行 `initialize_server.py`，安装 systemd 单元并启动。
该初始化脚本遇到已有配置或同名角色会停止，不覆盖现有账号。
服务器监听 TCP 8081，云服务器防火墙也须放行该端口。PostgreSQL 5432 不需对公网开放。
目前地址使用 HTTP；提供 HTTPS 时需配套反向代理及启用安全 Cookie。

## 查看或修改看板账号、密码

先通过 SSH 登录服务器，然后查看配置（不要分享完整内容）：

```bash
sudo less /etc/documate-dashboard/dashboard.env
```

按 `q` 退出。修改时：

```bash
sudo nano /etc/documate-dashboard/dashboard.env
```

只改前两行，例：

```ini
DASHBOARD_USERNAME=你的新账号
DASHBOARD_PASSWORD=你的新密码
```

含空格等特殊字符时用双引号包住值。不要改数据库连接或 SESSION_SECRET。
`Ctrl+O`、回车保存，`Ctrl+X` 退出。然后执行：

```bash
sudo systemctl restart documate-dashboard
sudo systemctl status documate-dashboard --no-pager
```

账号/密码改变后，旧 Cookie 自动失效，需要重新登录。服务重启也会清空登录限速记录。
Cookie 为 HttpOnly、SameSite=Strict，8 小时到期；前端不在 localStorage 中保存密码。

## 本地测试

```bash
python3 -m venv /tmp/documate-dashboard-venv
/tmp/documate-dashboard-venv/bin/pip install -r server/dashboard/requirements.txt httpx pytest
/tmp/documate-dashboard-venv/bin/python -m pytest server/dashboard/tests -q
```

部署后验证：未登录访问 `/api/dashboard` 返回 401；正确登录后可查看并分页；
POST/PUT/PATCH/DELETE `/api/dashboard` 返回 405。
以只读数据库账号验证 INSERT/UPDATE/DELETE 和读取敏感列均被数据库拒绝。
