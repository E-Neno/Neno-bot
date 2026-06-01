# Phase 3b 实现方案 v3

> 基于 PHASE_3b.md、代码考古报告、用户补充约束修订（含三点校正）。

---

## 1. 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `app/config.py` | 末尾追加常量 | `BRAIN_WHITELIST_USERS`（env 读取，空=全量关闭） |
| `app/services/proactive/send_executor.py` | 末尾新增函数 | `send_brain_intent()` |
| `app/services/proactive/runner.py` | 末尾新增函数 | `consume_brain_intents()` + `run_consume_brain_intents()` |
| `app/services/consciousness/__init__.py` | `start()` 内追加 | 注册 consume 调度 job；不新增 feed_user_event（留后续） |
| `tests/unit/test_phase3b.py` | 新增文件 | 6 个核心场景 |

**零改动**：rules.py / proactive_service.py / send_executor 现有函数 / check_and_send_once / candidate_service.py / context_builder.py / chat_service.py / history_digest.py / session_submit_controller.py / session_aggregation_controller.py / platform.py

---

## 2. 每个文件具体改什么

### 2.1 `app/config.py` — 末尾追加

```python
BRAIN_WHITELIST_USERS: list[str] = [
    uid.strip()
    for uid in os.getenv("BRAIN_WHITELIST_USERS", "").split(",")
    if uid.strip()
]
```

空 env → 空 list → **整个 brain send 子系统关闭**。

这不是普通漏斗拦截：当 `BRAIN_WHITELIST_USERS` 为空时，`consume_brain_intents`
在白名单检查处直接返回 `{"action": "whitelist_empty"}`，**不修改 intent status**。
queued intent 保持积压，等待未来白名单配置后自动恢复消费。
这是设计意图：空白名单 = "brain 生成照常，发送全关"。

### 2.2 `app/services/proactive/send_executor.py` — 文件末尾新增

**文件落点决策**：
- `send_executor.py` 已经 import `proactive_service.send_proactive_candidate`（行 18），依赖关系自然
- `runner.py` 已经 import `send_executor.auto_send_dry_run, auto_send_real`（行 56），追加 import `send_brain_intent` 顺畅
- 如果实现过程中发现对 proactive_service 私有 helper 依赖过重导致语义不自然，
  可将 `send_brain_intent` 改放到 `proactive_service.py` 文件末尾。
  无论放在哪里，都只新增函数，不修改现有函数。

**新增 import**（追加到 send_executor.py 顶部现有 import 旁边）：

```python
import json as _json
from app.storage.db import (
    add_proactive_candidate,
    execute_write,
    get_proactive_target_by_session,
)
from app.services.proactive_service import (
    _target_hash_for_session,
    _mask_identifier,
)
```

注意：`send_proactive_candidate` 和 `record_proactive_event` 已在现有 import 中（行 15-18）。

**函数签名**：

```python
def send_brain_intent(
    user_id: str,           # proactive_intent.user_id，格式 "wx:private:12345"
    fragments: list[str],
    trace_id: str,
    intent_id: int,         # proactive_intent.id，用于更新 status
) -> dict:
    """
    将 brain fragments 逐条转写为 proactive_candidates（source='brain'），
    调用现有 send_proactive_candidate() 复用微信发送链路。
    原子发送：一旦开始，完成全部 fragments。
    """
```

**内部逻辑**：

```
1. 提取 platform 和 session_id：
   parts = user_id.split(":")        # ["wx", "private", "12345"]
   platform = parts[0]               # "wx"
   session_id = user_id              # "wx:private:12345"（user_id 本身就是 session_id）

2. 精确查 proactive_targets：
   target_row = get_proactive_target_by_session(platform, session_id)
   if not target_row:
       → execute_write UPDATE intent status='dropped'
       → add_debug_event("brain_no_target", reason=f"no {platform} target for {session_id}")
       → return {"success": False, "sent_count": 0, "error": "no target for session"}
   ⚠️ 禁止用 get_latest_proactive_target(platform) 取"最新目标"，否则会发错人。

3. 从 target_row 提取：
   real_user_id  = target_row.get("real_user_id")    # "wxid_xxxx"
   target_hash   = _target_hash_for_session(session_id)
   target_label  = _mask_identifier(real_user_id or "")
   permission_uid = parts[2]                          # "12345"

4. 构造 metadata dict（_resolve_wx_candidate_target 需要的字段）：
   base_metadata = {
       "session_id": session_id,
       "wx_real_user_id": real_user_id or None,
       "wx_permission_user_id": permission_uid,
       "source": "brain",
       "brain_intent_id": intent_id,
       "brain_trace_id": trace_id,
   }

5. 逐条 fragment 发送（原子，不腰斩）：
   sent_count = 0
   error_msg = None
   for idx, fragment in enumerate(fragments):
       meta = {**base_metadata,
               "brain_fragment_index": idx,
               "brain_fragment_count": len(fragments)}
       candidate = add_proactive_candidate(
           platform=platform,
           target_hash=target_hash,
           target_label=target_label,
           message=fragment,
           reason=f"brain intent #{intent_id} frag {idx}",
           status="pending",
           source="brain",
           metadata_json=_json.dumps(meta, ensure_ascii=False),
       )
       try:
           send_proactive_candidate(
               candidate_id=candidate["id"],
               dry_run=False,
               event_source="brain",
               trace_id=trace_id,
           )
           sent_count += 1
       except Exception as e:
           error_msg = str(e)[:200]
           add_debug_event(trace_id=trace_id, module="send_brain_intent",
                           event="fragment_send_failed", level="error",
                           reason=error_msg, action="send_failed")
           break

6. 更新 proactive_intent status：
   if sent_count == len(fragments):
       status = "sent"
   elif sent_count > 0:
       status = "partial"
   else:
       status = "dropped"
   execute_write("UPDATE proactive_intent SET status=? WHERE id=?",
                 (status, intent_id))

7. return {"success": sent_count > 0, "sent_count": sent_count,
           "total": len(fragments), "error": error_msg}
```

