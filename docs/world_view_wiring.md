# 世界引擎视图 · 接后端改造说明（给 Codex）

> 目标：把 `world-observatory-v9.html` 的**世界引擎工作区**从写死的 `states[]` 改成读真实后端。
> **范围**：只接"世界引擎"视图。**控制中枢暂不接**（见末尾"暂不接"）。
> 红线：纯前端 + 复用现成只读端点；不碰 6 个红线文件；不改 DB schema；要补字段只能往 `build_snapshot()` 只增不删。

---

## 0. 后端端点（已存在，无需新写）

```
GET  /debug/consciousness/world-live   → { success, loop_enabled, world:{...} }   纯只读，不花钱
POST /debug/consciousness/world-tick   → { success, world:{...} }                 步进一步
鉴权：请求头  X-Admin-Token: <令牌>   （与现有控制台一致）
```

`world` 真实结构（实测）：
```json
{
  "sim_time":"18:42", "location":"living_room",
  "rooms":{ "living_room":{"label":"客厅","objects":[{"key":"kettle","state":"warm"}]}, ... },
  "money":86, "plan":[{"phase":"evening","intent":"读完一章","done":false}],
  "carried_over":[], "recent":[{"action":"read_book","ago_min":0}], "gone":["杯子"],
  "last":{ "action":"read_book", "reasoning":"…", "micro":"…", "drift":[["kettle","boiling","cold"]],
           "event":null, "sleeping":false, "phase":"傍晚", "ops":[] },
  "energy":54, "energy_status":"awake", "mood":"不安", "mood_valence":-0.3
}
```
注意：
- `last.action` **中英混**：LLM 出 `read_book` 这种英文 key；移动/睡觉是中文（`去厨房`/`睡觉`/`醒来`）。映射要两种都兜。
- 字段是 `last.reasoning`（不是 reason）；`last.micro` 是短心声；`last.drift` 是世界自发变化；`last.event` 是意外。

---

## 1. 房间顺序与默认站位（前端常量）

后端只给"在哪个房间"，不给房间内坐标 → 前端按房间给默认 x（落在主家具旁）。

```js
const ROOM_ORDER = ["bedroom", "living_room", "kitchen", "balcony"]; // 对应 v9 里 data-room 0..3
const ROOM_NAME  = { bedroom:"卧室", living_room:"客厅", kitchen:"厨房", balcony:"阳台" };
const DEFAULT_X  = { bedroom:.58, living_room:.52, kitchen:.42, balcony:.72 }; // 房间内 0..1
```

---

## 2. 动作 → 中文 + 姿势 映射

```js
// 英文 key → 中文展示（中文 action 直接透传）
const ACTION_ZH = {
  read_book:"读书", make_tea:"泡茶", boil_water:"烧水", cook:"做饭",
  water_plant:"浇花", clean:"收拾屋子", rest:"休息", eat:"吃东西",
  look_window:"望向窗外", sleep:"睡觉", organize:"整理",
};
function actionLabel(a){ return ACTION_ZH[a] || a || "发呆"; }

// 动作 → 姿势（驱动立绘/缩放；v9 已有 reading/sleeping class）
function poseOf(a){
  const s = (a||"") + "";
  if (/read|读|书/.test(s))  return "reading";
  if (/sleep|睡/.test(s))    return "sleeping";
  if (/^去|回|walk|move/.test(s)) return "walk";
  return "idle";
}
```

---

## 3. 适配器：后端 `world` → v9 的 `state` 形状

v9 的 `applyState(state)` 基本可复用，只要把后端 `world` 转成它认识的 `state`：

```js
function mapSnapshot(world){
  const roomKey = world.location || "living_room";
  const roomIdx = Math.max(0, ROOM_ORDER.indexOf(roomKey));
  const last = world.last || {};
  // 厨房水壶是否在烧
  const kitchenObjs = (world.rooms?.kitchen?.objects) || [];
  const steam = kitchenObjs.some(o => o.key==="kettle" && o.state==="boiling");
  // 世界自发变化 → 那句"水凉了/雨没停"
  const drift = (last.drift||[]).map(d => Array.isArray(d) ? `${d[0]} ${d[1]}→${d[2]}` : d);
  const change = last.event || drift.join("；") || "";
  const action = actionLabel(last.action);

  return {
    room: roomIdx,
    x: DEFAULT_X[roomKey] ?? .5,
    action,                                   // 大标题
    thought: last.micro || action,            // 气泡（短）
    inner: last.reasoning || "",              // 引述独白
    mood: world.mood || "—",
    energy: world.energy ?? "—",
    duration: "",                             // 后端暂无，留空或后续补
    time: world.sim_time || "--:--",
    change,                                    // "世界变化"小框
    foot: "",                                  // 可由 plan/carried_over 拼，先留空
    moment: action,                            // 长卷当前格
    steam,
    pose: poseOf(last.action),
    walk: poseOf(last.action)==="walk",
    plan: world.plan || [],                    // 用于渲染计划清单
    gone: world.gone || [],
  };
}
```

