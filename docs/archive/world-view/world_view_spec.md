# 生活世界 · 可视化施工图（舞台 + 演员 / 写实的家 + 风格化的她）

> 给 Codex 的施工说明。**范围仅限"生活世界"这一个可视化组件**；控制台其余排版/功能由用户和 Codex 另行商定。
> 概念参考：`world_view_follow.html`（镜头跟随单间版，**这是最终形态**）；`world_view_motion.html`（早期会动占位，仅留作动效参考）。
> 核心转变：**不是每次生成新画，而是一个固定舞台 + 一个会动的她；镜头跟着她、一次看一个房间，不再是上帝视角剖面图。**

---

## 0. 定调

- 形态：**2D 游戏场景 + 跟随镜头**。家是一条横向连起来的房间带；视口**一次只看一个房间**，看得大、看得近，像和她在同一间屋里。她走到哪、镜头平滑移到哪（"追随"的那个瞬间是灵魂）。邻屋在画面边缘虚虚露一点保持"家是连着的"，**右上角小地图管纵览**。参考《Florence》《Spiritfarer》横版生活游戏——**舞台画死，演员在上面活动，镜头跟人**。
- **为什么不用剖面图**：上帝视角切开四房间，把"看图纸"和"看她生活"焊在一起 → 冷、像房产中介图、她缩成小人、写实化更像解剖图。跟随单间则亲密、她够大、单间写实就是一张正常室内画。
- 美术分工（关键决策，已定）：
  - **场景/家 = 写实**（固定不动 → 没有恐怖谷，要电影级质感）
  - **她 + 可互动道具 = 风格化**（要动 → 照片级会瘆人且无法动画）
  - 这是 2D 游戏成熟做法：写实背景 + 风格化角色。
- 富度原则：**画面不吃配置，所以往富里堆**，但按"可累加层"组织——核心先跑通，氛围细节无限往上叠，随时能停在完整状态。
- 反廉价铁律：颜色/间距/圆角/字号全部取自 §6 token 表；不用默认控件；不用 emoji 当图标；不用 AI 紫。

---

## 1. 渲染架构：舞台 + 演员（分层）

```
镜头   跟随层          一条横向房间带(.world)，靠 translateX 把她居中；视口 overflow 裁切     ← 纯代码
L0  写实房间底图    每个房间一张写实室内渲染图(正常单间，非剖面)，并排成带，几何固定    ← 美术(写实)
L1  氛围层(代码)    时段色温、天气、灯光池、窗外天空/城市灯、雨丝、光尘、视口暗角        ← 纯代码，无需美术
L2  道具精灵        固定家具上的"会变的东西"：水壶状态、植物状态、灯开关…              ← 美术(风格化小图) + 数据选帧
L3  动态道具        她买的/扔的/新增的物件，运行时按数据摆放                          ← 美术(风格化) + 数据生成
L4  角色 Neno       风格化精灵，能寻路移动、换动作、随心情变姿态、可携带物             ← 美术(风格化) + 数据驱动
L5  特效            蒸汽、炉火、翻书、浇水、她的呼吸光环、互动高亮                    ← 纯代码
L6  界面层          右上小地图(纵览/高亮当前房间) + 注脚(动作/独白/心情/精力/钱/计划/长卷) ← DOM
```
- **每张写实底图是一张"正常的室内画"**，不是切开墙的剖面——这正是写实化得以成立的关键。
- 非当前房间盖一层 `.dim` 压暗；当前房间 `.active` 透出暖光池。

- **写实只在 L0**（不动的舞台）。**风格化在 L2/L3/L4**（会动的一切）。
- L1/L5 是纯代码生成的氛围与特效——**富度的大头在这里，且零美术成本**。
- **降级**：任意精灵/底图缺失 → 回退几何画法（见 motion.html），永不开天窗。

---

## 2. 四层动态：什么固定、什么会变（对应后端字段）

| 层 | 内容 | 变不变 | 数据来源 |
|---|---|---|---|
| 骨架 | 房间结构、墙、大件内置家具(床/灶台/沙发/书架) | **画死不变** | `virtual_world.json` 房间定义 |
| 状态 | 同一物件换样子：水壶 冷/温/沸、植物 鲜/缺水/枯、灯 开/关 | 变样子 | `rooms[].objects[].state` |
| 增减 | 她买来的新物件出现、坏的消失 | 增/减 | `dyn_objects` / `removed` / `gone` |
| 角色 | 她的位置、动作、朝向、心情姿态、手上拿的东西 | 全自由 | `location` / `last.action` / `mood*` |

