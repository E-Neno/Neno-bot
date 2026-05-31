# PHASE_3b — 漏斗汇流与发送

> **前置**：Phase 3a 已完成并通过全部验收标准。`NenoBrain.run_cycle()` 能正确把 fragments 写入 `proactive_intent` 表，判断层/生成层降级测试全绿，diff 红线文件零改动。
>
> **本阶段目标**：把 `proactive_intent` 表里的待发意图，经由 `rules.py` 同一套漏斗检查后，通过 `send_executor.py` 的发送链路真实发出。**本阶段首次真实发消息，必须先在白名单单用户灰度测试。**
>
> ⚠️ **架构铁律（再次强调）**：
> - `SessionSubmitController` 与本阶段完全无关，**禁止使用**
> - 漏斗复用 `rules.py` 现有函数，**不改 rules.py 逻辑**，只调用
> - 在 `send_executor.py` 旁**新增** `send_brain_intent()`，**不改**现有函数
> - `context_builder.py` 本阶段**不碰**（Phase 4 才注入动态状态）

---

## 1. 本阶段范围

### 改动/新增文件

| 文件 | 改动类型 | 内容 |
|------|----------|------|
| `app/services/proactive/send_executor.py` | **新增函数**（不改现有） | `send_brain_intent(user_id, fragments, trace_id)` |
| `app/services/proactive/runner.py` | **新增方法**（不改现有） | `consume_brain_intents()` — 消费 proactive_intent 表 |
| `app/services/consciousness/__init__.py` | 注入 | APScheduler 注册 `consume_brain_intents` 消费任务 |
| `app/services/chat_service.py` | **尾部追加**（不改现有逻辑） | 回复后调用 `consciousness_engine.feed_user_event()` |

### 本阶段**禁止改动**的内容

| 禁止改动 | 原因 |
|----------|------|
| `send_executor.py` 现有函数（`send_proactive_candidate` 等） | 只新增，不改；改了会破坏现有 proactive 链路 |
| `proactive/rules.py` 任何逻辑 | 只调用，不改；漏斗规则是现有系统精心调校的 |
| `proactive/runner.py` 现有方法 | 只新增 `consume_brain_intents`，不动 `check_and_send_once` |
| `session_submit_controller.py` | 与本阶段完全无关 |
| `session_aggregation_controller.py` | 同上 |
| `context_builder.py` | Phase 4 才改 |
| `history_digest.py` | 不碰 |

---

## 2. 真实发送链路（考古确认版）

```
proactive/runner.py
  consume_brain_intents()          ← 本阶段新增，消费 proactive_intent 表
    ↓
    rules.hard_cooldown_active()   ← 复用现有漏斗（只调用，不改）
    rules.failure_pause_active()
    rules.within_active_window()
    rules.today_sent_count()
    rules.has_recent_user_message()
    ↓ [漏斗通过]
    send_executor.send_brain_intent(user_id, fragments, trace_id)  ← 新增
      ↓
      for fragment in fragments:
          asyncio.sleep(fragmenter.typing_delay(fragment))   ← 打字延迟
          _post_neno_bridge_send_qq(user_id, fragment)       ← 复用现有
          _save_proactive_context(user_id, fragment, ...)    ← 复用现有
      ↓
      UPDATE proactive_intent SET status='sent'
```

**关键：漏斗不变、管路不变、只换 payload。**
- 漏斗：`rules.py` 的全套检查函数，一个都不跳过
- 管路：`_post_neno_bridge_send_qq()` + `_save_proactive_context()`，完全复用
- Payload：不是 proactive_candidates 表的模板 text，而是 brain 生成的 fragments

---

## 3. 接口定义

### `send_executor.py` — 新增函数（追加到文件末尾）