---

## 4. 用轮询 + tick 取代写死的步进

删掉写死的 `states[]` 与 `step()` 循环，换成：

```js
const ADMIN_TOKEN = /* 与现有控制台同源取令牌，例如 localStorage / 现有 getAdminHeaders() */;
const HEADERS = { "X-Admin-Token": ADMIN_TOKEN };
let latest = null;

async function loadWorld(){
  try {
    const r = await fetch("/debug/consciousness/world-live", { headers: HEADERS });
    const data = await r.json();
    if (!data.success) return;
    latest = mapSnapshot(data.world);
    applyState(latest);          // 复用 v9 的渲染
    renderPlan(latest.plan);     // 见 §5
  } catch(e){ /* 静默或状态栏提示 */ }
}

// “步进一步”按钮：真的推世界一步
document.getElementById("stepButton").addEventListener("click", async (e) => {
  e.target.disabled = true;
  try {
    await fetch("/debug/consciousness/world-tick", { method:"POST", headers: HEADERS });
    await loadWorld();
  } finally { e.target.disabled = false; }
});

// 常驻轮询（纯读、不花钱）
loadWorld();
setInterval(loadWorld, 5000);
```

> 小地图按钮原本"跳到某房间的写死状态"——现在没有写死状态了。两种处理：
> (a) 仅作纵览高亮，不可点跳（推荐，因为房间由她决定）；
> (b) 或保留点击→`POST /world-tick` 直到她走到那间（不建议，绕）。先做 (a)。

---

## 5. 计划清单改成按数据渲染

现在 `<ul class="plan">` 三条是写死在 HTML 里的，改成动态：

```js
function renderPlan(items){
  const ul = document.querySelector(".plan");
  ul.innerHTML = (items||[]).map(it =>
    `<li class="${it.done?'done':''}">${it.intent || it.phase || ""}</li>`
  ).join("");
}
```

（`applyState` 里把 `currentMoment`、`storyFoot` 等已有逻辑保留即可。）

---

## 6. 资源落位（同源，fetch 才不跨域）

现在页面和图片在 `tmp/brainstorm-console/content/`，相对路径。接后端要同源：
- 页面 → 由后端静态目录提供（如 `app/static/console/world-observatory.html` 或并入现有控制台）
- 图片 → `app/static/img/world/`，HTML 里 `background-image`/`<img src>` 改成该路径
- 确认 fetch 用相对路径 `/debug/...`（同源），令牌沿用现有控制台的取法

---

## 7. 数据缺口（前端先兜底，别为它动后端）

| 缺的 | 现状 | v1 处理 |
|---|---|---|
| Neno 房间内 x | 后端没有 | 用 `DEFAULT_X` 默认站位 |
| 天气/下雨 | 后端没 `weather` | **先关掉 `.rain`**（或后续 `build_snapshot` 接 `life_events` 补 `weather`，只增） |
| 持续时间 duration | 后端没有 | 留空 |
| "世界变化"文案 | 用 `last.drift`/`last.event` | 已在 mapSnapshot 拼好 |
| 坐姿/睡姿立绘 | 只有站姿 1 张 | 美术补齐前，先用现有缩放占位（不影响接线） |

---

## 8. 暂不接：控制中枢

控制中枢的**系统拓扑 / 实时事件流 / 检查器 / 待处理队列全是写死假数据**。接活需要后端**新端点**（拓扑、结构化事件 feed+详情、任务队列），**目前不存在**。
- 有 `GET /debug/consciousness/events` 可能喂一部分事件流，但拓扑/检查器/队列要新写后端，属另一阶段。
- **v1：控制中枢保持静态壳子或隐藏，不接。**

---

## 9. 人工干预口（后续，已有端点可用）

后端已有 `POST /debug/consciousness/inject`（注入）与 `/think`。等世界视图接通后，可拿来做设计文档里的"注入事件 / 轻推"方向盘。本期先不做。

---

## 验收（你的眼睛，不是接口通）

1. 后端开 `world_loop`（低频即可），打开页面 → 她的位置/动作/心情/计划**跟着真实世界每 5 秒变**
2. 点"步进一步" → 世界真推进一格，画面随之变
3. 关掉假数据后，没有任何写死的 `states` 残留
4. 看着像她在过日子，不是在播 demo