**固定的只有骨架**——固定才有"这是她的家"的辨识感。其余都在动。

---

## 3. 跟随镜头 + 坐标与寻路（让"她能走/找/用 + 镜头跟人"成立）

**家是一条横向房间带**（房间并排），用一份**静态坐标表**（前端常量，按底图量出，不进后端）：

```js
const ROOM_W = 560, VW = 760;            // 单间宽 / 视口宽（按实际定）
const ORDER  = ['bedroom','living_room','kitchen','balcony'];  // 房间在带子里的左右顺序
const WORLD_W = ROOM_W * ORDER.length;

const SCENE = {
  // 物件：房间序号 + 房间内 x(像素) + 她使用时站立的房间内 x
  objects: {
    bed:    { roomIdx:0, x:120, use_x:180 },
    sofa:   { roomIdx:1, x:300, use_x:340 },
    shelf:  { roomIdx:1, x:70,  use_x:110 },
    kettle: { roomIdx:2, x:140, use_x:150 },
    plant:  { roomIdx:3, x:480, use_x:430 },
    // 动态物件运行时按"房间空位网格"分配房内 x
  },
};

// 她在“整个家”里的绝对坐标
function worldX(roomIdx, x){ return roomIdx*ROOM_W + x; }
// 镜头：把她放视口正中，夹住别露出带子两端
function cameraX(wx){ return Math.max(-(WORLD_W-VW), Math.min(0, -(wx - VW/2))); }
```

- **寻路（横向）**：她当前 `worldX` → 目标物件 `use_x` 的 `worldX`。CSS `transition: left 1.6s` + walk 动画。跨房间就是沿带子横走，自然穿过中间的房间。
- **镜头跟随**：每次她移动，`world.style.transform = translateX(cameraX(目标))`，同样 1.6s 缓动 → 镜头平滑追上去。两端夹紧，不露黑边。
- **用东西**：走到 `use_x` → 朝向物件 → 播动作动画 + 触发物件状态/特效。
- **当前房间**：`location` 决定哪个 `.room` 加 `.active`（透暖光、其余压暗）+ 小地图对应格高亮。
- **新物件落位**：每房间留"空位网格"，`dyn_objects` 按序填房内 x，满了叠到架上。
- （可选纵向/多层：若日后房间分上下层，带子可换成"楼层切换"或加楼梯过场，本期先做单条横带。）

---

## 4. 角色 Neno（风格化，可动）

做法二选一（推荐 A，资源小、表情活、好被数据驱动）：
- **A 纸偶骨架(puppet rig)**：身体拆成 头/发/躯干/手臂/腿 几块，用 transform 拼。换姿势=改关节角度，心情=改姿态，不用一张张帧图。SVG 或分层 PNG 都行。
- **B 序列帧 sprite sheet**：每个动作一条帧序列。最经典，但图多、改动作要重画。

**动画集（先做核心 4 个，其余慢慢加）：**
```
核心: walk / idle(呼吸) / sit-read / sleep
扩展: cook 烧饭 / water 浇花 / eat / stretch 伸懒腰 / look-window 望窗外 /
      slump 低落 / cheer 开心蹦 / cry / dance / carry 拿着杯子走
```
- **朝向**：左右走翻转精灵。
- **心情驱动姿态**：`mood_valence` 低→含胸、动作慢、光环偏冷；高→挺拔、轻快、光环暖。
- **携带物**：动作产生的物品(泡好的茶)可挂在手上一起移动。
- **微行为**：idle 时随机插入小动作（看一眼窗外、整理头发、发呆），**让她闲着也像活的**。

---

## 5. 丰富度目录（往富里堆，几乎全是纯代码 L1/L5，零美术）

按"可累加层"组织。核心跑通后，每加一条世界就更活一点：

**时间与光**
- 全天候色温循环：黎明/早晨/正午/午后/黄昏/夜，连续过渡，不是 4 张切图
- 太阳/月亮在窗外缓慢移动；光斑随之在地板上移动
- 黄昏自动点灯、清晨灭灯；灯光池、烛光轻闪
- 光尘：光束里浮动的尘埃微粒

