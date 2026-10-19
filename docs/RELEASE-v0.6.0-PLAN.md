# DocuMate v0.6.0 服务器发布审批清单

日期：2026-10-14。状态：经用户批准已发布 v0.6.0，按用户要求未新增备份，已删除 v0.5.1 旧公开包。

## 文件清单

| 本地来源 | 服务器目标 | 字节数 | SHA256 |
| --- | --- | ---: | --- |
| `release/windows-x64/DocuMate-Setup-v0.6.0-windows-x64.exe` | `/var/www/documate/downloads/DocuMate-Setup-v0.6.0-windows-x64.exe` | 411551224 | `4836482ad8c38b724a13281ebf944e1ee7d578d1f5bcc92cec4b39ad213da39f` |
| `release/mac-arm64/DocuMate-v0.6.0-mac-arm64-updates.zip` | `/var/www/documate/downloads/DocuMate-v0.6.0-mac-arm64-updates.zip` | 510198415 | `57800022c685766fecdf06de916807ba4058117ca7a952b98a4adf336266e436` |
| `release/mac-arm64/DocuMate-v0.6.0-mac-arm64-updates.zip.sha256` | `/var/www/documate/downloads/DocuMate-v0.6.0-mac-arm64-updates.zip.sha256` | 104 | `68b4f9f130b81b4e8a67c507b4e462149204bfd7769964156695e593b2ba4ea4` |
| `release/windows-x64/DocuMate-Setup-v0.6.0-windows-x64.exe` | `/var/www/documate-updates/windows-x64/DocuMate-Setup-v0.6.0-windows-x64.exe` | 411551224 | `4836482ad8c38b724a13281ebf944e1ee7d578d1f5bcc92cec4b39ad213da39f` |
| `release/windows-x64/DocuMate-Setup-v0.6.0-windows-x64.exe.blockmap` | `/var/www/documate-updates/windows-x64/DocuMate-Setup-v0.6.0-windows-x64.exe.blockmap` | 432186 | `879c3e8bb3811af1c066d059a0aa6cb9f1e23b47a646a3ba75b94661c2451d4b` |
| `server/download-site/index.html` | `/var/www/documate/index.html` | 17503 | `ecc4046031acce15793189a0ba10d05fd21fc577c88379eb27a25891dbb977f1` |
| `release/windows-x64/latest.yml` | `/var/www/documate-updates/windows-x64/latest.yml` | 371 | `65a673d38d7c62e3750283fe4939ce45ceac423f756b18636cbce174d066353a` |
| `release/mac-arm64/mac-version.json` | `/var/www/documate/mac-version.json` | 40 | `495552e4bcabada1b69e4efe32e7615802c7670b6068bae22466e4325b29d98f` |

## 执行与验证顺序

1. 用户后续明确要求不新增备份。本次未新增备份，既有 v0.5.1/v0.5.0 回退备份保留。
2. 将上述产物上传服务器暂存目录，按字节数和 SHA256 校验后放入对应公开目录，文件公开读取权限保持可下载。
3. 替换下载页（仅下载链接及版本变化，蓝白视觉和截图资源不变）。
4. 安装包与 blockmap 全部就绪后，最后发布 Windows `latest.yml` 和 Mac `mac-version.json`，保持现有两平台更新机制。
5. 核对下载页、两平台 HTTP 下载、文件大小及哈希、Windows 更新文件及 Mac 版本提示。确认既有认证健康检查可访问。
6. 按用户授权，在新包与元数据验证通过后，直接删除 v0.5.1 的 4 个旧公开文件；服务器暂存目录已清理。

## 不涉及的服务器内容

- `/opt/documate-auth/`、`/etc/documate-auth/auth.env`、认证服务与数据库：无需更改或迁移。
- `/opt/documate-dashboard/`、看板配置及数据库只读权限：无需更改。
- Nginx、SMTP、密钥和访问端口：无需改动。
- 下载页现有 WebP/PNG 原图与应用截图：无需替换或删除。
- Git 提交/推送：不属于本次服务器发布；Windows 打包修复脚本及测试当前仍有本地未提交修改。

## 已验证及边界

- Windows 安装包 411551224 字节；latest.yml 版本、路径、SHA512、大小一致，blockmap 存在。
- Mac ZIP 510198415 字节；ZIP 全部成员完整性与 SHA256 一致，ZIP 内应用版本为 0.6.0。
- 服务器当前公开版本为 0.5.1，下载页与本地差异仅为版本及下载链接，磁盘可用约 25 GB。
- 未确认两平台正式安装包完整 UI、文件引用实际 Agent 对话及真实自动升级验收；产物核查不等同于这些验证。
- 未发布 Windows ARM64，亦未宣称相关构建问题已经解决。


## 发布完成记录

- 8 个服务器目标文件大小、SHA256 和公开读取权限验证通过。
- Windows 安装包通过硬链接用于下载和自动更新两处路径，仅占一份文件数据。
- 新下载地址 HTTP 200、Content-Length 和 Range 内容检查通过；下载页与更新元数据 HTTP 内容哈希匹配本地来源。
- 4 个 v0.5.1 旧公开地址均返回 HTTP 404，删除的文件逻辑大小合计 533279254 字节。
- 认证健康检查 HTTP 200；未改认证服务、数据库、看板或 Nginx 配置，未重启服务。
- 未新增服务器备份，暂存目录已清理；已有历史回退备份未删除。
- 本次验证限于产物和发布链路，未宣称两平台完整安装 UI 或实际自动升级验收通过。
