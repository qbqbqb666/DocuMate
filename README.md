# DocuMate

## 本地启动

安装依赖后，分别启动后端和前端：

```bash
uv sync
npm install
uv run python -m src.backend
npm run dev
```

默认地址：

- 后端：`http://127.0.0.1:8765`
- 前端：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8765/docs`

可从 `.env.example` 复制启动参数到 `.env`。健康检查为
`/api/health`，资源就绪检查为 `/api/ready`。

## 桌面应用

开发模式会同时启动 Vite 页面和 Electron；Electron 负责启动、监听并在退出时关闭本地后端：

```bash
npm run dev:desktop
```

构建前端和 PyInstaller 后端，再生成当前平台的安装包：

```bash
npm run build:desktop
npm run package:mac
```

macOS 初版产物位于 `release/mac-arm64/DocuMate.app`，目前未做 Apple 签名和公证。应用配置、日志及 SQLite 数据库存放在 Electron 的用户数据目录；工作区文档仍保留在用户选择的本地文件夹中。

常用验证命令：

```bash
uv run pytest
npm run typecheck
npm run test:electron
```
