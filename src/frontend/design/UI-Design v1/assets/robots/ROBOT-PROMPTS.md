# 机器人生图任务清单

> 9 张图: 3 个机器人 × 3 个状态.
> 风格统一, 主色深海蓝 #1e3a8a, 透明背景, 卡通 minimalist flat 风.

---

## 工具推荐

| 工具 | 优势 | 链接 |
|---|---|---|
| **Midjourney + Niji 6** | 卡通风最强, 风格一致性最好 | [discord.gg/midjourney](https://discord.gg/midjourney) |
| **即梦 (Dreamina)** | 中文友好, 国内免梯子 | [jimeng.jianying.com](https://jimeng.jianying.com) |
| **通义万象 (阿里)** | 国内免费, 卡通效果不错 | [tongyi.aliyun.com/wanxiang](https://tongyi.aliyun.com/wanxiang) |
| **DALL-E 3 (ChatGPT Plus)** | 理解中文 prompt 好 | ChatGPT Plus 内置 |
| **Recraft.ai** | 出 SVG / 矢量, 编辑方便 | [recraft.ai](https://recraft.ai) |

**强烈建议 Midjourney + Niji 6** — 卡通角色一致性最佳。如果用国内工具, 用同一个 seed 保持 3 状态人物一致。

---

## 通用底层 prompt (所有 9 张都加)

```
cute friendly robot character, minimalist flat 2D illustration,
soft rounded shapes, deep navy blue (#1e3a8a) primary color with white/light blue accents,
isolated on transparent background, front 3/4 view,
character design for SaaS app illustration, clean modern style,
no text, no logo
--ar 1:1 --niji 6
```

中文版 (即梦/通义用):

```
可爱友善的卡通机器人角色, 极简扁平 2D 插画风格,
柔和圆润造型, 深海蓝 (#1e3a8a) 主色 + 白色/浅蓝点缀,
纯色背景或透明背景, 半正面 3/4 视角,
SaaS 应用插图风格, 现代简洁, 无文字无 logo
```

---

## 3 个机器人差异化 (各自的"识别标志")

| 机器人 | 标识特征 | 描述 (英文) | 描述 (中文) |
|---|---|---|---|
| **Robot 1** | 戴小耳机, 端咖啡杯 | wearing small headphones, holding a coffee cup | 戴着小耳机, 端着咖啡杯 |
| **Robot 2** | 戴圆眼镜, 桌上一叠纸 | with round glasses, stack of papers on desk | 戴着圆眼镜, 桌上一叠纸 |
| **Robot 3** | 头顶天线, 旁边小盆栽, 圆胖 | with antenna on top, small potted plant beside, slightly chubby | 头顶有天线, 旁边一个小盆栽, 圆胖 |

---

## 3 种状态的姿势描述

### 状态 A · 摸鱼 (idle) — 默认, 散漫不专心

| 机器人 | 姿势 (英文) | 姿势 (中文) |
|---|---|---|
| Robot 1 | leaning back lazily, feet up on desk, sipping coffee, looking sideways | 慵懒地向后靠, 双脚翘在桌上, 喝着咖啡, 眼睛看向一旁 |
| Robot 2 | slumped over desk, head resting on stack of papers, almost dozing off | 趴在桌上, 头枕在一叠纸上, 快睡着了 |
| Robot 3 | spinning on chair, looking at phone, plant slightly tilted | 转椅子上玩手机, 旁边盆栽稍微歪了 |

### 状态 B · 偷看 (peek) — 用户输密码时, 夸张伸脖子

| 机器人 | 姿势 (英文) | 姿势 (中文) |
|---|---|---|
| Robot 1 | dramatically leaning forward, neck stretched extremely to the right, eyes wide and curious, coffee cup tilting | 夸张前倾, 脖子极度向右伸长, 眼睛瞪大好奇, 咖啡杯歪了 |
| Robot 2 | standing up from chair, hands on desk, neck craned to the right, glasses sliding down | 从椅子上站起来, 手撑在桌上, 脖子向右探, 眼镜往下滑 |
| Robot 3 | standing on tiptoes, neck stretched ridiculously long to the right, plant knocked over | 踮起脚尖, 脖子滑稽地向右伸到老长, 盆栽都被碰倒了 |

### 状态 C · 装忙 (smile) — 鼠标在他们身上时, 假装努力 + 看用户

| 机器人 | 姿势 (英文) | 姿势 (中文) |
|---|---|---|
| Robot 1 | awkward forced smile looking directly at camera, frantically typing on laptop, sweat drop | 强装微笑直视镜头, 慌乱地敲键盘, 头上一滴汗 |
| Robot 2 | wide fake smile to camera, holding paper upside-down pretending to read seriously | 假笑面对镜头, 拿着一张纸 (倒着的) 装作很认真在读 |
| Robot 3 | nervous smile waving to camera, antenna sparkles, plant restored straight | 紧张地朝镜头挥手并微笑, 天线闪光, 盆栽恢复直立 |

---

## 完整 prompt 拼装范例

**例: Robot 1, 状态 B 偷看** (Midjourney/Niji)

```
cute friendly robot character wearing small headphones holding a coffee cup,
dramatically leaning forward neck stretched extremely to the right,
eyes wide and curious, coffee cup tilting,
minimalist flat 2D illustration, soft rounded shapes,
deep navy blue (#1e3a8a) primary with white accents,
isolated on transparent background, front 3/4 view,
character design for SaaS app illustration, clean modern
--ar 1:1 --niji 6
```

**例: Robot 3, 状态 C 装忙** (即梦/通义用中文)

```
可爱友善的卡通机器人角色, 头顶有天线, 旁边一个小盆栽, 圆胖,
紧张地朝镜头挥手并微笑, 天线闪光, 盆栽恢复直立,
极简扁平 2D 插画风格, 柔和圆润造型,
深海蓝 (#1e3a8a) 主色 + 白色点缀,
透明背景, 半正面 3/4 视角, SaaS 应用插图风格
```

---

## 一致性保持技巧 (重要!)

**问题**: AI 生图最难的是"同一个角色不同动作", 容易每次画得像不同人.

**3 个方法**:

### 方法 1 · 用 seed (Midjourney 推荐)

```
... 完整 prompt ... --seed 12345 --ar 1:1
```

同一个 Robot 的 3 个状态, 用**相同 seed**, 只改 pose 描述. 这样人物特征保持一致.

3 个不同 robots 用 3 个不同 seed (e.g. 11111, 22222, 33333), 但每个 robot 内部 3 状态 seed 一致.

### 方法 2 · 用 character reference (Midjourney v6+)

先画一张 robot 标准姿势, 然后用它作为 reference:

```
... 新动作 prompt ... --cref [reference图URL] --cw 100
```

### 方法 3 · 即梦 / 通义万象的"角色一致性"功能

国内工具大多有这个功能, UI 里直接选 "保持角色一致" + 上传第一张图.

---

## 命名约定 (生完后)

下载后这样命名, 我直接用:

```
robot-1-idle.png    Robot 1 · 摸鱼
robot-1-peek.png    Robot 1 · 偷看
robot-1-smile.png   Robot 1 · 装忙
robot-2-idle.png
robot-2-peek.png
robot-2-smile.png
robot-3-idle.png
robot-3-peek.png
robot-3-smile.png
```

放到这个目录: `design/UI-Design v1/assets/robots/`

(我会先建好这个目录)

---

## 输出要求

- **格式**: PNG (透明背景) 或 WebP
- **分辨率**: 至少 512×512, 推荐 1024×1024
- **背景**: 透明 (Midjourney 用 `--no background` 不行, 推荐生完用 [remove.bg](https://remove.bg) 或 [removebg](https://www.remove.bg) 抠掉)
- **风格统一性**: 9 张图必须看起来"是同一套"

---

## 我已经在做什么

我在并行做 **占位 prototype** (用 SVG 简笔机器人 + 完整交互逻辑), 你这边生图同时进行.

我做完 prototype 你可以先看交互效果, 确认布局/位置/状态切换都对, 然后我们用你的真图替换占位 SVG 即可.

预估时间:
- 我做 prototype: ~10 分钟
- 你生 9 张图 (含挑选): ~1-2 小时
- 我替换 + 整合 LoginPage: ~20 分钟