**关键**：`send_proactive_candidate(candidate_id, dry_run=False)` 内部走完整 wx 链路：
`_send_wx_candidate` → `_resolve_wx_candidate_target` → `_post_neno_bridge_send_wx` → `_save_proactive_context` → 更新 candidate status。全部复用，零新造路径。

**fragment 间延迟**：不在 `send_brain_intent` 内部 sleep（它是同步函数）。`send_proactive_candidate` 内部已有 bridge HTTP 往返延迟，天然有间隔。如需精确打字延迟，后续在 async wrapper 中加 `asyncio.sleep`。

### 2.3 `app/services/proactive/runner.py` — 文件末尾新增

**新增 import**（runner.py 顶部追加）：

```python
import json as _json
from app.config import BRAIN_WHITELIST_USERS
from app.services.proactive.send_executor import send_brain_intent
```

**函数签名**（模块级同步函数，非 class method，与 runner.py 现有风格一致）：

```python
def consume_brain_intents() -> dict:
    """
    消费 proactive_intent 表中 status='queued' 的意图。
    每次只消费一条（FIFO），经漏斗检查后调用 send_brain_intent()。
    同步函数，由 async wrapper 通过 asyncio.to_thread 调用。
    """

async def run_consume_brain_intents(trace_id: str | None = None) -> dict:
    """async 入口，供 APScheduler 调用"""
```

**consume_brain_intents 内部逻辑**：

```
1. trace_id = new_trace_id()

2. 取第一条 queued intent：
   row = fetch_one(
       "SELECT id, user_id, fragments FROM proactive_intent "
       "WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
   )
   if not row:
       return {"action": "no_intent", "sent": False}
   intent_id, user_id, fragments_json = row["id"], row["user_id"], row["fragments"]

3. 白名单检查（硬性前置）：
   if not BRAIN_WHITELIST_USERS:
       return {"action": "whitelist_empty", "sent": False}   # 不改 status
   if user_id not in BRAIN_WHITELIST_USERS:
       execute_write("UPDATE proactive_intent SET status='dropped' WHERE id=?",
                     (intent_id,))
       return {"action": "whitelist_skip", "sent": False}

4. 漏斗检查（只调用 rules.py，不改逻辑）：
   if rules.hard_cooldown_active():
       execute_write("UPDATE proactive_intent SET status='dropped' WHERE id=?",
                     (intent_id,))
       logger.info(f"[{trace_id}] brain intent dropped: hard_cooldown")
       return {"action": "hard_cooldown", "sent": False}

   if rules.failure_pause_active():
       execute_write("UPDATE proactive_intent SET status='dropped' WHERE id=?",
                     (intent_id,))
       logger.info(f"[{trace_id}] brain intent dropped: failure_pause")
       return {"action": "failure_pause", "sent": False}

   if not rules.within_active_window(datetime.now()):
       logger.debug(f"[{trace_id}] brain intent deferred: outside active window")
       return {"action": "outside_window", "sent": False}   # 保持 queued

   daily_limit = PROACTIVE_DAILY_LIMIT  # 从 config 读
   if rules.today_sent_count() >= daily_limit:
       execute_write("UPDATE proactive_intent SET status='dropped' WHERE id=?",
                     (intent_id,))
       logger.info(f"[{trace_id}] brain intent dropped: daily_limit")
       return {"action": "daily_limit", "sent": False}

5. Recent chat 检查：
   platform = user_id.split(":")[0]   # "wx"
   if rules.has_recent_user_message(platform):
       logger.debug(f"[{trace_id}] brain intent deferred: recent {platform} chat")
       return {"action": "recent_chat_defer", "sent": False}  # 保持 queued

6. 解析 fragments 并发送：
   fragments = _json.loads(fragments_json)
   result = send_brain_intent(user_id, fragments, trace_id, intent_id)

7. 记录 proactive_events：
   record_proactive_event(
       event_type="brain_intent_consumed",
       platform=platform,
       action="sent" if result["success"] else "failed",
       success=result["success"],
       reason=result.get("error"),
       metadata={"intent_id": intent_id, "sent_count": result["sent_count"], ...}
   )

8. return {"action": "sent" if result["success"] else "send_failed",
           "sent": result["success"], **result}
```

