# 刀① 阶段 1+2 合并 · Codex 详规（种子进世界引擎 + self_context）

> 上位方案：`docs/dao1-self-developed-life-plan.md`（v4）。本文件是给 codex 的**实现详规**，
> 签名/接入面/门控边界已钉死，照着写，别自创第二套机制。
> **北极星**：用户体验第一，防伪边界是命。基建砍到刚好不崩。
>
> **r2 闭合（codex 二轮 review，6 阻断+3 小修全修）**：①种子确定性注入不依赖 LLM（默认关也可见，§1d/§4/§5）；
> ②关系挪阶段4（WorldLoop 无 session_id，§3b）；③门控比 action+energy_status、睡醒 hard trigger（§3a/§3e）；
> ④tick 尾用 `ws`/`nstate` 不用 `sim`、挂 line 494 前（§3a/§3e）；⑤独立开关红线重写不矛盾（§6）；
> ⑥补 timeout 配置（§2b/§3c）；小修：guard 删"读书"、seed 真 try/except。

## 0. 一句话目标
把"她是谁"的根从聊天 prompt 搬进世界引擎：种子存 `prompts/seed.json`（不可变基石），
世界引擎用廉价 LLM 维护一段 `self_context`（活的"此刻的你"），聊天和 world_brain **只读**它。
**世界引擎为主，聊天彻底当读者。**

---

## 1. 种子（`prompts/seed.json` + config 装载 + system.txt 砍壳）

### 1a. 新建 `prompts/seed.json`
```json
{
  "name": "Neno",
  "age": 18,
  "temperament": "偏活泼、暖一点、说话松弛不端着，跟熟的人会慢慢放开",
  "background_principle": "专业/学校/家乡/过去这些不是预设的，是真实生活里慢慢长出来的；按已确立的自己来、和过去一致；没确立的就自然带过，别现编一个固定设定填进去。"
}
```
- 就这 4 个键，别加别的。

### 1b. `app/config.py`：装载种子
- 在 `SYSTEM_PROMPT = load_text("prompts/system.txt")`（约 line 56）**下面**加（**真正的 try/except**，别裸 loads）：
  ```python
  import json as _json
  try:
      NENO_SEED = _json.loads(load_text("prompts/seed.json"))
  except Exception:  # 文件缺失/损坏只防手滑，不让 config 崩
      NENO_SEED = {}
  ```
  （复用现成 `load_text`；正常情况文件必须存在，except 只兜底。）

### 1c. `prompts/system.txt`：砍成纯声音壳（**定稿，照抄**）
**把现有 line 1~5 整块换成下面两行**（其余 line 7 往下「聊天方式/情绪/记忆/时间/绝对禁止」**全部保留不动**）：
```
你叫 Neno，一个女生，现在正和对方在QQ上日常聊天。
你具体是谁——年纪、气质、最近过的生活、和对方的关系——由系统在下面动态区告诉你。顺着那个来、和过去保持一致，别在这里另编一套固定设定。
```
**删除理由（codex/用户都要知道）**：
- 旧 line 1「20岁出头」→ 年纪由种子出（18），不在 system.txt 写死。
- 旧 line 2「有点小傲、嘴硬、不喜欢太热情、懒散」**是冷人设，与种子气质「偏活泼、暖一点、松弛」直接冲突** →
  **一并删除**，气质统一由种子确定性注入，避免她精神分裂（种子说暖、壳说傲冷）。
- 旧 line 3~5 背景段（大学/专业固定/日常节奏）→ 全删（就是逼她现编的源头）。
- 性别「女生」留在壳里（种子 json 维持 4 键不扩字段）；line 7 以下是「怎么说话」的声音脚手架，与暖活泼不冲突，保留。
- **红线**：system.txt 是**静态可缓存**区，**不许**塞动态内容（种子值、self_context）。
  种子/self_context 都**不经 system.txt**——见 §4 三层结构（种子确定性注入动态槽 + self_context 走动态槽）。

### 1d. 种子是确定性的，不依赖 LLM（**修 codex #1 致命洞**）
**关键**：`self_context` 默认关闭、首次未生成、或组写失败时，种子**仍必须可见**，否则她不知道自己 18 岁/没气质 → 现编。
所以种子**不经 LLM、确定性注入**：
- 聊天：`build_self_state_context()` **始终**从 `config.NENO_SEED` 确定性渲染一段种子块（见 §4 第 1 层）。
- world_brain：**始终**读 `config.NENO_SEED` 确定性种子，即使 `self_context` 为空（见 §5）。
- LLM 只负责生成「生活语境」那层（`self_context`，可为空），**不负责种子**。

---

## 2. self_context 存储 + 配置（6 件闭合条件里的 #1 #3）

