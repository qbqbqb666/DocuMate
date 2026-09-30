# 功能覆盖检查清单 — v1

> 用于审查 v1 8 屏是否覆盖了所有必需功能.
> 你一项一项打 ✅ / ✗, 决定 P0/P1 要不要补.

---

## ✅ 已覆盖 (UI-Design v1 8 屏)

| 功能点 | 在哪屏 | 备注 |
|---|---|---|
| 用户注册 (邮箱 + 昵称 + 密码) | 02-RegisterPage | 含确认密码 / 数据收集告知 |
| 用户登录 (邮箱 + 密码 + 记住我) | 01-LoginPage | 含错误提示 / 忘记密码占位 |
| 忘记密码提示 | 01-LoginPage | 只占位"下版本支持", 没做完整流程 |
| 首次登录欢迎公告 (3 卡片) | 03-WelcomeModal | 大学生项目 + API Key + 加密 |
| 配置 SiliconFlow API Key | 04-ApiKeyModal | 含 password 显隐 / 外链 / 验证状态 |
| Key 验证 3 态 (loading/success/error) | 04-ApiKeyModal | 含演示切换按钮 |
| 主界面空状态 | 05-EmptyState | 含 3 个快捷入口 / 状态条 |
| 拖拽接收 | 05-EmptyState | 仅设计意图, 没做 drag-over 视觉态 |
| Header (logo + 面包屑 + 头像) | 05/06/07 共用 | 56px 高 |
| Sidebar 三栏切换 (文档/搜索/对话) | 06-MainWorkspace | 含 tab 高亮 |
| 文档列表 (含元数据) | 06-MainWorkspace | 4 条示例数据 |
| 工作区切换入口 (按钮) | 06-MainWorkspace | 按钮在, 但点击后的 picker 没做 |
| 当前文档详情 + 章节目录 + 元数据 | 06-MainWorkspace | 主区分 2/3 + 1/3 |
| 文档 4 个 Action (对话/翻译/PDF/摘要) | 06-MainWorkspace | 入口按钮 |
| AI 对话流 (用户/AI/工具调用 3 种气泡) | 07-ChatPanel | 含工具进行中 spinner |
| 多会话列表 | 07-ChatPanel sidebar | 3 条示例 + 新对话按钮 |
| Session header (标题 / 关联文档 / 新建/清空) | 07-ChatPanel | |
| 输入区 (附件 / textarea / 发送) | 07-ChatPanel | 含快捷键提示 |
| 用户信息 + 头像 + mini 统计 | 08-SettingsDrawer | 含 3 项卡片 (文档/对话/tokens) |
| 账号管理 (改昵称/密码/邮箱) | 08-SettingsDrawer | 仅入口按钮, 点击后的 modal 没做 |
| API Key 管理 (查看/更换/删除) | 08-SettingsDrawer | |
| 工作区管理 (切换/同步/清空索引) | 08-SettingsDrawer | |
| 使用统计 (本月 LLM/Embedding/Vision/PDF) | 08-SettingsDrawer | 仅 mini 视图 |
| 关于 (版本/GitHub/反馈/文档) | 08-SettingsDrawer | |
| 退出登录 | 08-SettingsDrawer | rose 警告色, 但没做确认 modal |

---

## ⚠️ P0 可能漏 (我建议必补)

| # | 功能 | 触发场景 | 建议新屏 |
|---|---|---|---|
| 9 | **AuthGuard loading 状态** | App 启动时 access_token 自动 refresh 中显示什么 | `09-LoadingScreen.html` |
| 10 | **工作区切换 picker** | Sidebar 工作区按钮点击后, 选其他文件夹 | `10-WorkspacePicker.html` (modal/popover) |
| 11 | **拖拽文件 hover 视觉反馈** | EmptyState / MainWorkspace 拖文件时整页 border + ring 闪烁 | 集成到 05/06 的 `drag-over` 态 |
| 12 | **危险操作确认 modal** | 退出登录 / 删除文档 / 清空向量索引 | `11-ConfirmDialog.html` (通用组件) |
| 13 | **Toast 通知系统** | 操作成功/失败的右上角弹出反馈 | `12-ToastSystem.html` (通用组件) |

---

## 🟡 P1 可能要 (按需)

| # | 功能 | 触发场景 | 建议新屏 |
|---|---|---|---|
| 14 | 搜索结果页 | Sidebar Tab "搜索" 点击, 输入关键词后 | `13-SearchResults.html` |
| 15 | 出版级 PDF 渲染完成预览 | 用户点"生成 PDF" 完成后 | `14-PdfPreview.html` |
| 16 | 错误页 (网络/服务不可达) | Auth Service 502, 500, SiliconFlow 限流等 | `15-ErrorPage.html` |
| 17 | 完整密码找回流程 | LoginPage "忘记密码" 真做出来 (邮件验证码) | `16-PasswordReset.html` |
| 18 | 修改昵称 / 邮箱 / 密码 modal | SettingsDrawer 各 "修改" 入口的 popup | `17-AccountEditModals.html` |
| 19 | 详细使用统计页 | SettingsDrawer "查看详细" 点开 | `18-UsageStats.html` (图表) |
| 20 | AI 看图工具 UI (`look_at_image`) | bb-agent 临时眼调用时前端展示 | 集成到 07-ChatPanel |

---

## 🟢 P2 锦上添花 (优先级低)

| 功能 | 备注 |
|---|---|
| 暗色模式 (整套 dark) | 设计文档说并行支持. v1 只做亮色, 等定稿后批量加 `dark:` 前缀 |
| Onboarding 引导 tour | 新用户首次进主界面的 step-by-step 教学 |
| 命令面板 (Cmd+K) | Linear / Raycast 风格快捷命令 |
| 文档批量操作 (多选删除/移动) | 复选框 + 顶栏 action bar |
| 生成历史列表 | `.documate/generations.json` 可视化 |
| 文档版本对比 (diff) | AI 翻译/改写前后对比 |
| 配置同步 (多设备) | 未来 SaaS 升级时 |
| 多语言 (i18n) | 中英切换 |

---

## 你的审查方法

```
1. 浏览器打开每个 HTML, 看渲染是否符合预期
2. 上表 "已覆盖" 一项一项 ✅ 或 ✗ (✗ 的告诉我什么没看到)
3. P0 5 项: 决定要不要补 (我建议都补)
4. P1 7 项: 按优先级标号 (1=最急, 7=可后)
5. 跟我说结果, 我去补
```

## 反馈格式建议

```
P0:
  9 ✓ 必补
  10 ✓ 必补
  11 集成到 05/06 就行
  12 ✓ 通用 modal
  13 ✓ 通用 toast

P1 排序:
  1. 17 密码找回 (我想做完整流程)
  2. 18 账号编辑 modals
  3. 15 PDF 预览
  ...

已覆盖 ✗ 项 (我没看到的):
  - 01 LoginPage 应该有"显示密码"切换, 没看到
  - 06 MainWorkspace 应该有文档右键菜单, 没看到
  - ...
```
