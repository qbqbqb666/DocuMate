# DocuMate UI 设计 v1 — 我做的版本

> 基于 `design/UI-DESIGN-SPEC.md` (Apple HIG + lucide-react + 0 emoji)
> 每个 HTML 单文件 + 浏览器双击预览 + 你审查反馈我改

## 进度 (一次性出全, 等你审查)

| # | 屏幕 | 文件 | 状态 | 主要功能 |
|---|---|---|---|---|
| 01 | LoginPage | [`01-LoginPage.html`](./01-LoginPage.html) | ⏳ 等审查 | 双栏 + 渐变品牌 + 4 chip + 邮箱/密码/记住我 |
| 02 | RegisterPage | [`02-RegisterPage.html`](./02-RegisterPage.html) | ⏳ 等审查 | 镜像 Login + 4 bullet + 4 字段表单 |
| 03 | WelcomeModal | [`03-WelcomeModal.html`](./03-WelcomeModal.html) | ⏳ 等审查 | 480px modal + 3 卡片 + 入场动效 |
| 04 | ApiKeyModal | [`04-ApiKeyModal.html`](./04-ApiKeyModal.html) | ⏳ 等审查 | 520px + Key 输入 + 3 态验证 |
| 05 | EmptyState | [`05-EmptyState.html`](./05-EmptyState.html) | ⏳ 等审查 | SVG 插画 + 3 快捷入口 |
| 06 | MainWorkspace | [`06-MainWorkspace.html`](./06-MainWorkspace.html) | ⏳ 等审查 | 三栏 + 文档列表 + 详情预览 |
| 07 | ChatPanel | [`07-ChatPanel.html`](./07-ChatPanel.html) | ⏳ 等审查 | 消息流 + 工具调用 + auto-resize 输入 |
| 08 | SettingsDrawer | [`08-SettingsDrawer.html`](./08-SettingsDrawer.html) | ⏳ 等审查 | 420px 抽屉 + 5 分组 + 退出 |

---

## 🔍 重点先看这个

**[`FEATURE-COVERAGE.md`](./FEATURE-COVERAGE.md)** — 功能覆盖检查清单

里面列了:
- ✅ v1 8 屏覆盖的所有功能 (~30 项)
- ⚠️ P0 我建议必补的 5 项 (loading 屏 / 工作区 picker / 拖拽反馈 / 确认 modal / Toast)
- 🟡 P1 按需补的 7 项 (搜索结果 / PDF 预览 / 错误页 / 密码找回 / 账号编辑 modal / 统计页 / 看图 UI)
- 🟢 P2 锦上添花 (暗色模式 / Cmd+K / 引导 tour 等)

**先看这个清单决定功能要补到什么程度, 再回头审查 8 屏视觉细节.**

---

## 预览方法

任选一种:

```bash
# 1. Finder 打开整个文件夹, 双击 .html 文件
open "design/UI-Design v1"

# 2. 单文件
open "design/UI-Design v1/06-MainWorkspace.html"

# 3. 全部一起开 (会开 8 个浏览器标签)
open "design/UI-Design v1"/*.html
```

每个 HTML **单文件自包含**, Tailwind CDN + Lucide CDN + 内联样式, 无需 build, 任何浏览器都能开.

---

## 反馈方法 (审查阶段)

按设计文档建议的 2 步走:

### 第 1 步: 功能覆盖审查

打开 `FEATURE-COVERAGE.md`, 一项一项 ✅ 或 ✗:
- ✓ 的: OK
- ✗ 的: 告诉我什么功能没在 v1 屏里出现
- P0/P1 决定要不要补

### 第 2 步: 单屏深度审查 (在覆盖完整后)

按 01 → 08 顺序逐个审, 反馈格式:

```
[01-LoginPage]
✅ 整体方向: OK
❌ 具体改:
  - 大标题字号小一号, 32px → 28px
  - 4 个 chip 间距太挤, gap-3 → gap-4
  - 渐变方向反过来, 从右下→左上
  - 右下"切换错误提示"调试按钮删掉
```

我改完同一个文件, 你刷新浏览器再看.

---

## 满意后的下一步

1. ✅ 功能覆盖完整 + 8 屏视觉过审 →
2. 我把 HTML 转成 React `.tsx`, 落到 `src/frontend/auth/` / `src/frontend/components/` 等对应位置 →
3. 跟 V4 已经写的 `src/frontend/auth/LoginPage.tsx` 风格统一 →
4. commit + 推 GitHub

---

## 设计基础 (来自 UI-DESIGN-SPEC.md)

- **风格**: Apple HIG, 大量留白, 8px 网格
- **图标**: lucide.dev, 严禁 emoji
- **主色**: indigo-500 `#6366f1`, 强调 violet `#8b5cf6`
- **品牌渐变** (仅 Login/Register): `linear-gradient(135deg, #6366f1, #8b5cf6, #a855f7)`
- **字体**: SF Pro / PingFang SC stack
- **圆角**: 卡片 16, 按钮 10-12, 输入框 10, Modal 24
- **缓动**: `cubic-bezier(0.2, 0, 0, 1)` (Apple 标准)
- **动效时长**: 入场 240ms, hover 160ms, modal 280ms, stagger delay 60ms
