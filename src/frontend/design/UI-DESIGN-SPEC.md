# DocuMate UI 设计规范 v1

> 用于配合 AI 设计工具 (Open Design / Claude Design / Gemini 等) 生成 UI 原型.
> 按"使用顺序"章节里的步骤逐段复制提示词到工具内.

---

## 目录

- [Part 1 — 设计基础](#part-1--设计基础)
  - [1.1 项目背景](#11-项目背景)
  - [1.2 设计目标](#12-设计目标)
  - [1.3 视觉系统](#13-视觉系统)
  - [1.4 动效系统](#14-动效系统)
  - [1.5 技术约束](#15-技术约束)
  - [1.6 禁止事项](#16-禁止事项)
- [Part 2 — 使用指南](#part-2--使用指南)
- [Part 3 — 提示词包](#part-3--提示词包)
  - [Prompt 1 — 项目背景 (粘一次)](#prompt-1--项目背景-粘一次)
  - [Prompt 2 — 一次性出 8 页 v1 大体设计](#prompt-2--一次性出-8-页-v1-大体设计)
  - [Prompt 3 — 细化 LoginPage](#prompt-3--细化-loginpage)
  - [Prompt 4 — 细化 RegisterPage](#prompt-4--细化-registerpage)
  - [Prompt 5 — 细化 WelcomeModal](#prompt-5--细化-welcomemodal)
  - [Prompt 6 — 细化 ApiKeyModal](#prompt-6--细化-apikeymodal)
  - [Prompt 7 — 细化 EmptyState](#prompt-7--细化-emptystate)
  - [Prompt 8 — 细化 MainWorkspace](#prompt-8--细化-mainworkspace)
  - [Prompt 9 — 细化 ChatPanel](#prompt-9--细化-chatpanel)
  - [Prompt 10 — 细化 SettingsDrawer](#prompt-10--细化-settingsdrawer)
- [Part 4 — 验收 Checklist](#part-4--验收-checklist)
- [Part 5 — 字段速查表](#part-5--字段速查表)
- [附录 A — Lucide Icons 速查](#附录-a--lucide-icons-速查)

---

# Part 1 — 设计基础

## 1.1 项目背景

**DocuMate** 是一款本地优先的 AI 文档助手 (Electron 桌面 App).

- **核心功能**: 用户上传 PDF / Word / 扫描件 → AI Agent 帮读取 / 搜索 / 翻译 / 生成出版级 PDF
- **隐私哲学**: 所有文档留本地, 不上云
- **测试期模式**: 用户自带 SiliconFlow API Key (BYOK), 你后端只管账号 + 计费代理
- **目标用户**: 高校学生 / 研究者 / 知识工作者 / 内容创作者

## 1.2 设计目标

按优先级排:

1. **Apple HIG 风格** — 简约 / 大气 / 高级 (参考 macOS Big Sur 之后 + iPadOS 17 语言)
2. **大量留白** — 8px 网格, 视觉权重克制
3. **优雅有趣的动效** — Apple 标准缓动 + spring 弹簧 + magnetic hover
4. **深色模式并行** — slate-950 基底, dark: 前缀
5. **中英文混排美观** — PingFang SC + SF Pro Text 协同

## 1.3 视觉系统

### 主色

- Apple System Blue `#007AFF`
- Tailwind indigo-500 `#6366f1`
- 二者混用作为主品牌色

### 品牌渐变 (仅登录/注册页用)

```css
linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%)
```

### 灰阶系统

| 亮色模式 | 暗色模式 | 用途 |
|---|---|---|
| `#FFFFFF` | `#000000` | 纯白/黑 |
| `#F5F5F7` | `#1C1C1E` | 页面背景 |
| `#E5E5EA` | `#2C2C2E` | 卡片背景 |
| `#D2D2D7` | `#3A3A3C` | 边框/分隔 |
| `#86868B` | `#8E8E93` | 次要文字 |
| `#1D1D1F` | `#FFFFFF` | 主文字 |

### 圆角

| 元素 | 半径 |
|---|---|
| 卡片 | 16px (`rounded-2xl`) |
| 按钮 | 10-12px (`rounded-xl`) |
| 输入框 | 10px (`rounded-lg`) |
| Modal | 24px (`rounded-3xl`) |
| 图标背景 | 完全圆 (`rounded-full`) |

### 阴影

```css
shadow-sm:  0 1px 2px rgba(0,0,0,0.04)
shadow:     0 2px 8px rgba(0,0,0,0.04)
shadow-md:  0 4px 12px rgba(0,0,0,0.06)
shadow-lg:  0 8px 24px rgba(0,0,0,0.08)
shadow-2xl: 0 24px 64px rgba(0,0,0,0.12)
```

### 字体

```
主字体 (拉丁): SF Pro Display (标题) / SF Pro Text (正文)
主字体 (中文): PingFang SC
等宽字体:     SF Mono
```

CSS:

```css
font-family:
  -apple-system, BlinkMacSystemFont,
  'SF Pro Display', 'SF Pro Text',
  'PingFang SC', 'Hiragino Sans GB',
  'Microsoft YaHei', sans-serif;
```

### 图标

- **全部用 lucide-react**: `npm install lucide-react`
- **严禁 emoji** (任何场景, 包括 logo / 标题 / 卡片 / 列表项 / 状态指示)
- 装饰图标尺寸: 16/20/24/32px
- 图标颜色: 跟随文字色或品牌色

## 1.4 动效系统

### 标准缓动

```css
cubic-bezier(0.2, 0.0, 0, 1)   /* Apple 标准, 比 ease 更柔 */
```

### 动效规范

| 场景 | 效果 | 时长 |
|---|---|---|
| 元素入场 | opacity 0→1 + translateY(8 → 0) | 240ms |
| Hover | scale(1.02) + brightness(1.05) | 160ms |
| 按下 | scale(0.97) 弹回 spring | 80ms |
| 切页 | 横向 slide(8%) + fade | 320ms |
| 列表 stagger | 每项 delay 30ms | — |
| Modal 弹出 | scale(0.96 → 1) + opacity | 280ms |
| 抽屉滑入 | translateX(100% → 0) | 320ms |

### 关键互动

- **按钮 hover**: 抬起 `-translate-y-0.5` + 阴影加深
- **输入框 focus**: ring-2 渐显 200ms
- **卡片 hover**: -translate-y-1 + shadow-lg
- **状态点**: 呼吸 (opacity 0.5 ↔ 1, 2s infinite)

## 1.5 技术约束

### 必用

- React 19
- Tailwind CSS 3
- Electron
- TypeScript (.tsx)
- lucide-react (图标)

### 不用

- ❌ shadcn/ui
- ❌ Material UI / MUI
- ❌ Mantine
- ❌ Ant Design
- ❌ Framer Motion (用 Tailwind transition + keyframes 替代)
- ❌ React Router (App 单页布局, 用状态切换)

### 实现优先级

1. Tailwind utility classes (90% 场景)
2. inline style (复杂值: 渐变 / 自定义阴影)
3. CSS modules (极少用)

## 1.6 禁止事项

| 类别 | 禁止 | 理由 |
|---|---|---|
| 图标 | 任何 emoji | 不专业, 跟苹果风冲突 |
| 视觉 | 拟物化 / 重影 / 高反差 | 不符合 macOS Big Sur 之后语言 |
| 颜色 | 强渐变 (除登录页) | 苹果克制 |
| 颜色 | 高饱和色块 | 难看 |
| 边框 | 实心彩色边框 | 用阴影代替 |
| 风格 | 卡通 / 圆胖 / 童趣感 | 跟产品定位不符 |

---

# Part 2 — 使用指南

## 2.1 推荐 AI 设计工具

按推荐顺序:

1. **Open Design** (nexu-io/open-design) — 开源 Claude Design 替代
2. **Claude Design** (官方) — 付费, 但工作流好
3. **v0.dev** (Vercel) — 不错的备选
4. **Bolt.new** — 也行

## 2.2 提示词使用顺序

```
┌─ Prompt 1 (项目背景) ──────────┐
│  粘到 AI 工具的 Brand Context  │
│  或对话开头, 永久 context     │
└────────────────────────────────┘
              ↓
┌─ Prompt 2 (8 页 v1 大体设计) ──┐
│  让 AI 一次性出全部草稿        │
│  审查整体风格统一性            │
└────────────────────────────────┘
              ↓
   v1 满意? 否 → 迭代 Prompt 2
              ↓ 是
┌─ Prompt 3-10 (逐页细化) ───────┐
│  一次一个 prompt, 单独打磨每页 │
│  每个细化输出 → 立刻 export    │
└────────────────────────────────┘
              ↓
   合并到 DocuMate src/frontend/ 对应文件
```

## 2.3 操作建议

- **AI 工具支持文件夹链接的话**, 把 `/Users/qbqb/Desktop/暂时存储/DocuMate` 整个目录链给它 (不是只链 src/frontend/, 工具还需要看 package.json / tailwind.config.js)
- **每次满意立刻 export**, 防止 session 丢失
- **不满意时迭代而非重做**: 给具体反馈 ("阴影太重" / "字号小一号" / "缓动太慢"), 让 AI 改而不是从头来
- **逐页细化前先让 v1 整体风格统一**

## 2.4 注意事项

- 中国大陆用户用 Open Design + Claude CLI 时, 关掉 Claude Desktop App 避免并发 403
- Gemini CLI 需要代理, 而且账号 region 不能是 CN
- 国内最稳: Qwen CLI / DeepSeek CLI / Kimi CLI (用 API Key)

---

# Part 3 — 提示词包

## Prompt 1 — 项目背景 (粘一次)

**用法**: 粘到 AI 工具的 "Brand Context" / "Product Description" 输入框, 或作为对话开头的系统提示. 让 AI 永久记住项目设定.

```
# 项目: DocuMate (Electron 桌面 App)

## 是什么
DocuMate 是本地优先的 AI 文档助手. 用户上传 PDF/Word/扫描件, AI Agent 帮读取/搜索/翻译/生成出版级 PDF. 文档留本地, 隐私优先. 测试阶段用户自带 SiliconFlow API Key.

## 目标用户
高校学生、研究者、知识工作者、内容创作者.

## 设计目标
1. Apple HIG 简约 / 大气 / 高级 (参考 macOS Big Sur 之后 + iPadOS 17)
2. 大量留白, 8px 网格, 视觉权重克制
3. 优雅有趣的动效 (Apple 标准缓动 + spring 弹簧 + magnetic hover)
4. 深色模式并行 (slate-950 基底)
5. 中英文混排美观 (PingFang SC + SF Pro Text 协同)

## 视觉系统
- 主色: Apple System Blue #007AFF / indigo-500 #6366f1
- 品牌渐变 (仅登录注册页用): linear-gradient(135deg, #6366f1, #8b5cf6, #a855f7)
- 灰阶亮: #FFFFFF / #F5F5F7 / #E5E5EA / #D2D2D7 / #86868B / #1D1D1F
- 灰阶暗: #000000 / #1C1C1E / #2C2C2E / #3A3A3C / #8E8E93 / #FFFFFF
- 圆角: 卡片 16px / 按钮 10-12px / 输入框 10px
- 阴影: 0 2px 8px rgba(0,0,0,0.04) (柔和)
- 字体: SF Pro Display / Text + PingFang SC, 等宽 SF Mono

## 图标
- 全部用 lucide-react 线性图标
- 严禁任何 emoji (任何场景, 包括 logo / 标题 / 卡片 / 列表项 / 状态指示等都不许用)
- logo 不用 emoji, 用 SVG 抽象图形 (推荐 lucide FileText + Sparkles 组合, 或自定义 SVG 渐变方块含字母 D)
- 装饰场景需要图标时, 一律 lucide icon + 适当 size + 颜色

## 动效
- 缓动: cubic-bezier(0.2, 0.0, 0, 1)
- 入场: opacity 0→1 + translateY(8 → 0), 240ms
- Hover: scale(1.02) + brightness(1.05), 160ms
- 按下: scale(0.97), 80ms 弹回 spring
- 切页: 横向 slide(8%) + fade, 320ms
- 列表 stagger: 每项 delay 30ms

## 技术栈 (输出代码要兼容)
- React 19 + Tailwind CSS 3 + Electron
- 不用 shadcn / Material UI / Mantine / Ant Design / Framer Motion
- Tailwind utility class 优先, 复杂值用 inline style
- TypeScript .tsx, dark: 前缀做深色模式

## 不要的
- 任何 emoji (这是硬规则, 包括装饰性 / 状态性 / logo 任何场景)
- 拟物化 / 重影 / 高反差
- 强渐变 (除登录注册页品牌区)
- 卡通 / 圆胖 / 童趣感
- 实心彩色边框 (用阴影代替)
- 高饱和度色块
```

---

## Prompt 2 — 一次性出 8 页 v1 大体设计

**用法**: 在 AI 工具新建会话, 让它基于 Prompt 1 的项目背景, 一次性出全部 8 个页面的草稿. 重点是结构与风格统一, 不追求细节完美.

```
基于上面项目背景, 一次性给我 DocuMate 全部 8 个页面的 v1 大体设计.
重点: 布局结构 + 视觉风格统一, 细节后续单独 polish.
全部图标用 lucide-react, 绝对没有任何 emoji.

8 个页面 (每个独立 React functional component, TypeScript .tsx):

1. LoginPage
   左右分栏. 左侧渐变品牌区: SVG logo (FileText + Sparkles 组合, 或抽象渐变方块含字母 D) + 产品名 "DocuMate" + tagline + 大标题 + 4 个 feature chip (每个 chip 含 lucide icon + 文字). 右侧白卡表单: 邮箱 / 密码 / "记住我" 复选框 / "忘记密码" 链接 / 登录按钮 / "立即注册" 链接.

2. RegisterPage
   同登录布局镜像 (左品牌右表单). 左侧文案改 "加入 DocuMate" + 4 行 bullet 列表 (每行 lucide icon + 文字, 不要 emoji). 右侧表单: 邮箱 / 昵称(可选) / 密码 / 确认密码 / 注册按钮.

3. WelcomeModal
   首次登录弹的欢迎公告. 480px modal + 半透明遮罩. 3 张分组卡片, 每张顶部 lucide icon (GraduationCap / AlertTriangle / ShieldCheck) + 标题 + 描述. 底部 2 按钮: "再看一下" 次按钮, "现在去填" 主按钮.

4. ApiKeyModal
   SiliconFlow Key 输入弹窗 520px. 顶部 lucide Key icon (圆形 indigo 背景包裹). 含 password input (右侧 lucide Eye/EyeOff toggle 显隐) + helper text + 验证状态指示 (lucide Loader2 spin / CheckCircle2 / XCircle) + 保存按钮.

5. EmptyState
   主界面空状态 (登录后没文档). 居中布局大留白. 顶部 SVG 插画或 lucide 组合 (FileText + Bot 双图标渐变色). 大字标题 + 副标题段落. 3 个快捷入口卡片 (横排), 每张含 lucide icon (Upload / FolderOpen / MessageSquare) + 标题 + 描述. 底部状态条 (mono 字体 + 绿点 pulse).

6. MainWorkspace
   主界面三栏布局. 顶部 header (56px): SVG logo + 产品名 / 中间面包屑当前文档 / 右侧 lucide Settings + 用户头像 (gradient 圆 + 首字母). 左侧 sidebar (280px): 工作区切换按钮 (含 lucide ChevronsUpDown) + 3 个 tab (用 lucide FileText / Search / MessageSquare 配文字) + tab 内容区. 中间主区根据 tab 显示文档列表/搜索/对话.

7. ChatPanel
   Chat 对话面板. 顶部 header: session 标题 + lucide ChevronDown 切换菜单 + lucide Plus 新建 + lucide Trash2 清空. 中间消息流: 用户消息右侧 (渐变蓝紫气泡 + 圆角 rounded-tr-md). AI 消息左侧 (白卡 + 边框 + 圆角 rounded-tl-md). 工具调用居中卡片 (lucide Wrench icon + 状态指示). 底部 auto-resize 输入框 + 圆形 lucide Send 发送按钮.

8. SettingsDrawer
   从右侧滑入 420px 抽屉. 顶部用户卡: 大头像 (gradient 圆含首字母 monogram) + 邮箱 + 昵称 + 加入天数 + 右上 lucide X 关闭. 5 张分组卡片 (账号 / API Key / 工作区 / 使用统计 / 关于), 每张含 lucide icon + 子项. 底部退出登录按钮 (lucide LogOut icon + 文字, rose 警告色).

要求:
- 8 个独立 .tsx 文件
- 全部 Tailwind utility classes
- 圆角 / 阴影 / 间距 / 字号 / 配色完全一致
- 含基本 hover / focus / 入场动效
- 0 emoji
- v1 重点是骨架 + 风格统一, 细节后续 prompt 再深入
```

---

## Prompt 3 — 细化 LoginPage

**用法**: v1 出来后, 用这段细化 LoginPage. 包含具体的 Tailwind 类、动效参数、状态接口.

```
基于刚才 LoginPage v1, 进一步精细化:

【视觉】
- 左侧渐变品牌区背景: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%)
- 在渐变区上叠加 2 个柔光圆: w-96 h-96 rounded-full bg-white/10 blur-3xl, 分别 absolute -top-20 -right-20 和 -bottom-20 -left-20, 增加层次
- 左侧顶部 logo: 用 SVG 自定义图形 (推荐: 一个 14x14 圆角方块, 内嵌 lucide FileText icon, 配 Sparkles 装饰点) + "DocuMate" 文字 (text-3xl font-bold)
- tagline "懂你文档的 AI 助手" 用 text-indigo-100 text-sm, 紧贴 logo 下
- 中段大标题 "把繁琐文档 / 交给 AI" 4xl 加粗 leading-tight, 分 2 行
- 介绍段 max-w-md, text-indigo-100 text-base leading-relaxed
- 4 个 feature chip (2x2 网格, gap-3, max-w-md):
   每个 chip: bg-white/10 + backdrop-blur-sm + border border-white/20 + rounded-lg + px-3 py-2 + flex items-center gap-2
   含 lucide icon (size-5) + 文字:
   - Brain icon + "Function Calling Agent"
   - Search icon + "向量语义搜索"
   - Eye icon + "Vision OCR"
   - FileText icon + "出版级 PDF"
- 底部小字 "测试阶段 · 大学生开源项目 · © 2026 DocuMate" text-indigo-200/80 text-xs

【右侧表单】
- max-w-md 居中
- 主标题 "欢迎回来" text-3xl font-bold text-slate-800
- 副标题 "登录你的 DocuMate 账号" text-slate-500 text-sm
- 邮箱 input: 标准 label + input, focus 时 ring-2 ring-indigo-500 + border-transparent
- 密码 input: 同上. label 行右侧加 "忘记密码?" 链接 (text-indigo-600 text-xs hover 下划线)
- "记住我" 复选框: 行内, w-4 h-4 + accent-indigo-600 + 后跟 "记住我 (30 天免登录)" text-sm
- 点击"忘记密码" 在密码框下平滑展开淡黄提示框: bg-amber-50 border-amber-200 text-amber-800, 内容 "密码找回功能下个版本支持, 暂时请联系开发者"
- 主按钮 "登录": w-full py-2.5 rounded-lg, background linear-gradient(135deg, #6366f1, #8b5cf6), text-white font-medium shadow-md, hover 抬起 -translate-y-0.5 + shadow-lg
- 错误提示: bg-rose-50 border border-rose-200 text-rose-700 text-sm px-3 py-2 rounded-md
- 底部 "还没账号? 立即注册" 链接居中

【动效】
- 整页入场: 左栏 translateX(-16 → 0) 240ms + 右栏 fade-in delay 100ms
- 输入框 focus: ring 渐显 200ms
- 主按钮 hover: 抬起 + shadow 强化 160ms cubic-bezier(0.2,0,0,1)
- 4 个 feature chip stagger: 每个 delay 60ms
- 错误提示 fade-in + 高度展开 200ms

【状态】
useState: email / password / remember / loading / error / showForgotHint
props: onLogin(email, password, remember): Promise / onSwitchToRegister
含 form submit handler + 前端校验 + AuthError 区分

输出完整 TypeScript .tsx, 0 emoji.
```

---

## Prompt 4 — 细化 RegisterPage

**用法**: 跟 LoginPage 呼应, 但有差异化文案与字段.

```
基于刚才 RegisterPage v1, 进一步精细化:

【视觉】
- 左侧渐变区跟 LoginPage 完全一致 (同样柔光圆 + logo + tagline 一致, 形成对称感)
- 左侧大标题改 "加入 DocuMate / 体验真正懂你的 AI" 4xl 加粗 leading-tight (单引号去掉)
- 左侧介绍段: "注册免费. 测试阶段需要你自带 SiliconFlow API Key 体验 AI 能力 — 不会消耗太多 token, 放心试."
- 左侧 4 行 bullet 列表 (max-w-md, space-y-2):
   每行 flex items-center gap-2, text-indigo-50 text-sm
   - lucide BookOpen icon (size-5) + "文档管理 + RAG 语义搜索"
   - lucide Eye icon + "Vision OCR 识别扫描件"
   - lucide FileText icon + "anthropic 同款出版级 PDF"
   - lucide ShieldCheck icon + "文档本地, API Key Fernet 加密"

【右侧表单】
- max-w-md, 主标题 "创建账号" + 副标题 "几秒钟开始使用"
- 邮箱 input
- 昵称 input (label 后跟 "(可选)" text-xs 灰), placeholder "不填默认用邮箱前缀"
- 密码 input (placeholder "至少 6 位")
- 确认密码 input
- 注册按钮 (跟登录页同款渐变)
- 底部小字 text-slate-400 text-xs: "注册即代表同意'测试期数据收集'规则: 我们保存你的邮箱、密码哈希、API Key 加密密文、调用日志(不存调用内容)"

【交互校验】
- 前端校验: 邮箱格式 / 密码至少 6 位 / 两次密码一致
- 后端 409 重复邮箱 → 错误显示 "这个邮箱已注册, 试试登录?"
- 错误提示同 LoginPage 风格 (rose 系)

【动效】
跟 LoginPage 一致 (复用规范)

【状态】
useState: email / displayName / password / confirmPassword / loading / error
props: onRegister(email, password, displayName?): Promise / onSwitchToLogin

输出完整 TypeScript .tsx, 0 emoji.
```

---

## Prompt 5 — 细化 WelcomeModal

**用法**: 用户首次登录弹的欢迎公告 modal.

```
基于刚才 WelcomeModal v1, 进一步精细化:

【布局】
- 半透明遮罩: bg-black/40 + backdrop-blur-sm, fixed inset-0 z-50, flex items-center justify-center
- Modal: 480px wide, bg-white rounded-3xl shadow-2xl p-8

【内容】(从上到下)
- 顶部图标: 一个 16x16 圆形 bg-gradient (indigo to violet), 内嵌 lucide Sparkles icon (size-8, white)
- 标题: "欢迎使用 DocuMate" text-2xl font-bold text-center text-slate-900
- 副标题: "开始之前, 有 3 件事想告诉你" text-slate-500 text-sm text-center mb-6

- 3 张分组卡片 (space-y-3):

  卡片 1: bg-slate-50 rounded-2xl p-4, flex items-start gap-3
    - 左侧 lucide GraduationCap icon (size-6, indigo-600), 顶部对齐
    - 右侧: 标题 "大学生独立项目" text-base font-semibold + 描述 "我是一名大学生, DocuMate 是我业余时间做的开源项目" text-slate-600 text-sm

  卡片 2: bg-amber-50 rounded-2xl p-4, flex items-start gap-3
    - 左侧 lucide AlertTriangle icon (size-6, amber-600)
    - 右侧: 标题 "测试期需自带 API Key" + 描述 "需要你提供 SiliconFlow API Key 才能用. 测试场景不会消耗太多 token, 请放心试用"

  卡片 3: bg-emerald-50 rounded-2xl p-4, flex items-start gap-3
    - 左侧 lucide ShieldCheck icon (size-6, emerald-600)
    - 右侧: 标题 "我们如何保护你" + 描述 "API Key 用 Fernet AES 加密存储, 文档全程留你本地, 不上传服务器"

- 底部 2 按钮 (flex gap-3 mt-6):
   - 左侧次按钮 "再看一下" (flex-1, border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 rounded-xl py-2.5)
   - 右侧主按钮 "现在去填" (flex-1, gradient indigo-violet text-white shadow-md hover 抬起 rounded-xl py-2.5)
   主按钮右侧加 lucide ArrowRight icon

【动效】
- 遮罩 fade-in 200ms
- Modal 入场: scale(0.96 → 1) + opacity 0→1, 280ms cubic-bezier(0.2,0,0,1)
- 3 张卡片 stagger 滑入: translateY(16 → 0) + fade, 每张 delay 80ms (整体动画时长 ~600ms)
- 关闭: 反向 scale + fade 200ms

【交互】
- ESC 键关闭 (相当于 onLater)
- 点击遮罩关闭 (onLater)
- body scroll lock 当 modal 显示时

【状态】
props: isOpen: boolean / onLater(): void (关闭仅标记 seenWelcome) / onConfigureKey(): void (关闭并打开 ApiKeyModal)

输出完整 TypeScript .tsx, 用 createPortal 挂到 body, 0 emoji.
```

---

## Prompt 6 — 细化 ApiKeyModal

**用法**: SiliconFlow API Key 输入弹窗.

```
基于刚才 ApiKeyModal v1, 进一步精细化:

【布局】
- 遮罩同 WelcomeModal
- Modal: 520px wide, bg-white rounded-3xl shadow-2xl p-8

【内容】
- 顶部图标: 16x16 圆形 bg-indigo-100, 内嵌 lucide Key icon (size-8, indigo-600)
- 标题: "配置 SiliconFlow API Key" text-2xl font-bold text-center
- 副标题: "你的 Key 用 Fernet AES 加密存储, 不出现在任何日志或客户端缓存" text-slate-500 text-sm text-center mb-6

- 输入框区:
   - label "API Key" text-sm font-medium text-slate-700 mb-1.5
   - input wrapper relative
     - input type=password 默认 (按眼睛切 type=text), placeholder "sk-xxxxxxxxxxxxxxxxxxxxxxx", font-mono, 完整 Tailwind 样式
     - 右侧 absolute lucide Eye 或 EyeOff icon button (size-5, slate-400 hover:slate-600), 点击切显隐
   - helper text "格式: 以 sk- 开头" text-slate-400 text-xs mt-1.5

- 外链行: flex items-center gap-1.5 text-indigo-600 text-sm hover 下划线
   - lucide ExternalLink icon (size-4) + "如何获取 SiliconFlow API Key?"
   点击在新标签页打开 https://siliconflow.cn (Electron 调 shell.openExternal)

- 验证状态行 (动态显示):
   - loading: bg-slate-50 rounded-lg px-3 py-2 + lucide Loader2 spin (size-5, indigo-600) + "正在验证 SiliconFlow…" text-slate-700 text-sm
   - success: bg-emerald-50 rounded-lg px-3 py-2 + lucide CheckCircle2 (emerald-600) + "Key 有效, 关联到你的 SiliconFlow 账号"
   - error: bg-rose-50 rounded-lg px-3 py-2 + lucide XCircle (rose-600) + 错误详情 (从后端返回)

- 底部 2 按钮 (flex gap-3 mt-6):
   - "取消" (flex-1, border bg-white text-slate-700 rounded-xl)
   - "保存并验证" (flex-1, gradient indigo-violet, loading 时换 lucide Loader2 spin + 文字 "验证中…", disabled 时 opacity-50)

【交互】
- input 空 / 不以 sk- 开头 → 主按钮 disabled
- 主按钮点击 → setLoading true → 调 onSubmit(apiKey) → 成功 cross-fade 状态行 → 0.5s 后自动关闭 + onSuccess(last4)
- 失败 → 输入框 ring-2 ring-rose-300 + 错误状态行展示

【动效】
- 弹出: scale + fade 280ms
- 眼睛 icon 切换: rotate(180deg) 200ms
- 验证状态切换: cross-fade 200ms
- 成功 CheckCircle 入场: scale(0 → 1.2 → 1) 弹跳 spring 400ms

【状态】
useState: apiKey / showKey / verifyState ('idle'|'loading'|'success'|'error') / errorMsg
props: isOpen / onClose / onSubmit(apiKey): Promise<{ok:boolean; last4?:string; error?:string}> / onSuccess(last4)

输出完整 TypeScript .tsx, 用 createPortal, 0 emoji.
```

---

## Prompt 7 — 细化 EmptyState

**用法**: 主界面空状态 (登录后没文档).

```
基于刚才 EmptyState v1, 进一步精细化:

【布局】
- flex-1 flex flex-col items-center justify-center 居中, 大量留白 p-24
- 内部 stack max-w-2xl items-center text-center space-y-6

【视觉】(从上到下)
- 顶部抽象插画: SVG 自定义, 80x80 size
  - 一个圆角矩形 (像 PDF 文档) 渐变填充 indigo-violet, 内含几行文字线 (slate-300)
  - 旁边偏右上小一点的圆形 (像 AI 节点) 同渐变填充, 内含 lucide Sparkles icon
  - 整体浮动姿态 (有 drop-shadow)
- 大标题 "Hello, DocuMate" text-5xl font-bold tracking-tight (-0.02em) text-slate-900
- 副标题段落: "上传 PDF / Word, 用自然语言指挥 AI 读取、搜索、翻译你的文档. 数据全程留本地." text-slate-500 text-base max-w-xl leading-relaxed

- 3 个快捷入口卡片 (flex gap-4 mt-6):
   每个卡片: bg-white rounded-2xl border border-slate-200 shadow-sm p-5 w-56 cursor-pointer
   内部: 顶部 lucide icon (size-7, indigo-600), 标题 + 描述
   - lucide Upload + "上传文档" + "拖入或点击选择 PDF / Word / 图片"
   - lucide FolderOpen + "选择工作区" + "切换到其他文件夹做知识库"
   - lucide MessageSquare + "直接对话" + "跳过文档, 用 AI 聊聊"

- 底部状态条 (固定在页面底部, 距底 24px):
   - 一行小字 mono 字体, flex items-center gap-2
   - 绿色圆点 (w-2 h-2 bg-emerald-500 rounded-full, animate-pulse)
   - 文字 "Phase 2 — Function Calling Agent" text-slate-400 text-xs

【交互】
- 整个 EmptyState 区域接收拖拽 (drag-enter / drag-leave / drop)
- 拖拽进入时: 整页外边显示 border-4 border-indigo-500 + ring-8 ring-indigo-200/50 + animate-pulse
- 3 个快捷入口卡片点击触发对应 callback

【动效】
- 整页 stagger 入场: 插画 → 标题 → 副标题 → 3 卡片 → 状态条, 每个 delay 100ms
- 3 卡片 hover: -translate-y-1 + shadow-lg + border-indigo-200, 200ms cubic-bezier(0.2,0,0,1)
- 绿点呼吸: opacity 0.5 ↔ 1, 2s infinite
- 拖拽进入: border 出现 + ring pulse 200ms

【深色模式 (dark: 前缀)】
- bg-slate-900 主色
- 卡片 bg-slate-800 + border-slate-700, hover border-indigo-500/50
- 标题 slate-100, 副标题 slate-400

【状态】
props: onUpload(): void / onSelectWorkspace(): void / onOpenChat(): void / isDragging?: boolean

输出完整 TypeScript .tsx, 0 emoji.
```

---

## Prompt 8 — 细化 MainWorkspace

**用法**: 主界面三栏布局.

```
基于刚才 MainWorkspace v1, 进一步精细化:

【整体】
h-screen flex flex-col bg-slate-50 dark:bg-slate-950

【顶部 header】(高 56px, fixed top, bg-white/80 backdrop-blur-md border-b border-slate-200)
- 左侧: 14x14 SVG logo (gradient 方块含 lucide FileText) + "DocuMate" 文字 font-semibold
- 中间面包屑: 工作区名 + lucide ChevronRight icon + 当前文档名 (没选时显示 "未选择文档" slate-400)
- 右侧操作组 (flex items-center gap-2):
   - lucide Settings icon button (size-5, hover bg-slate-100 rounded-lg)
   - 用户头像按钮 (w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 含首字母 monogram, white text-sm font-medium)
   - 头像点击打开 SettingsDrawer

【主体】flex flex-1 overflow-hidden (header 下方)

【左侧 sidebar】(width 280px, bg-slate-50 dark:bg-slate-900 border-r border-slate-200)

  - 顶部工作区切换 (p-4):
     button 整宽, flex items-center justify-between, hover bg-slate-100 rounded-lg px-3 py-2
     - 左侧 flex items-center gap-2: lucide Folder icon + 当前工作区名 truncate
     - 右侧 lucide ChevronsUpDown icon (size-4 slate-400)
     点击展开 recent workspaces dropdown

  - 3 个 tab 切换 (px-4, 横排 flex gap-1, bg-slate-200/50 rounded-lg p-1):
     每个 tab: flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium
     - active: bg-white shadow-sm text-indigo-600 (dark: bg-slate-800)
     - inactive: text-slate-500 hover:text-slate-700
     - tab 1: lucide FileText icon + "文档"
     - tab 2: lucide Search icon + "搜索"
     - tab 3: lucide MessageSquare icon + "对话"

  - tab 内容区 (flex-1 overflow-y-auto px-4 pb-4 pt-2 space-y-1):
     "文档" tab: 文档列表项
        每项 flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
        hover bg-slate-100, selected bg-white shadow-sm ring-1 ring-indigo-500
        含 lucide FileText icon (size-4 slate-400) + 文件名 + 字数 slate-400 xs

     "搜索" tab: 大输入框 + 结果列表
     "对话" tab: session 历史列表 (跟文档列表风格统一)

  - 底部固定上传按钮 (mx-4 mb-4):
     w-full py-2.5 rounded-xl gradient indigo-violet text-white shadow-md
     flex items-center justify-center gap-2
     lucide Upload icon + "上传文档"
     hover 抬起 + shadow-lg

【中间主区】(flex-1 bg-white dark:bg-slate-950 overflow-hidden)
- 没选文档时: 显示 EmptyState 组件
- 选了文档时: 文档预览
   - header: 文件名 + 元数据 (字数 / 大小 / 上传时间) + lucide Eye / Trash2 操作按钮
   - 主体 overflow-y-auto, pre 标签显示文本

【交互】
- sidebar 工作区下拉切换: 平滑动画, 选中刷新主区
- 3 个 tab 切换: 用 opacity + absolute 切, 不用 display:none (保持滚动位置)
- 文档列表项 click → 主区显示该文档预览
- 拖拽文件到主区任意位置: 整页 ring 高亮

【动效】
- 工作区 dropdown: scale(0.95 → 1) + fade 200ms
- tab 切换: active 状态平滑迁移 + 内容 cross-fade 200ms
- 文档列表 stagger 入场: 每项 delay 30ms
- header 用户头像 hover: rotate 5deg + scale 1.05, 200ms

【深色模式】
全套 dark: 前缀 (bg-slate-950 / sidebar bg-slate-900 / header bg-slate-900/80)

【状态】
useState: activeTab / selectedDocId / showWorkspaceMenu / showSettings
props: workspace / documents / onSelectDoc / onUpload / onSwitchWorkspace / onOpenSettings

输出完整 TypeScript .tsx, 0 emoji.
```

---

## Prompt 9 — 细化 ChatPanel

**用法**: Chat 对话面板 (产品核心, 重点打磨).

```
基于刚才 ChatPanel v1, 进一步精细化 (产品核心, 重点打磨):

【整体】flex flex-col h-full bg-white dark:bg-slate-950

【顶部 header】(高 56px, border-b border-slate-200, px-6, flex items-center justify-between)
- 左侧 button: 当前 session 标题 + lucide ChevronDown icon (size-4)
- 点击展开 session 切换菜单: 历史 sessions 列表, 每行含标题 + 最后时间 + lucide Trash2 删除按钮
- 右侧操作组 (flex gap-2):
   - lucide Plus icon button "新建对话" (size-9 rounded-lg hover:bg-slate-100)
   - lucide Trash2 icon button "清空"
   - lucide Settings icon button "Chat 设置"

【中间消息流】(flex-1 overflow-y-auto px-6 py-6 space-y-4)

  用户消息 (self-end ml-12 max-w-[70%]):
   - rounded-2xl rounded-tr-md (右上小圆角形成气泡尖)
   - background linear-gradient(135deg, #6366f1, #8b5cf6)
   - text-white px-4 py-3 shadow-md
   - 底部右对齐时间戳 text-indigo-200/80 text-xs (formatRelativeTime)

  AI 消息 (self-start mr-12 max-w-[70%]):
   - rounded-2xl rounded-tl-md (左上小圆角)
   - bg-white border border-slate-200 dark:bg-slate-800 dark:border-slate-700
   - px-4 py-3 shadow-sm
   - markdown 渲染 (用 react-markdown), 标题/列表/代码块/引用都美化
   - 引用标记 [来源 1] 渲染成 chip: inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-md text-xs cursor-pointer hover bg-indigo-100
     chip 内 lucide FileText icon size-3 + "来源 1"
     点击跳转源文档
   - 底部左对齐时间戳

  工具调用块 (mx-auto max-w-[80%] my-2):
   - bg-slate-50 dark:bg-slate-800/50 border border-slate-200 rounded-xl px-4 py-3
   - 顶部行 flex items-center justify-between:
     - 左侧 flex gap-2: lucide Wrench icon (size-4 slate-500) + 工具名 "kb_read_file" font-mono text-sm
     - 右侧状态指示器:
        pending: lucide Loader2 spin (size-4 amber-500) + "等待用户授权" text-amber-700 text-xs
        running: lucide Loader2 spin (indigo-500) + "执行中…"
        success: lucide CheckCircle2 (emerald-500) + "完成 (12.3s)"
        error: lucide XCircle (rose-500) + "失败"
   - 参数行 (可折叠): "查看参数" 按钮展开 JSON 代码块 (font-mono text-xs bg-slate-100 dark:bg-slate-900 rounded-md p-2 mt-2)

【底部 input 区】(border-t border-slate-200 p-4)
- container max-w-3xl mx-auto:
  - 输入框 wrapper: bg-slate-50 dark:bg-slate-900 rounded-2xl p-3 ring-1 ring-slate-200 focus-within:ring-2 focus-within:ring-indigo-500 transition
    - textarea: bg-transparent w-full resize-none outline-none border-none max-h-40 placeholder "输入消息… (Cmd+Enter 发送)"
  - 下方行 flex justify-between items-center mt-2:
    - 左侧 helper: "Cmd+Enter 发送" + 字数 slate-400 text-xs
    - 右侧圆形发送 button: w-10 h-10 rounded-full gradient indigo-violet shadow-md, lucide Send icon (size-5 white)
      disabled 时 opacity-50 + cursor-not-allowed

【动效】(核心)
- 新消息入场: scale(0.96 → 1) + opacity + slide-up 8px, 200ms cubic-bezier(0.2,0,0,1)
- AI 文字流式渐现: 每 chunk fade-in 30ms (打字机效果)
- 工具调用卡片状态切换: cross-fade + icon 旋转
- 新消息自动 smooth scroll 到底
- 发送按钮 click: scale(0.9 → 1.05 → 1) 弹回 spring 80+60ms
- session 菜单: scale(0.95 → 1) + fade 200ms
- 引用 chip hover: scale 1.05 + bg 加深 150ms

【深色模式】
- 整体 bg-slate-950, header bg-slate-900
- AI 消息 bg-slate-800 border-slate-700, 用户消息保留渐变
- 工具卡片 bg-slate-800/50

【状态】
useState: input / messages / loading / pendingTool / sessionId / showSessionMenu
props: onSend / onCancel / onClear / onApprove / onDeny / sessions / onSwitchSession / onNewSession

输出完整 TypeScript .tsx (含 react-markdown 集成), 0 emoji.
```

---

## Prompt 10 — 细化 SettingsDrawer

**用法**: 用户设置抽屉, 含账号管理、API Key、工作区、使用统计、退出登录.

```
基于刚才 SettingsDrawer v1, 进一步精细化:

【布局】
- 右侧滑入抽屉, fixed right-0 top-0, w-[420px] h-screen
- bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 shadow-2xl
- 左侧半透明遮罩 fixed inset-0 bg-black/30 backdrop-blur-sm (点击关闭)
- 内部 overflow-y-auto p-6 space-y-6

【顶部用户卡】(flex items-start gap-4 pb-4 border-b border-slate-200)
- 大头像 w-16 h-16 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500
  内嵌 monogram (用户名首字母 text-2xl text-white font-medium)
- 右侧 stack:
  - 邮箱 text-slate-900 font-medium
  - 昵称 text-slate-500 text-sm
  - 加入天数 text-slate-400 text-xs
- 右上角 lucide X icon button (absolute top-6 right-6, hover bg-slate-100 rounded-lg)

【卡片 1 账号】
- 分组标题: text-slate-500 text-xs font-semibold uppercase tracking-wide mb-2 "账号"
- 卡片 bg-slate-50 dark:bg-slate-800/50 rounded-xl divide-y divide-slate-200:
  3 行, 每行 flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-slate-100
  - lucide Mail icon + "修改邮箱" + 右侧 lucide ChevronRight (slate-400)
  - lucide User icon + "修改昵称" + ChevronRight
  - lucide Lock icon + "修改密码" + ChevronRight
- 点击某行 → 该行下方平滑展开内联输入框 + 保存按钮 (其他行自动收起)

【卡片 2 API Key】
- 标题 "API Key"
- 卡片内容:
  - 当前 Key 显示 (font-mono): "sk-...wxyz"
  - 右侧 status badge: lucide CheckCircle2 emerald + "有效 · 上次验证 5min 前"
  - 2 按钮 (flex gap-2):
    - "更换 Key" (lucide RefreshCw icon, border bg-white text-slate-700)
    - "删除" (lucide Trash2 icon, border-rose-200 bg-rose-50 text-rose-600)

【卡片 3 工作区】
- 标题 "工作区"
- 当前路径行: lucide FolderOpen icon + 路径 font-mono text-xs slate-500 truncate
- 2 按钮: "切换工作区" (lucide ArrowRightLeft) + "Finder 打开" (lucide ExternalLink)

【卡片 4 使用统计】
- 标题 "使用统计" + 右上 "详情" 链接 (text-indigo-600 text-xs hover 下划线 + lucide ArrowRight)
- 3 个数字 (flex justify-around py-3):
  每个 stat: text-center
  - 数字 text-2xl font-bold text-slate-900
  - 标签 text-slate-500 text-xs (今日/本周/本月 · 调用次数)
- 下方 7 天柱状图 (flex items-end gap-1 h-16):
  每柱 flex-1 bg-gradient-to-t from-indigo-500 to-violet-500 rounded-t-md
  高度按相对值 (style height)

【卡片 5 关于】
- 标题 "关于"
- 3 行 divide-y:
  - lucide Globe icon + "项目主页" + ChevronRight → shell.openExternal
  - lucide FileText icon + "隐私政策" + ChevronRight → 弹 modal
  - lucide MessageCircle icon + "反馈" + ChevronRight → mailto
- 底部小字 text-slate-400 text-xs text-center: "DocuMate v0.1.0 · 测试阶段"

【底部退出按钮】
- 整宽 py-3 rounded-xl bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900
- hover bg-rose-100, click 弹二次确认 modal
- flex items-center justify-center gap-2: lucide LogOut icon + "退出登录"

【交互】
- 卡片标题项 click 内联展开 (其他自动收起)
- 退出登录: 弹二次确认 modal "确定退出? 你的本地数据保留, 重新登录即可恢复"

【动效】
- 抽屉滑入: translateX(100% → 0) 320ms cubic-bezier(0.2,0,0,1)
- 遮罩 fade-in 同步
- 各卡片 stagger 入场: delay 80ms each
- 数字 stats 跳动入场: 从 0 计数到目标 600ms easing-out
- 7 天柱状图: 柱子顺序长出 (height 0 → 实际), 每柱 delay 50ms
- 退出按钮 hover: 微微震动 (translateX -1 / 0 / 1 keyframe pulse)

【状态】
useState: isOpen / activeEdit ('email'|'nickname'|'password'|null) / showLogoutConfirm
props: user / onClose / onUpdateField(field, value) / onChangeApiKey / onDeleteApiKey / onSwitchWorkspace / onLogout / usageStats

输出完整 TypeScript .tsx, 用 createPortal 挂 body, 0 emoji.
```

---

# Part 4 — 验收 Checklist

每个页面交付时逐项检查 (任何一项失败必须打回重做):

## 视觉

- [ ] 0 emoji (任何场景)
- [ ] 所有图标用 lucide-react
- [ ] 圆角符合规范 (卡片 16px / 按钮 10-12px / 输入框 10px / Modal 24px)
- [ ] 阴影柔和 (不超过 shadow-2xl, 没有刺眼黑边)
- [ ] 字体 SF Pro + PingFang SC
- [ ] 主色 indigo-500 / 渐变 indigo-violet-purple (除登录页外不强用渐变)
- [ ] 灰阶用 slate 系列 (亮色 / 深色都对应规范)
- [ ] 间距 8px 网格 (gap-2 / 4 / 6 / 8 等)

## 交互

- [ ] hover 反馈 (按钮抬起 / 卡片抬起 / 链接下划线)
- [ ] focus 反馈 (输入框 ring 渐显)
- [ ] disabled 状态 (opacity-50 + cursor-not-allowed)
- [ ] 错误提示 (rose 系, 不是红色块)
- [ ] 加载状态 (lucide Loader2 spin)

## 动效

- [ ] 入场动画 (fade + slide-up)
- [ ] hover 动画 (scale + shadow, cubic-bezier 缓动)
- [ ] 列表 stagger (每项 delay 30-80ms)
- [ ] Modal / 抽屉的入场/退场动画
- [ ] 关键互动有 spring 弹簧效果

## 技术

- [ ] TypeScript .tsx
- [ ] Tailwind utility classes 优先
- [ ] 无 shadcn / MUI / Mantine / Framer Motion 依赖
- [ ] 深色模式支持 (dark: 前缀)
- [ ] 状态管理 props 接口清晰
- [ ] React 19 兼容

## 代码质量

- [ ] 完整 React functional component
- [ ] useState / useEffect / useCallback 用得当
- [ ] event handler 命名 (onXxx / handleXxx)
- [ ] 无 magic number (复杂值定义为常量)
- [ ] 注释精简但关键 (复杂逻辑必注释)

---

# Part 5 — 字段速查表

## Tailwind Color Tokens

```
背景:
  bg-white                  亮色页面
  bg-slate-50               次级背景
  bg-slate-900              深色页面
  bg-slate-800              深色卡片
  bg-indigo-50              品牌色淡化
  bg-rose-50                警告/错误淡化

文字:
  text-slate-900            主要 (亮)
  text-slate-500            次要
  text-slate-400            辅助/占位
  text-indigo-600           主品牌
  text-rose-600             警告/错误
  text-emerald-600          成功

边框:
  border-slate-200          标准 (亮)
  border-slate-700          标准 (暗)
  border-indigo-500         focus / 选中
```

## Tailwind Spacing Tokens

```
gap-1 (4px)   gap-2 (8px)   gap-3 (12px)
gap-4 (16px)  gap-6 (24px)  gap-8 (32px)

p-2  (8px padding)    px-4 (16px horizontal)
p-4  (16px)           py-2 (8px vertical)
p-6  (24px)
p-8  (32px)
```

## Tailwind Radius Tokens

```
rounded-md       6px      标识 / 小图标背景
rounded-lg       8px      输入框
rounded-xl       12px     按钮 / 小卡片
rounded-2xl      16px     标准卡片
rounded-3xl      24px     Modal / 大型卡片
rounded-full     圆       头像 / 状态点
```

## Tailwind Shadow Tokens

```
shadow-sm        卡片浮起 (微)
shadow           卡片浮起 (标准)
shadow-md        按钮浮起 / hover
shadow-lg        按钮 hover 增强
shadow-xl        弹窗
shadow-2xl       Drawer / Modal
```

## Animation Tokens

```css
/* 通用缓动 */
.ease-apple { transition-timing-function: cubic-bezier(0.2, 0.0, 0, 1); }

/* 入场 */
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.animate-fade-in-up { animation: fade-in-up 240ms cubic-bezier(0.2, 0, 0, 1); }

/* 缩放入场 (Modal) */
@keyframes scale-in {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}
.animate-scale-in { animation: scale-in 280ms cubic-bezier(0.2, 0, 0, 1); }

/* 弹簧反馈 (按钮按下) */
@keyframes spring-tap {
  0%   { transform: scale(1); }
  40%  { transform: scale(0.97); }
  100% { transform: scale(1); }
}
.animate-spring-tap { animation: spring-tap 200ms cubic-bezier(0.4, 0, 0.2, 1); }

/* 抽屉滑入 (右侧) */
@keyframes slide-in-right {
  from { transform: translateX(100%); }
  to   { transform: translateX(0); }
}
.animate-slide-in-right { animation: slide-in-right 320ms cubic-bezier(0.2, 0, 0, 1); }

/* 呼吸 (状态点) */
@keyframes breathe {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.5; }
}
.animate-breathe { animation: breathe 2s ease-in-out infinite; }
```

---

# 附录 A — Lucide Icons 速查

## 装

```bash
npm install lucide-react
```

## 用

```tsx
import { FileText, Search, Settings, Upload, Folder } from 'lucide-react'

<FileText className="size-5 text-indigo-600" />
<Search size={20} strokeWidth={1.5} />
```

## DocuMate 用到的图标清单

| Icon | 用在哪 |
|---|---|
| `FileText` | 文档 / logo / 列表项 |
| `Folder` / `FolderOpen` | 工作区 |
| `Search` | 搜索 tab |
| `MessageSquare` | Chat tab / 对话 |
| `Settings` | 设置入口 |
| `User` | 用户头像 / 账号设置 |
| `Mail` | 邮箱字段 |
| `Lock` | 密码字段 |
| `Key` | API Key |
| `Eye` / `EyeOff` | 密码显隐 |
| `Upload` | 上传按钮 |
| `Send` | 发送按钮 |
| `Plus` | 新建对话 |
| `Trash2` | 清空 / 删除 |
| `Wrench` | 工具调用 |
| `Loader2` | 加载 (spin) |
| `CheckCircle2` | 成功状态 |
| `XCircle` / `X` | 错误 / 关闭 |
| `AlertTriangle` | 警告 |
| `ShieldCheck` | 安全/保护 |
| `GraduationCap` | 学生 / 教育 |
| `Sparkles` | AI 装饰 |
| `LogOut` | 退出登录 |
| `ChevronRight` / `ChevronDown` / `ChevronsUpDown` | 导航箭头 / 折叠 |
| `ArrowRight` / `ArrowRightLeft` | 行动 / 切换 |
| `ExternalLink` | 外链 |
| `Globe` | 网站 / 项目主页 |
| `MessageCircle` | 反馈 |
| `RefreshCw` | 刷新 / 更换 |
| `BookOpen` | 文档/知识 |
| `Brain` | AI / 推理 |
| `Bot` | AI 助手 |

完整图标库: https://lucide.dev/icons/

---

**文档版本**: v1.0
**创建日期**: 2026-05-14
**适用项目**: DocuMate (Electron AI 文档助手)
**维护者**: 项目作者