```python
# ──────────────────────────────────────────────────────────
# Brain Intent 发送（Phase 3b 新增，不改上方现有函数）
# ──────────────────────────────────────────────────────────

async def send_brain_intent(
    user_id: str,
    fragments: list[str],
    trace_id: str,
    db: "Database",
    intent_id: int,
    config: "ConsciousnessConfig",
) -> dict:
    """
    发送 brain 生成的碎片化消息。
    复用现有的 _post_neno_bridge_send_qq() 和 _save_proactive_context()。
    成功后更新 proactive_intent.status = 'sent'。
    失败后更新 status = 'dropped'，写 debug_events，不 raise。

    发送间隔：按 Fragmenter.typing_delay() 计算，模拟真人打字节奏。

    返回：{"success": bool, "sent_count": int, "error": str | None}
    """
    from app.services.consciousness.fragmenter import Fragmenter
    import asyncio

    fragmenter = Fragmenter(config)
    sent_count = 0

    try:
        for i, fragment in enumerate(fragments):
            if i > 0:
                delay = fragmenter.typing_delay(fragment)
                await asyncio.sleep(delay)

            # 复用现有发送函数（不改它，直接调用）
            ok = await _post_neno_bridge_send_qq(
                user_id=user_id,
                text=fragment,
                trace_id=trace_id,
            )
            if not ok:
                break

            # 复用现有落库函数（保证 chat 上下文能看到主动消息）
            await _save_proactive_context(
                user_id=user_id,
                text=fragment,
                source="brain",
                trace_id=trace_id,
            )
            sent_count += 1

        # 更新意图状态
        status = "sent" if sent_count == len(fragments) else "partial"
        await db.execute(
            "UPDATE proactive_intent SET status=? WHERE id=?",
            (status, intent_id),
        )
        return {"success": sent_count > 0, "sent_count": sent_count, "error": None}

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"[{trace_id}] send_brain_intent failed: {e}")
        await db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?",
            (intent_id,),
        )
        # 写 debug_events
        try:
            from datetime import datetime
            await db.execute(
                "INSERT INTO debug_events (trace_id, event_type, detail, created_at) "
                "VALUES (?, 'send_brain_intent_failed', ?, ?)",
                (trace_id, str(e)[:500], datetime.now().isoformat()),
            )
        except Exception:
            pass
        return {"success": False, "sent_count": sent_count, "error": str(e)}
```

> ⚠️ **注意**：`_post_neno_bridge_send_qq` 和 `_save_proactive_context` 是 `send_executor.py` 中**已有的私有函数**。直接调用，不重新实现。如果它们的参数签名与上面不完全一致，**以现有函数的真实签名为准**，调整调用方式，不要修改它们本身。

### `proactive/runner.py` — 新增方法（追加到 class 末尾）

```python
async def consume_brain_intents(self) -> dict:
    """
    消费 proactive_intent 表中 status='queued' 的意图。
    每次只消费一条（FIFO），经漏斗检查后调用 send_brain_intent()。

    ⚠️ 漏斗检查复用现有 rules.py 函数，逻辑完全不变。
    ⚠️ 不改 check_and_send_once()，两条路径完全独立。
    """
    import logging
    import uuid
    logger = logging.getLogger(__name__)
    trace_id = str(uuid.uuid4())[:8]

    # 取第一条 queued 意图
    row = await self._db.fetchone(
        "SELECT id, user_id, fragments FROM proactive_intent "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
    )
    if not row:
        return {"action": "no_intent", "sent": False}

    intent_id, user_id, fragments_json = row

    # ── 复用同一套漏斗规则（rules.py，只调用不改）──
    import json as _json
    from app.services.proactive import rules

    if rules.hard_cooldown_active():
        await self._db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?", (intent_id,)
        )
        logger.info(f"[{trace_id}] brain intent dropped: hard_cooldown_active")
        return {"action": "hard_cooldown", "sent": False}

    if rules.failure_pause_active():
        await self._db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?", (intent_id,)
        )
        logger.info(f"[{trace_id}] brain intent dropped: failure_pause_active")
        return {"action": "failure_pause", "sent": False}

    if not rules.within_active_window():
        # 不发但不丢弃，等进入活跃窗口再发
        logger.debug(f"[{trace_id}] brain intent deferred: outside active window")
        return {"action": "outside_window", "sent": False}

    daily_limit = getattr(self._config, "max_proactive_per_day", 20)
    if rules.today_sent_count() >= daily_limit:
        await self._db.execute(
            "UPDATE proactive_intent SET status='dropped' WHERE id=?", (intent_id,)
        )
        logger.info(f"[{trace_id}] brain intent dropped: daily limit reached")
        return {"action": "daily_limit", "sent": False}

    # ── 漏斗通过，调用发送 ──
    fragments = _json.loads(fragments_json)
    from app.services.proactive.send_executor import send_brain_intent
    result = await send_brain_intent(
        user_id=user_id,
        fragments=fragments,
        trace_id=trace_id,
        db=self._db,
        intent_id=intent_id,
        config=self._consciousness_config,
    )

    logger.info(
        f"[{trace_id}] consume_brain_intents: "
        f"sent={result['sent_count']}/{len(fragments)} to {user_id}"
    )
    return {"action": "sent", "sent": result["success"], **result}
```