**天气**（接 `weather` 事件）
- 雨：窗上雨珠下淌 + 玻璃水痕 + 远处城市朦胧；可选雨声
- 晴/阴/雪：天空与窗光随之变；雪花飘落
- 天气影响她：下雨她更可能窝沙发、晴天去阳台

**窗外世界**（暗示"还有更大的世界"）
- 远处楼宇窗户入夜逐个亮起/熄灭
- 偶尔街灯、车灯划过
- 季节：窗外树木换色（春绿/秋黄/冬枯）

**居家活物（让屋子自己呼吸）**
- 窗帘微摆、植物叶子轻晃、挂钟摆动、电视雪花微光
- 一只**会自己乱逛的猫**（独立小 AI，跟她无关地走动、趴下、追光）——这一条最提"活气"
- 鱼缸里的鱼、桌上飘起的热气

**与你的互动（设计文档里的"人工干预口"在画面上的入口）**
- 点房间 → 拉近细看
- 点她 → 冒出当前心声气泡
- 注入天气/轻推（按钮）→ 画面即时响应
- 她"记得你来过"：被干预后留个小反应

**叙事氛围**
- 底部"今天的生活长卷"时间线（你截图里已有）
- 重要记忆在对应物件上留个微光标记（"这本书她读了三天"）

> 以上绝大多数是 CSS/canvas 粒子与渐变，**运行极轻、零美术**。要多富有多富。

---

## 6. 设计 token（hex，全部从这取）

```css
:root{
  --bg-night-1:#211d30; --bg-night-2:#19162a; --bg-dusk:#3a3350;
  --wall-1:#f6e9cf; --wall-2:#ecd9b4; --wall-line:#cdb389; --wall-edge:#6b5238;
  --wood:#8a5e33; --wood-light:#cf8f5e; --clay:#c2742f; --clay-deep:#a4543a;
  --light-core:#fff0cf; --light-mid:#f5cf86; --lamp:#ffe9b0;
  --sage:#6fa364; --teal:#5f8088; --teal-soft:#86a0a8;
  --mood-neg:#5f8088; --mood-neu:#b39b76; --mood-pos:#e0a052;
  --ink:#3a3026; --ink-soft:#9a8a72; --ink-faint:#b39b76; --paper:#fbf3e3;
  --radius-card:22px; --radius-inner:14px; --radius-sm:9px; --space:8px;
}
```
注脚标题/独白用衬线（`"Noto Serif SC", Georgia, serif`）；数字/标签用 sans + `tabular-nums`。

---

## 7. 美术资源清单 + 风格锁定

放 `app/static/img/world/`。

**写实房间底图（L0，每个房间一张"正常单间"渲染图，几何固定）**
```
room_bedroom.png  room_living.png  room_kitchen.png  room_balcony.png
```
> 关键①：**每张是一张正常的室内画**（正视 / 微俯视单间），**不是切开墙的剖面图**——这才让写实化成立、不诡异。四张并排拼成房间带，相邻边缘留可衔接的墙/门。
> 关键②：**每间只出一张中性光底图**，时段/天气全靠 L1 代码调色与叠层，**不要为每个时段重渲染**（省事 + 保证对齐）。
>
> 写实底图风格提示词：`photorealistic cozy room interior, eye-level front view of a single room, warm wooden furniture, large window, soft neutral daylight (gradeable), highly detailed, consistent light direction, no people`

**风格化角色 + 道具（L2/L3/L4）**
```
角色   neno_rig/ (纸偶部件: head/hair/torso/arm/leg) 或 neno_{action}.png
道具   obj_kettle_{cold|warm|boiling}.png  obj_plant_{fresh|needs_water|wilting}.png ...
动态   obj_{key}_default.png
```
> 风格化提示词：`warm hand-drawn game character/props, soft rounded shapes, cozy storybook style, transparent background, gentle shading, NOT photorealistic`
- 角色与道具**透明底、统一视角与光向**，否则贴上去会飘。
- 物件状态别硬编码：读 `virtual_world.json` 的 `categories[].states`，缺图回退几何。

---

## 8. 数据契约：`/world-live` JSON → 视觉

后端已就绪：`GET /debug/consciousness/world-live`（admin token，纯只读，不花钱）。实测结构：

