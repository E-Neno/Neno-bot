# PROACTIVE_ARCHAEOLOGY.md
# Proactive 链路考古结论 — Phase 3 必读

> 本文件记录了对 proactive 发送链路的完整考古结果。
> **在实现 Phase 3 任何代码之前必须读完本文件。**
> 违反本文件结论的设计会导致系统性故障（聊天卡死 / 漏斗失效 / 凌晨狂发消息）。

---

## 1. 最重要的结论（先看这个）

```
❌ 错误假设（原架构文档）：
   proactive 发送走 SessionSubmitController

✅ 真实情况（代码考古确认）：
   proactive 发送完全不走 SessionSubmitController
   它是独立线程内的同步函数，直接 HTTP POST 到 neno-bridge
```

**SessionSubmitController 的真实用途**：
- 只用于 `platform.py → submit_platform_chat_turn`
- 保证同一 session 的**用户聊天消息**不并发执行
- 与 proactive、brain 链路**完全无关**

**如果 Phase 3 强行使用 SessionSubmitController**：
- 把 brain→LLM 调用（几十秒阻塞）塞进 SubmitHandler
- 同一 session 的所有用户聊天请求会全部卡死在 FIFO 队列里
- 这是灾难性故障，必须避免

---

## 2. Proactive 真实发送链路（完整调用栈）

```
proactive/runner.py
  Runner.check_and_send_once(
      ignore_random=False,
      ignore_recent_chat=False,
      ignore_active_window=False,
      force=False,
      dry_run_only=False,
      event_source=None,
      trace_id=None
  ) -> dict
    │
    ├─ [规则漏斗 — 全部使用 rules.py 函数]
    │   hard_cooldown_active()         → bool
    │   failure_pause_active()          → bool
    │   within_active_window(now)       → bool
    │   today_sent_count()              → int
    │   has_recent_user_message(platform) → bool
    │   has_pending_platform_candidate(platform) → bool
    │
    ├─ create_auto_candidate(target_row) → INSERT proactive_candidates
    │
    └─ auto_send_real(candidate, target_row)
         │
         └─ send_proactive_candidate(candidate, target_row)
              │
              └─ _send_qq_candidate(candidate, target_row)
                   │
                   ├─ _post_neno_bridge_send_qq(user_id, text, ...)
                   │    └─ HTTP POST 127.0.0.1:18793/proactive/send-qq
                   │
                   └─ _save_proactive_context(user_id, text, source, ...)
                        └─ add_message() 直接写 messages 表
```

---

## 3. Rules.py 漏斗函数清单（完整）

```python
# proactive/rules.py — 所有函数同步，无副作用，可直接调用

hard_cooldown_active() -> bool
    # 任何 send/generate 事件在冷却窗口内 → True
    # 窗口时长由 PROACTIVE_HARD_COOLDOWN_MINUTES 配置

failure_pause_active() -> bool
    # 连续失败 >= PROACTIVE_FAILURE_PAUSE_THRESHOLD → True
    # 防止反复失败刷 neno-bridge

within_active_window(now: datetime) -> bool
    # 当前时间在 PROACTIVE_ACTIVE_START ~ PROACTIVE_ACTIVE_END → True
    # 控制 Neno 的活跃时间段（比如 8:00-23:00）

today_sent_count() -> int
    # SELECT COUNT(*) FROM proactive_candidates
    # WHERE source='auto' AND status='sent' AND date=today

has_recent_user_message(platform: str) -> bool
    # 近期是否有用户主动发消息（避免"用户刚说完话Neno又主动发"的尴尬）

has_pending_platform_candidate(platform: str) -> bool
    # 是否已有 pending 候选（防重复生成）

last_sent_at() -> str | None
    # 最近一次 auto sent 的时间字符串

# ── 组合诊断入口（只读，不发送）──
evaluate_proactive_rules(include_enabled=True) -> dict
    # 返回 {can_send, reason, platform, target_summary, checks:[...]}
    # 纯只读，适合调试和日志
```

---

## 4. Brain 链路的正确设计（Phase 3 应实现的）