### `chat_service.py` — 尾部追加（不改现有逻辑）

```python
# 在 handle_message() 返回回复文本之后，异步通知 consciousness 层。
# 追加到文件末尾或 handle_message 函数末尾，不改现有任何逻辑。

async def _notify_consciousness_on_reply(
    user_id: str,
    user_name: str,
    message: str,
    consciousness_engine,  # ConsciousnessEngine | None，从 app.state 读取
) -> None:
    """
    在 Neno 回复用户后，更新 consciousness 层的 last_interaction 和情绪。
    同时触发 P0 打断（如果世界引擎正在酝酿主动消息，则中止）。
    全程异步，失败静默，不影响主流程。
    """
    if consciousness_engine is None:
        return
    try:
        await consciousness_engine.feed_user_event(
            user_id=user_id,
            user_name=user_name,
            message_summary=message[:50],
            mood_impact=0.1,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"consciousness notify failed: {e}")
```

### `consciousness/__init__.py` — 新增 feed_user_event 和消费任务

```python
# 在 ConsciousnessEngine 中新增：

async def feed_user_event(
    self,
    user_id: str,
    user_name: str,
    message_summary: str,
    mood_impact: float = 0.1,
) -> None:
    """
    chat_service 在回复后调用，更新 last_interaction 和情绪。
    同时触发 P0 打断（通知 InterruptController）。
    """
    from .models import StateMutation, LastInteraction
    from datetime import datetime
    await self.state_store.submit_mutation(StateMutation(
        trace_id=f"user_{user_id}_{int(datetime.now().timestamp())}",
        last_interaction=LastInteraction(
            user_id=user_id,
            user_name=user_name,
            time=datetime.now(),
            summary=message_summary,
        ),
        mood_valence_delta=mood_impact,
        reason="user interaction",
    ))
    # P0 打断：通知 brain 有用户消息到来
    await self.interrupt.on_p0_interrupt(pool=self._pool)

# 在 start() 中注册消费任务（consume_brain_intents 每分钟检查一次）：
# ⚠️ 需要把 runner 实例传进来，或在 ConsciousnessEngine 中持有 runner 引用
# 具体依赖注入方式以现有 runner 的构造方式为准
scheduler.add_job(
    self._runner.consume_brain_intents,
    "interval",
    seconds=30,   # 每30秒检查一次，比 brain_cycle 更频繁确保及时消费
    id="consume_brain_intents",
    replace_existing=True,
)
```

---

## 4. 灰度测试方案

**Phase 3b 是整个项目唯一真正发消息的阶段，必须先灰度，不能直接全量上线。**

### Step 1：白名单配置

在 `config.py` 或环境变量中加：
```python
brain_whitelist_users: list[str] = []  # 空=全量关闭；填 user_id=灰度测试
# 例：["qq:private:12345"]
```

在 `consume_brain_intents()` 的漏斗检查之后、发送之前加白名单校验：
```python
if self._config.brain_whitelist_users and user_id not in self._config.brain_whitelist_users:
    logger.debug(f"[{trace_id}] brain intent skipped: not in whitelist")
    return {"action": "whitelist_skip", "sent": False}
```

### Step 2：灰度测试步骤

1. 把自己的 QQ user_id 加入白名单
2. 手动往 event_log 插一条 P1 事件（比如"买了杯奶茶踩雷了"）
3. 等待 brain_cycle（最多 60 秒）触发，确认 proactive_intent 表出现 queued 记录
4. 等待 consume_brain_intents（最多 30 秒）触发，确认：
   - proactive_intent.status 变为 'sent'
   - 手机/客户端真实收到消息
   - messages 表有对应记录（_save_proactive_context 落库）