### 2a. WorldState 加 3 字段（`app/services/consciousness/world_model.py`，`class WorldState`）
`life_world_state` 是单行 JSON blob（`state_json`），**零 schema 迁移**，直接加 pydantic 字段（旧数据自动补默认）：
```python
self_context: str = ""                      # 组好的"此刻的你"自然语言段
self_context_basis: dict | None = None      # 上次生成时的比较基准（#1）
self_context_updated_at: str = ""           # ISO 时间戳
```
- `self_context_basis` 至少存：`{location, action, mood_band, relationship_revision, generated_at}`。
  **没它重启后判断不了"变没变"**，"失败不推进基准"会变空头支票。

### 2b. 独立配置（`app/services/consciousness/config.py`，仿 `world_llm_enabled` 那行）
```python
self_context_llm_enabled: bool = _env_bool("CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED", False)
self_context_min_interval: int = int(os.getenv("CONSCIOUSNESS_SELF_CONTEXT_MIN_INTERVAL", "600"))
self_context_max_interval: int = int(os.getenv("CONSCIOUSNESS_SELF_CONTEXT_MAX_INTERVAL", "10800"))
self_context_model: str = os.getenv("OPENROUTER_SELF_CONTEXT_MODEL", "openai/gpt-4o-mini")
self_context_llm_timeout_seconds: float = float(os.getenv("CONSCIOUSNESS_SELF_CONTEXT_LLM_TIMEOUT", "20"))
```
- **必须独立于 `world_llm_enabled`**（#3）：关掉世界决策时 self_context 仍可单独开关；示例 `.env` **默认关**。
- `.env.example`（若有）补这 5 行，注释"默认关，开了每 ~10min 一次廉价组写"。

---

## 3. self_context 组写器（核心，#2 #4 #5 #6）

新建 `app/services/consciousness/self_context.py`，一个组写函数 + 一个守门器。

### 3a. 触发门控（#2 #4：用 `ws`/`nstate`，不是 `sim`）
**挂点（codex #4）**：`sim` 只活在清醒分支；睡眠分支只有 `ws`。所以组写入口挂在**两分支汇合之后**——
`world_loop.py` 现有 line 491 那块 presence/owe-reply 之后、**最后一次 `await self._world_store.write(ws)`（line 494）之前**，
统一传 `ws, nstate`。组写成功就改 `ws` 的三字段，由那次已有的 `write(ws)` 落库（不额外加写）。
**完全独立于 world_pressure / world_llm 门控**——self_context 有自己的开关和节奏。

判定逻辑（伪码，#2 #3 修正版）：
```
if not cfg.self_context_llm_enabled: return            # 关了直接跳（独立开关，#5）
now = time.time()
basis = ws.self_context_basis or {}
elapsed = now - parse_ts(ws.self_context_updated_at)    # 没生成过 = 无穷大
mood_band = band_of(nstate.mood.valence)                # 见 3d
energy_status = nstate.energy.status                    # awake / sleeping
cur_action = (ws.last_tick or {}).get("action", "")

# 睡↔醒切换 = hard trigger，绕过最短间隔（兑现"睡着分支也更新一次"）
hard = energy_status != basis.get("energy_status")
significant = (
    ws.location != basis.get("location")                # 换房间
    or mood_band != basis.get("mood_band")              # 心情跨档
    or cur_action != basis.get("action")                # 换动作（#3：必须比 action）
    or hard                                             # 睡醒切换
    # 阶段3 接：新自我事实 → significant=True
)
force = elapsed >= cfg.self_context_max_interval         # 太久没刷，强制重组
if not (hard or force or (significant and elapsed >= cfg.self_context_min_interval)):
    return
# 600s 最短间隔自然节流动作变化 → 不会 8 秒一 tick 几秒重写一次（#3：不需额外累加器）
# 睡醒是 hard，立即触发不受间隔限制
```
- **就地内存值**：用 tick 里已结算的 `ws`/`nstate`，**别再 `read()`**（CLAUDE.md 硬规则：submit 异步落库，同 tick read 读不到刚提交的值）。

### 3b. 合法输入来源（钉死，#5；关系**阶段 2 不读**，修 codex #2）
组写**只能读**这些，别的一律不碰：
- **0 号输入** = `config.NENO_SEED`（种子，最底、最高优先）。
- ① 世界状态：`ws.location` / `(ws.last_tick or {}).get("action")` / `ws.recent_actions` / 活跃 `ws.open_threads`。
- ② 内在状态：`nstate.energy`（精力/睡醒）、`nstate.mood`（情绪）。**情绪是合法来源，明确算进来。**
- ③ **关系：阶段 2 暂不读**（codex #2）。`WorldLoop` 没有 `session_id`，而 `relationship_state` 按 session 查；
  `relationship_revision` 字段也不存在——硬接会逼新窗口 agent 瞎猜。**关系连续化整个挪到阶段 4 一起做**
  （那时定 primary session ID + 具体字段：updated_at / conversation_count / 四项 score）。本阶段 basis 也不含关系。
