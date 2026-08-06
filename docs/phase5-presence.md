# Phase 5：对话↔世界（在场模型 Presence）

> **2026-07-10 更新（统一主脑）**：物理睡眠仍是唯一硬门；醒着后的 `reply_now / defer / leave_unanswered`
> 由主聊天 Executive 输出结构化决策。`DEFER_MARKER` 仍仅作兼容常量，当前主链不生成或消费它。
> pending 冷却到期表示“重新考虑”，不会绕过主脑强制回复。最新实现以 `docs/living-world.md` §5d 为准；
> 本文下方基于 `[暂不回]` 特殊字符串的流程只保留为历史记录。

> **2026-06-16 更新（刀① prompt 重构）**：`[暂不回]`（`DEFER_MARKER`）已从聊天 prompt 移除，醒着聊天路径不再消费它——
> 「醒着但不想回」的内容感知判断作废，**presence 现仅剩物理睡眠门**（睡着→攒 `pending_messages`、零 LLM）。
> `DEFER_MARKER`/`is_defer_reply` 常量在 `presence.py` 保留未删但不再注入/消费。本文下方含 DEFER 注入的描述为历史记录，以此条为准。详见 `docs/living-world.md` §5b。
>
> 取代已废弃的 `PHASE_5_IMPL_PLAN.md`（codex 的 WorldIngressGateway 规则表方案，
> 用户判定「太生硬」作废）。
>
> **核心（④ 最终形态）：「要不要回 / 何时回 / 回得怎样」不是规则表，是她自己临场拿捏。**
> 只剩一道物理门（睡着=没意识），其余全交给对话 LLM 在她真实状态下决定——它要么自然地回，
> 要么选择这次不回。判断这一下是真·LLM 在做（非确定、每次可能不一样），不是 if-else。

## 模型（一句话）

消息进来 →

1. **物理门（唯一硬规则）**：她睡着 = 真没看见 → 攒进 pending，**零 LLM**。醒来再面对。
2. **醒着 → 她对话脑一口气决定**：把她真实状态（在哪、在干嘛、精力、心情、牵挂）注入 prompt，
   她**要么自然地回**（敷衍/迟疑/上心/迷糊全由她自己掌握），**要么只输出 `[暂不回]`** 表示
   这会儿不想搭理。没有 high/mid/low 桶、没有阈值表。
3. **节流**：她说「暂不回」后给冷却（`DEFER_COOLDOWN_SECONDS`，默认 180s），别每拍拿 Opus 再问；
   睡着漏的消息醒了立刻重新面对。

「质感」（groggy/curt/distracted）不再由代码分档喂给她——她读到自己真实状态后**自己拿捏**，
这正是干掉「脚本感」的关键：分寸是她的，不是我写死的桶。

## 落地与状态

- **✅ 已做（含 ④ 重构）**：
  - `presence.py`：物理门 `is_physically_asleep()`、`[暂不回]` 标记 `DEFER_MARKER` + 识别
    `is_defer_reply()`、`stash_pending_message(cooldown=…)`（pending 骑 `life_world_state` 单行 JSON）。
  - `self_state_context.py`：注入她真实状态 + 「你可以这次不回」的指令（门控开时）。
  - `turn_orchestrator.run_chat_turn`：睡着→物理门攒着零 LLM；醒着→生成后若 `[暂不回]`→攒着不发。
    `run_chat_turn_from_persisted_user_messages`：醒来/冷却到期重新面对，仍不回则回滚再攒。
  - `world_loop._consume_pending`：醒着 + 冷却到期才让她重新面对；先认领防双发；她仍不回则带冷却重攒。
  - WX 平台投递：平台来源回复经 `send_world_expression`（proactive 链路）推回；web 只写 session。
  - 开关 `WORLD_PRESENCE_GATE_ENABLED`（默认关）、`WORLD_PRESENCE_WX_AUTO_SEND`（默认 dry_run）。
  - 验收脚本 `tmp/verify_presence_gate.py`（三场景：睡着零LLM门 / 醒来重新面对 / 临场选择不回带冷却）。
  - **规则表已删**：旧的 `availability.py`（decide_disposition + 沉浸度桶）整个移除——判断交还给她。
- **缓存重构（顺带）**：动态上下文（时间/关系/记忆/self_state）从 system 前缀挪到用户消息那头，
  历史段打缓存断点，让 Claude 能缓存 `[系统+历史]` 大头（之前一直不命中的根因是动态块堵在历史前）。
  见 `context_builder.build_chat_messages` + `tests/unit/test_chat_cache_structure.py`。
- **slice「真忘了」（计划，见下）**：仍是未来项。

> slice 3「质感」已被 ④ 吸收——不再用代码分档喂语气，她自己拿捏，无需单独一刀。

---

## 计划：真忘了（pending 衰减丢弃）

**目标**：漏掉的消息搁太久 + 她一直没空/没意愿 → 少数会**真的忘了**，永不回。让「不回」这种
结局完整（不是所有消息最终都必回）。

**改动**：
1. pending entry 已有 `received_at`(真实秒)、`reconsider_after`(冷却)。`_consume_pending` 每拍先做
   **过期清理**：`age = now - received_at` 超过 `WORLD_PENDING_FORGET_SECONDS`（默认如 6h）→ 丢弃。
   - 更像人：age 越长丢弃概率越高（而非硬阈值）；用关系分/salience 抬高「重要的人」留存。
2. 丢弃留痕：写一条低 salience inner experience（kind=missed_message），让她事后「想起来愧疚」
   有据可依（未来可接主动道歉）。
3. 不真删用户消息（仍在 messages 表/历史），只是 pending 不再产出回复。

**测试**：`received_at` 设到很久以前 → tick → pending 被清、写了 missed_message experience、无 assistant。

**边界**：默认关或保守阈值（别让她随便忘事惹用户）；「要不要忘」纯函数化便于测。

---

## 红线状态（需后续同步）

- `PHASE_5_IMPL_PLAN.md` 已作废（建议同 `PHASE_4.md`：顶部标注禁止再据此实现）。
- 「不得把世界状态注入主聊天 prompt」红线已由 `self_state` 注入 + 本在场模型**有意打破**
  （用户 owner 授权）。涉及文件：`CLAUDE.md`、`NENO.md`、`AGENTS.md`、`NENO_ARCHITECTURE.md`、
  `docs/living-world.md`、`PHASE_4_LIVING_WORLD_SPEC.md`。需改成「经 `self_state_context` /
  `presence` 受控注入，默认开关可关」的新约定。