**async wrapper**：

```python
async def run_consume_brain_intents(trace_id: str | None = None) -> dict:
    trace_id = trace_id or new_trace_id()
    return await asyncio.to_thread(consume_brain_intents)
```

### 2.4 `app/services/consciousness/__init__.py` — `start()` 末尾追加

```python
# Phase 3b: 注册 brain intent 消费任务
from app.services.proactive.runner import run_consume_brain_intents
self._scheduler.add_job(
    run_consume_brain_intents,
    "interval",
    seconds=30,
    id="consume_brain_intents",
    replace_existing=True,
)
```

不新增 `feed_user_event` 方法（留后续阶段）。不改 chat_service。本阶段 consciousness/__init__.py 只做这一件事：注册调度。

### 2.5 `tests/unit/test_phase3b.py` — 新增

7 个测试场景，全部 monkeypatch 外部依赖：

| 测试 | 场景 | 预期 |
|------|------|------|
| `test_whitelist_empty_blocks` | BRAIN_WHITELIST_USERS=[] | 不创建 candidate，不发送，intent 保持 queued（子系统关闭） |
| `test_whitelist_skip_drops` | user_id 不在白名单 | intent → dropped |
| `test_recent_chat_defers` | has_recent_user_message=True | intent 保持 queued，不发送 |
| `test_outside_window_defers` | within_active_window=False | intent 保持 queued，不发送 |
| `test_three_fragments_sends_all` | 3 个 fragments，全部成功 | 创建 3 条 candidate，intent → sent |
| `test_partial_on_failure` | 第 2 个 fragment 发送失败 | 第 1 条 candidate 成功，intent → partial |
| `test_no_target_drops` | get_proactive_target_by_session 返回 None | intent → dropped |

所有测试 monkeypatch：
- `send_proactive_candidate` → mock 成功/失败
- `add_proactive_candidate` → 返回假 candidate dict
- `rules.*` → 控制漏斗行为
- `get_proactive_target_by_session` → 返回假目标或 None（精确匹配）
- `execute_write` / `fetch_one` → 用 dict 记录调用
- `add_debug_event` → no-op

---

## 3. proactive_candidates 写入字段

```python
add_proactive_candidate(
    platform="wx",
    target_hash=target_hash,           # sha256(session_id)[:12]
    target_label=target_label,         # _mask_identifier(real_user_id)
    message=fragment,                  # 单条 fragment 文本
    reason="brain intent #42 frag 0",  # 含 intent_id + fragment index
    status="pending",                  # send_proactive_candidate 会更新
    source="brain",                    # 标识来源
    metadata_json=json.dumps({
        "session_id": "wx:private:12345",
        "wx_real_user_id": "wxid_xxxx",
        "wx_permission_user_id": "12345",
        "source": "brain",
        "brain_intent_id": 42,
        "brain_fragment_index": 0,
        "brain_fragment_count": 3,
        "brain_trace_id": "abc123",
    }),
)
```

metadata_json 中的 `session_id` + `wx_real_user_id` + `target_hash` 是
`_resolve_wx_candidate_target()` 校验所需的。
`wx_permission_user_id` 是 `_extract_private_session_user_id` 的结果预存。
目标通过 `get_proactive_target_by_session(platform, session_id)` 精确查找，
不使用 `get_latest_proactive_target`，避免发错人。

---

## 4. user_id → 微信 candidate metadata 映射

```
proactive_intent.user_id = "wx:private:12345"   ← 本身就是 session_id
    │
    ├─ platform = split(":")[0] → "wx"
    ├─ session_id = user_id → "wx:private:12345"
    │
    ├─ get_proactive_target_by_session("wx", "wx:private:12345")  ← 精确查
    │     → proactive_targets 行（存在则继续，不存在则 dropped）
    │     real_user_id  = "wxid_xxxx"
    │
    ├─ target_hash    = sha256(session_id)[:12]
    ├─ target_label   = _mask_identifier(real_user_id)
    ├─ permission_uid = "12345"  （从 session_id 提取）
    │
    └─ metadata_json = {
         "session_id": "wx:private:12345",
         "wx_real_user_id": "wxid_xxxx",
         "wx_permission_user_id": "12345",
         "source": "brain",
         "brain_intent_id": intent_id,
         "brain_fragment_index": 0,
         "brain_fragment_count": 3,
         "brain_trace_id": trace_id,
       }
```