- ④ 自我事实 `long_term_memory(subject="neno")`：**阶段 1+2 还没有，先传空**。
  **严禁**去读旧的 `subject=""`（那是用户的记忆，不是她的，#8）。

### 3c. 组写 + LLM 调用
- 复用 `from app.llm.openrouter_client import chat_with_openrouter`，async executor 包（仿 `world_brain.py:227`
  / `daily_planner.py:83`：`await loop.run_in_executor(None, partial(chat_with_openrouter, ...), timeout=...)`）。
- model = `cfg.self_context_model`；timeout = `cfg.self_context_llm_timeout_seconds`（#6 新增配置）。
- **组写 prompt 契约（防扩写软层，#6）**：
  - 把输入事实**编号**喂进去（"事实1: 她在客厅；事实2: 精力有点低；事实3: 刚在整理客厅…"。**阶段 2 无关系事实**）。
  - 指令：**只能压缩/转述编号事实**，信息不足就省略，**不许补**专业/学历/家乡/家庭/过去等没给的设定，不许"合理推测"。
  - 输出一段 2~4 句的自然语言"此刻的你"，第二人称（"你现在…"），给聊天/world_brain 当底色。
- **失败降级**：LLM 调用异常/超时/空 → 留上一版 self_context、**不推进 basis**、记 `log_event` warning（带 trace_id）、
  **不阻断 tick**。下次再试。

### 3d. 最小反扩写守门器（硬层，让"绝不扩写"是真的，#6）
组写**输出后、落库前**过一道码层 guard：
```python
HIGH_RISK = ["专业", "大学", "学校", "学院", "家乡", "老家", "父母", "爸妈", "家人",
             "职业", "工作单位", "公司", "毕业", "上学"]  # 身份/传记锚
# 注意：删了"读书"——"在客厅读书"是正常生活行为，会误杀（codex 提醒）。保留上学/学校/大学/毕业等身份词。
def guard(output: str, input_facts: str) -> bool:
    for kw in HIGH_RISK:
        if kw in output and kw not in input_facts:
            return False   # 输出冒出输入里没有的高风险身份 → 拒绝
    return True
```
- guard 不过 → **拒绝本次结果、保留旧 self_context、不推进 basis、记 warning、不阻断 tick**（同失败降级）。
- 就一个关键词 guard，够堵"画画→设计专业"这类漂白即可，别做复杂 NLP。
- `band_of(valence)`：把 mood valence 切 3~4 档（如 <-0.2 低 / -0.2~0.2 平 / >0.2 好），给 basis 比较和组写用。

### 3e. 成功落库
- 组好且 guard 过（写 `ws`，由 line 494 那次已有 `write(ws)` 落库；basis 字段见 codex #2 #3：含 action/energy_status，不含关系）：
  ```python
  ws.self_context = output
  ws.self_context_basis = {
      "location": ws.location,
      "action": (ws.last_tick or {}).get("action", ""),
      "mood_band": mood_band,
      "energy_status": nstate.energy.status,   # #3：进 basis，兑现睡醒触发
      "generated_at": now_iso,
  }
  ws.self_context_updated_at = now_iso
  # 不在这里额外 write——汇合点后面 line 494 的 await self._world_store.write(ws) 会落库
  ```

---

## 4. 聊天接读（`self_state_context.py` 外科手术，三层结构，#1 #4）

`build_self_state_context()`（`app/services/chat/self_state_context.py:50`）现在**手拼**地点/动作/精力/情绪/牵挂，
**还背着**：睡醒框架（line 87-89）、presence gate + DEFER_MARKER（line 108-116）、读失败降级。

**改成三层装配（顺序固定）**，每层独立、互不依赖：

**第 1 层 — 确定性种子（始终注入，不依赖 LLM，修 #1）**：
- 从 `config.NENO_SEED` 渲染一段固定种子块，**永远有**，与 self_context 开没开、生成没生成无关：
  > 你叫 Neno，{age} 岁。你的气质：{temperament}。{background_principle}
- 这是堵 #1 洞的关键：self_context 默认关/没生成/失败时，她**仍知道自己 18 岁、有气质**，不现编。

**第 2 层 — 生活语境 self_context（LLM 生成，可为空，有回退）**：
- 读 `life_world_state` 的 `state_json.self_context`。**非空 → 用它**当"此刻你正过的生活"那段。
- **空（没开/还没生成/降级保留旧空）→ 回退到现在的手拼逻辑**（line 86-106 那套地点/精力/心情/牵挂），
  别让她突然没生活状态。
- 即把现有 line 86-106 包成"self_context 为空时的 fallback"，非空时用 self_context 顶替。