```
WorldEngine heartbeat
  → EventPool.pop_pending()
  → NenoBrain.run_cycle()
      ├─ Step1: 规则过滤（0成本）
      ├─ Step2: DeepSeek 判断（JSON）
      └─ Step3: Gemini 生成 fragments
  → INSERT proactive_intent (status='queued')
         ↑
         这里停，不发消息（Phase 3a 的边界）

─────────────────────────── Phase 3b 边界 ───────────────────────────

APScheduler 每30秒
  → runner.consume_brain_intents()
      ├─ rules.hard_cooldown_active()      ← 复用同一套漏斗
      ├─ rules.failure_pause_active()
      ├─ rules.within_active_window()
      ├─ rules.today_sent_count()
      └─ [漏斗通过] send_executor.send_brain_intent()
           ├─ asyncio.sleep(typing_delay)   ← 打字节奏
           ├─ _post_neno_bridge_send_qq()   ← 复用现有发送
           └─ _save_proactive_context()     ← 复用现有落库
```

**原则：穿同一件漏斗、走同一条管路、灌不同的水。**

---

## 5. send_executor.py 中需要复用的函数

```python
# 以下函数在 send_executor.py 中已存在，Phase 3b 直接调用，不重新实现：

_post_neno_bridge_send_qq(...)
    # HTTP POST 到 127.0.0.1:18793/proactive/send-qq
    # 真实签名以现有代码为准，实现前必须 Read 确认

_save_proactive_context(...)
    # 调用 add_message() 把主动消息写入 messages 表
    # 确保 Neno 说过的话进入对话上下文
    # 真实签名以现有代码为准，实现前必须 Read 确认
```

⚠️ **实现 send_brain_intent() 之前，必须先 Read send_executor.py 确认这两个函数的真实参数签名**。禁止假设参数，以现有签名为准调整调用方式。

---

## 6. 并发模型（asyncio↔threading 风险评估）

```
原始担忧：asyncio 单写者 与 threading 命门 跨范式死锁

实际情况：
- SessionSubmitController 是 threading.RLock，用于用户 chat 串行化
- proactive 发送是独立线程内的同步函数
- brain 是 asyncio 协程
- 三者完全独立，不共享锁，不存在跨范式持锁竞争

结论：Phase 3 不存在 asyncio↔threading 死锁风险
```

唯一需要注意的并发场景：**世界引擎主动消息 vs 用户 P0 消息**
- 这是 brain 内部的 asyncio 打断（InterruptController）
- 全程在同一个 asyncio 事件循环内，无需 threading 锁
- 见 PHASE_3a.md 中 InterruptController 的实现

---

## 7. 关键约束汇总（开发检查清单）

在提交 Phase 3 代码之前，逐条确认：

- [ ] 没有任何代码引用 `SessionSubmitController.allocate_ticket()`
- [ ] 没有任何代码引用 `SessionSubmitController.submit_ready()`
- [ ] `rules.py` 的所有函数只被调用，没有被修改
- [ ] `send_executor.py` 现有函数没有被修改，只在末尾新增了 `send_brain_intent()`
- [ ] `proactive/runner.py` 现有方法没有被修改，只在末尾新增了 `consume_brain_intents()`
- [ ] `_post_neno_bridge_send_qq()` 和 `_save_proactive_context()` 的调用签名以现有代码为准
- [ ] brain 生成的 fragments 最终通过 `_save_proactive_context()` 写入 messages 表
- [ ] `context_builder.py` 未被修改（Phase 4 才注入动态状态）

---

## 8. 如何追加到 CODEBASE_ANALYSIS.md

在 CODEBASE_ANALYSIS.md 末尾追加如下章节：

```markdown
## §新增 — Proactive 链路考古结论（Phase 3 前置）

### 核心结论
- **SessionSubmitController 与 proactive/brain 链路完全无关**
  - 它只用于 `platform.py → submit_platform_chat_turn`（用户聊天串行化）
  - proactive 是独立线程内的同步函数，直接 HTTP POST 到 neno-bridge
  - Brain 链路是 asyncio 协程，通过 proactive_intent 表与 proactive runner 解耦

### 真实发送链路
`runner.check_and_send_once()` → `rules.py 漏斗` → `send_executor._send_qq_candidate()`
→ `_post_neno_bridge_send_qq()` + `_save_proactive_context()`

### Brain 意图发送链路（Phase 3b 新增）
`brain.run_cycle()` → `proactive_intent 表` → `runner.consume_brain_intents()`
→ `rules.py 同一套漏斗` → `send_executor.send_brain_intent()`
→ `_post_neno_bridge_send_qq()` + `_save_proactive_context()`

### rules.py 漏斗函数
`hard_cooldown_active()` / `failure_pause_active()` / `within_active_window()` /
`today_sent_count()` / `has_recent_user_message()` / `evaluate_proactive_rules()`

### Phase 3 并发风险
无 asyncio↔threading 死锁风险。唯一并发场景是 brain 内部的 asyncio 打断（InterruptController），全程在同一事件循环内。
```