5. 测试漏斗：手动触发 hard_cooldown（发一条后立即再触发），确认第二条被 dropped
6. 确认无误后，可以把白名单清空或扩大

### Step 3：并发测试

测试世界引擎主动消息 + 用户 P0 消息并发时的打断行为：
1. 手动触发 brain 进入 judging 阶段（插 P1 事件 + 表达欲设满）
2. 同时发一条用户消息（触发 feed_user_event → on_p0_interrupt）
3. 确认 judging 被取消，proactive_intent 无新记录，用户消息正常回复
4. 测试 generating 阶段打断：mock Gemini 延迟 > brain_cycle，验证 stop_after_current

---

## 5. 验收标准（Phase 3b 完成的定义）

### 功能验收

- [ ] 白名单单用户灰度：完整链路跑通（事件 → brain → proactive_intent → 漏斗 → 发送 → 收到消息）
- [ ] 漏斗有效：hard_cooldown 期间 brain intent 被 dropped，不发消息
- [ ] 日上限有效：today_sent_count() 达到上限后 intent 被 dropped
- [ ] failure_pause 有效：模拟发送失败 N 次，确认进入熔断状态
- [ ] 打字延迟：两条碎片之间有真实的间隔，不是瞬间连发
- [ ] `_save_proactive_context()` 确保消息写入 messages 表（Neno 自己说过的话进上下文）
- [ ] `feed_user_event()` 被 chat_service 正确调用，last_interaction 更新
- [ ] P0 打断：用户消息到来时 judging 阶段被取消

### diff 红线（Phase 3b）

| 文件 | 预期 diff |
|------|-----------|
| `send_executor.py` | 只在文件末尾新增 `send_brain_intent()`；现有函数零改动 |
| `proactive/runner.py` | 只在 class 末尾新增 `consume_brain_intents()`；`check_and_send_once()` 零改动 |
| `proactive/rules.py` | **零改动**（只调用，不改） |
| `chat_service.py` | 只在末尾追加 `_notify_consciousness_on_reply()`；现有逻辑零改动 |
| `context_builder.py` | **零改动** |
| `session_submit_controller.py` | **零改动** |
| `session_aggregation_controller.py` | **零改动** |
| `history_digest.py` | **零改动** |

---

## 6. 给 Claude Code 的执行指令

```
请读取以下文件，然后按本文件第 6 节的指令实现 Phase 3b：

必读文件（全部）：
1. NENO_ARCHITECTURE.md（架构约束）
2. CLAUDE.md（系统硬约束）
3. PHASE_3b.md（本文件）
4. PROACTIVE_ARCHAEOLOGY.md（考古结论——proactive真实发送链路，必读）
5. PHASE_3a.md（上一阶段，了解 proactive_intent 表结构和 brain 输出格式）

重要前提：
- Phase 3a 已完成，proactive_intent 表有 queued 记录等待消费
- SessionSubmitController 与本阶段完全无关，禁止使用
- send_executor.py 只新增函数，不改现有函数
- rules.py 只调用，不改逻辑
- runner.py 只新增方法，不改 check_and_send_once

实现顺序：
1. 先读 send_executor.py 现有代码，确认 _post_neno_bridge_send_qq 和
   _save_proactive_context 的真实签名，以真实签名为准调用
2. send_executor.py 末尾追加 send_brain_intent()
3. proactive/runner.py 末尾追加 consume_brain_intents()
4. consciousness/__init__.py 新增 feed_user_event() 和注册消费任务
5. chat_service.py 末尾追加 _notify_consciousness_on_reply()，
   并在 handle_message() 末尾用 asyncio.create_task() 异步调用它

⚠️ 在改动 send_executor.py 之前，必须先用 Read 工具读取其完整内容，
   确认现有函数签名，再决定如何调用。禁止假设签名。

完成后：
1. 先在白名单单用户跑灰度测试（见 PHASE_3b.md 第 4 节）
2. 用 git diff 逐一确认"diff 红线"表格中的零改动项
3. 确认无误后 commit
```
