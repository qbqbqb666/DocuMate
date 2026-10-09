# Windows 服务器更新

客户端从自己的轻量服务器检查更新，不使用 GitHub 更新源。

- x64：`http://1.14.67.230/documate-updates/windows-x64/`
- ARM64：`http://1.14.67.230/documate-updates/windows-arm64/`
- macOS 不使用 Windows 更新源，通过独立的 `mac-version.json` 提示手动更新；浏览器预览和未打包的开发模式不检查更新。

登录（含恢复登录）成功后检查，主界面和新用户引导在检查后才加载。
有新版先显示更新界面，点击“立即更新”后才下载；没有跳过按钮。
下载并校验成功后关闭 Python 后端并启动安装，安装后重新启动应用。
检查失败或 15 秒超时放行；已发现新版后下载/安装失败保持更新页，可重试。
这不是离线登录，也不是服务端版本封禁。

## 构建

项目版本在 package.json、package-lock.json、pyproject.toml、uv.lock 中保持一致。
首次引入更新器的版本为 0.4.1。原 0.4.0 必须手动安装一次新版。

在 Windows 项目根目录执行：

```powershell
npm.cmd ci --include=dev
npm.cmd run package:win:x64
# 需要 ARM64 时执行（需安装对应编译工具）
npm.cmd run package:win:arm64
```

输出分别在 `release/windows-x64/`、`release/windows-arm64/`。
每套包含 `.exe`、`.exe.blockmap` 和 `latest.yml`，不能跨架构混用。
脚本使用 `--publish never`，只生成产物，不自动上传。
`app-update.yml` 是安装包内部配置，不要替换为 `latest.yml`。

## 服务器

在现有 Nginx server 块引入 `server/updates/nginx-location.conf`，
文件目录是 `/var/www/documate-updates/windows-x64/` 和
`/var/www/documate-updates/windows-arm64/`。
Nginx 配置修改前备份，`nginx -t` 成功后 reload，保留现有认证反向代理。
本次已部署目录和 Nginx 路由；原站点配置备份在服务器
`/etc/nginx/sites-available/default.before-documate-updates-6Tq8oq`。
2026-10-09 已发布 Windows x64 0.4.1 安装包、blockmap 和 `latest.yml`，文件校验一致且公网可读取。
已用真实 Generic 更新器验证同版放行、模拟低版本发现新版，以及检查时不预下载。
ARM64 尚未发布；Windows 安装覆盖、重启和用户数据保留仍需实机验收。
没有安装包时不要发布虚假的 latest.yml；404 会按检查失败放行。

每次发布提高版本号，先上传 `.exe`、`.exe.blockmap`，校验文件后，
把 `latest.yml` 上传为临时文件，再在服务器同目录原子重命名为 `latest.yml`。
保留旧安装包和 blockmap 供差分下载使用。回滚清单前保留备份，不复用旧版本号发布不同内容。
GitHub Release 可以归档相同产物，但不影响服务器发布状态。

当前按既有 IP HTTP 方案接入。SHA-512 校验只能检测文件与清单是否一致，
不能防止 HTTP 清单和文件同时被篡改；正式公开分发应补齐可信 HTTPS 或签名验证。

## 发布前 Windows 实机验收

1. 安装带更新器的旧测试版本，发布更高版本到对应架构目录。
2. 登录后出现更新页；未点击时服务器没有安装包下载请求。
3. 点击后显示进度；断网后仍停在更新页，恢复网络后重试。
4. 下载成功后安装重启，版本变更，工作区、会话、API Key 保留。
5. 同版本不提示；更新源不可达时放行；x64/ARM64 不串包。

本地状态机测试不替代 Windows 安装升级验收。
