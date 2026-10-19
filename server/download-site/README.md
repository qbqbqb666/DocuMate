# DocuMate 下载页

公开地址：`https://documate.store/documate/`，通过 Nginx 443 端口提供 HTTPS；旧版客户端使用的 IP HTTP 入口继续保留。

`index.html` 部署到 `/var/www/documate/index.html`。
在现有 Nginx server 块内引入 `nginx-location.conf`，保留已有认证、更新和其他站点路由。

当前提供 Windows x64 和 macOS Apple Silicon v0.4.1 下载，不展示 Windows ARM64。
Mac 当前下载文件为 `DocuMate-v0.4.1-mac-arm64-updates.zip`，包含登录后的更新提示。
原 `DocuMate-v0.4.1-mac-arm64.zip` 保留归档，网页不再指向它。
发布新的安装包时：

1. 上传文件到 `/var/www/documate/downloads/`。
2. 在 `index.html` 底部 `downloads` 配置中填写对应文件名和版本。例如：

```javascript
'windows-x64': {
  url: 'downloads/DocuMate-Setup-v0.4.1-windows-x64.exe',
  version: '0.4.1',
},
```

3. 上传修改后的 HTML，刷新页面即可启用下载。

下载页不需要访问者登录。客户端登录规则保持不变。
这里展示安装包不会自动发布 Windows 更新；更新清单仍在 `/documate-updates/`。

## Mac 版本提示

打包后的 Mac 客户端在登录或恢复登录成功后读取
`https://documate.store/documate/mac-version.json`，与当前应用版本比较。
发现更高的正式版本时弹窗；点击“更新”打开下载网页，点击“稍后”继续使用。
检查失败或 15 秒超时正常进入应用。Mac 不自动下载、安装或删除旧应用。

`mac-version.json` 部署到 `/var/www/documate/mac-version.json`。
其中 `version` 必须对应网页中实际可下载的 Mac ZIP 版本，`notes` 为可选更新说明。
发布顺序为上传并校验新版 ZIP、更新下载网页、最后原子替换版本清单。
不能提前发布指向尚不可下载版本的清单。

用户退出旧应用后，将 ZIP 内的 `DocuMate.app` 拖到“应用程序”文件夹，选择“替换”。
保留 `~/Library/Application Support/documate` 中的会话、工作区配置和 API Key。
此前发布的 ZIP 不含版本提示功能，需要手动安装一次包含该功能的新版。