**第 3 层 — live 睡醒 + presence（一字不动，#4）**：
- 睡醒框架（line 87-89）：**此刻是否在睡仍 live 读 `agent_state` energy.status**——self_context ~10min 才刷会滞后，
  不能靠它判"此刻睡没睡"。
- presence gate + DEFER_MARKER（line 108-116）：**原样保留**。
- try/except 读失败降级：保留。

- **装配位置不变**：仍返回一段（或按原位置拆几段）system 块，放现成动态槽。**不重设计 prompt 接口、不动缓存顺序。**
- 三层结构 = `确定性种子 + LLM self_context(可空回退) + live 睡醒/presence`（codex #1 钦定）。

---

## 5. world_brain 接读（确定性种子 + self_context，#1）
- **始终注入确定性种子**：world_brain 组 prompt 时**总是**读 `config.NENO_SEED`（即使 `self_context` 为空），
  让她行动也知道自己是谁——堵 #1 洞，跟聊天同源。
- **self_context 非空时再叠一层**：把 `ws.self_context` 作为"此刻的你"上下文加进去。
- 找 world_brain 组 prompt 的地方（`world_brain.py`）插这两段。
- **只读**，world_brain **绝不写回** self_context / 自我库。

---

## 6. 红线（违反即打回）
- **防伪边界是命**：进 prompt 的自我信息只来自 种子 / 已持久化真实状态(世界+内在+关系) / 自我事实（本阶段为空）。
  组写不许扩写，guard 兜底。
- **self_context 只读派生，绝不反向写回自我库**（堵循环：摘要→world_brain 信→行动→反思证成事实）。
- **独立门控（修 codex #5 自相矛盾）**：两个开关**互不影响**——
  - `self_context_llm_enabled=False` → **绝不**调用组写 LLM。
  - `world_llm_enabled` 只管 WorldBrain 的决策路径。
  - 世界决策关、self_context 开时：**允许只调 self_context LLM**，但**绝不改变 deterministic routine**
    （`routine_decide` / mock 的决策行为一字不变）——CLAUDE.md 硬规则针对的是**决策路径**，self_context 是旁路只读派生，不碰它。
- **就地内存值**：tick 内 self_context 读 `sim`/`nstate`，不 `read()`。
- **静态 prompt 不塞动态**：种子/self_context 不进 system.txt；走动态槽。
- **示例配置默认关**；**不碰 `.env`**；**不 commit**（用户亲自）。
- **只读 `subject="neno"`，严禁把旧 `subject=""` 用户记忆当成她的**（本阶段自我库还空，传空即可）。

---

## 7. 测试（codex 写，pytest）
- `test_self_context_compose`：mock `chat_with_openrouter` 返回固定段 → 断言写进 `sim.self_context` + basis 三件齐。
- `test_self_context_gate`：未到 min_interval / 无显著变化 → 不调用 LLM（mock 断言 0 次调用）；换房间且过间隔 → 调用。
- **反扩写测试（验收核心）**：输入事实只给"经常画画"，
  - 软层：mock LLM 返回**不含**"设计专业" → 通过；
  - 硬层：mock LLM **硬返回**"她是设计专业学生" → guard 拒绝、`sim.self_context` 保留旧值、basis 不推进。
- `test_self_context_disabled`：`self_context_llm_enabled=False` → tick 完全不碰 LLM，mock 行为不变。
- `test_self_state_context_reads_self_context`：`life_world_state.self_context` 有值 → 聊天块用它；
  为空 → 回退手拼；**presence gate / DEFER_MARKER / 睡醒 live 判定在两种情况下都还在**。
- **`test_seed_always_visible`（验收核心，#1）**：`self_context_llm_enabled=False` **且** `self_context` 为空时，
  聊天块**仍含种子**（断言出现 `NENO_SEED["age"]`/气质关键词）；world_brain prompt 同样始终含种子。
  → 证明种子默认关闭也不消失、她不会因没开功能而现编。
- 别破坏现有 72+ 测试。`test_glide_falls_back_on_transient_action` 是预存 flaky（无种子 rng），与本改动无关。

## 8. 验收（codex 自查 + 我审 + 用户跑）
- codex 自查：`pytest -q`（codex 在 Windows 沙箱跑不了的话，写对即可，我来跑）。报：改了哪些文件 + 关键签名 +
  门控判定贴出来供我审缓存/防伪边界。**别自己开浏览器、别 commit。**
- 我审：防伪边界、缓存顺序（system.txt 没塞动态、动态走原槽）、独立门控、就地内存值。
- 用户跑：开 `CONSCIOUSNESS_SELF_CONTEXT_LLM_ENABLED=1`，聊天里看她是否"18/暖/连续/不现编"，
  控制台看 self_context 段是否随她生活变。