```json
{ "success":true, "loop_enabled":false, "world":{
  "sim_time":"18:42", "location":"living_room",
  "rooms":{ "living_room":{"label":"客厅","objects":[{"key":"kettle","state":"warm"}]}, ... },
  "money":86, "plan":[{"phase":"...","intent":"...","done":false}], "carried_over":[],
  "recent":[{"action":"read_book"}], "gone":["杯子"],
  "last":{"action":"read_book","reason":"...","inner":"..."},
  "energy":54, "energy_status":"awake", "mood":"不安", "mood_valence":-0.3
}}
```

| 字段 | 驱动 | 怎么画 |
|---|---|---|
| `location` | L4 她走到哪个房间 + L1 光池 | 寻路到该房间锚点，walk 动画；暖光池移过去 |
| `last.action` | L4 播哪个动作 | `neno_{action}` / 纸偶对应姿态；未知→idle |
| `rooms[].objects[].state` | L2 物件选帧 + L5 特效 | 换帧；boiling→蒸汽，lamp on→灯晕 |
| `dyn_objects`/`removed`/`gone` | L3 增减道具 | 新物件填房间空位（带"出现"动效）；移除淡出 |
| `mood`+`mood_valence` | L4 姿态/光环 + L6 心情色 | 冷↔暖插值；姿态含胸↔挺拔 |
| `energy_status` | sleeping 时 | →`neno_sleep`，整屋转夜、灯灭 |
| `sim_time` | L1 时段色温 | 由小时映射全天候光照 |
| `money`/`plan`/`gone`/`last.inner` | L6 注脚 | 见 motion/concept 注脚区 |

刷新：轮询 `/world-live` 默认 5s（纯读、不花钱）；状态变化做**过渡**不硬切。保留手动 `POST /world-tick` 步进按钮。

---

## 9. 需要后端补的字段（可选，且只增不改不删）

大部分富度无需动后端。若要更精准，只能往 `world_loop.build_snapshot()` 返回里**新增**：
- `weather`（接 `LifeEventSource` 的天气事件）→ 驱动 L1 雨雪
- `season`（由真实日期推）→ 窗外树色
- （非必须）`neno.facing` / `neno.carrying` —— 也可前端从 `last.action` 推断，能不动后端就不动

**禁止**：改现有字段含义、删字段、动 DB schema。

---

## 10. 性能与动效

- 全 2D：图片 + CSS transform + canvas 粒子。**运行极轻**，手机都满帧。重的是 LLM，不是画面。
- 粒子（雨/雪/光尘）控制在合理数量，用 `requestAnimationFrame` 或 CSS；页面不可见时暂停。
- 动效克制：移动 1~1.5s、氛围循环 ≥2.5s、`ease-in-out`；尊重 `prefers-reduced-motion`（开了就静止）。

---

## 11. 边界（红线，务必遵守）

- **禁改**：`session_submit_controller / session_aggregation_controller / context_builder / chat_service / proactive/rules / history_digest`。
- 可视化是**纯前端 + 复用现有只读端点**，正常不动任何后端 Python。
- 新增视觉字段只能加在 `build_snapshot()` 返回里，**只增不改不删**；不动 DB schema。
- 这两个端点（`/world-live`、`/world-tick`）是世界引擎唯一出口，重构控制台时**务必保留**（挪位置可、签名/契约别改）。
- 不 commit、不 push 由用户决定。

---

## 12. 落地顺序（核心先跑通，富度无限累加）

1. **骨架可动**：房间带(先几何占位) + 跟随镜头(translateX 居中她) + 小地图 + 坐标表 + 她横向寻路 + 4 个核心动作 + 接 `location`/`last.action`。零美术、零花钱、纯前端。参照 `world_view_follow.html` 直接起步。
2. **状态与增减**：L2 物件状态、L3 动态道具、L5 特效，接 `state`/`dyn_objects`/`gone`。
3. **氛围第一波**：L1 时段色温 + 灯光 + 当前房间光池。
4. **套 token 去廉价感**，定稿布局。
5. **换美术**：写实舞台底图替 L0；风格化角色/道具替 L2/L3/L4。代码不改。
6. **富度累加**：天气 → 窗外世界 → 居家活物(那只猫!) → 互动入口 → 叙事氛围。一条一条加，每条加完都是完整状态。
7. **用 `world-tick` 反复步进，肉眼校对**。

> **完成标准 = 你亲眼看着像她在过日子，不是接口通。** 富度没有终点，停在你满意的任意一层都成立。

> 后端世界引擎（压力触发/意外/低频 LLM）是另一份解耦设计：`../living-world-plans/living_world_design.md`，与本可视化互不阻塞。