`_resolve_wx_candidate_target()` 读到 `session_id` + `wx_real_user_id` +
匹配的 `target_hash` → 成功解析 → 调用 bridge。

**安全保证**：使用 `get_proactive_target_by_session` 精确匹配，
确保 brain intent 只发给对应的 session_id 用户，不会因"最新 target"
逻辑误发给其他人。

---

## 5. proactive_intent.status 更新策略

| 场景 | status 变更 | 写 debug_events |
|------|-------------|-----------------|
| 白名单空 | 不变（queued） | 否，logger.debug。**子系统关闭，积压是预期行为** |
| 不在白名单 | → dropped | 否，logger.info |
| hard_cooldown | → dropped | 否，logger.info |
| failure_pause | → dropped | 否，logger.info |
| outside_active_window | 不变（queued） | 否，logger.debug |
| today_sent_count >= limit | → dropped | 否，logger.info |
| has_recent_user_message | 不变（queued） | 否，logger.debug |
| 无对应 target（精确查无结果） | → dropped | **是** |
| 全部发送成功 | → sent | 否 |
| 部分成功 | → partial | **是**（记录 error） |
| 发送异常 | → dropped | **是**（记录 error） |

---

## 6. 预期 git diff 红线检查结果

| 文件 | 预期 diff |
|------|-----------|
| `app/config.py` | +3 行（BRAIN_WHITELIST_USERS） |
| `app/services/proactive/send_executor.py` | +import 追加 + 末尾新增 `send_brain_intent()` 函数；现有函数零改动 |
| `app/services/proactive/runner.py` | +import 追加 + 末尾新增 `consume_brain_intents()` + `run_consume_brain_intents()`；`check_and_send_once()` 零改动 |
| `app/services/consciousness/__init__.py` | `start()` 内追加 5 行调度注册 |
| `tests/unit/test_phase3b.py` | 新增文件 |
| `app/services/proactive/rules.py` | **零** |
| `app/services/proactive_service.py` | **零** |
| `app/services/proactive/scheduler_runtime.py` | **零** |
| `app/services/chat_service.py` | **零** |
| `app/services/session_submit_controller.py` | **零** |
| `app/services/session_aggregation_controller.py` | **零** |
| `app/services/chat/context_builder.py` | **零** |
| `app/services/chat/history_digest.py` | **零** |
| `app/routers/platform.py` | **零** |

---

## 7. 关键调用链

```
APScheduler (30s interval)
  → run_consume_brain_intents()
    → asyncio.to_thread(consume_brain_intents)
      → fetch_one("SELECT ... FROM proactive_intent WHERE status='queued'")
      → 白名单检查（空=子系统关闭，保持 queued 积压）
      → rules.hard_cooldown_active()              ← 复用 rules.py
      → rules.failure_pause_active()              ← 复用 rules.py
      → rules.within_active_window()              ← 复用 rules.py
      → rules.today_sent_count()                  ← 复用 rules.py
      → rules.has_recent_user_message("wx")       ← 复用 rules.py
      → send_brain_intent(user_id, fragments, trace_id, intent_id)
        → get_proactive_target_by_session("wx", session_id)  ← 精确查
        → for each fragment:
            → add_proactive_candidate(source="brain", ...)   ← 复用 db.py
            → send_proactive_candidate(candidate_id, dry_run=False, event_source="brain")
              → _send_wx_candidate()                          ← 复用 proactive_service.py
                → _resolve_wx_candidate_target(candidate)     ← 读 metadata
                → _post_neno_bridge_send_wx(...)              ← 复用微信 bridge
                → _save_proactive_context(...)                ← 复用落库
                → update_proactive_candidate_status("sent")   ← 复用
        → execute_write("UPDATE proactive_intent SET status=?")
```

---

## 8. 已知限制（Phase 3b 不解决）

1. **消息聚合竞态**：rules.has_recent_user_message 依赖 chat_stats 表，但用户消息可能还在内存聚合队列中未落库。Phase 3b 不改 session_submit_controller / session_aggregation_controller。
2. **fragment 间延迟**：Phase 3b 依赖 bridge HTTP 往返作为自然间隔，不额外加 typing delay。
3. **积压消费**：每次只消费一条 queued intent。如果第一条被 defer（outside_window / recent_chat），后续 intent 排队等待。可接受。
4. **白名单积压**：空白名单时 queued intent 无限堆积，不会 dropped。这是设计意图（子系统关闭），不是 bug。未来配置白名单后自动恢复消费。
