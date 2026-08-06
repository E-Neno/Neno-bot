"""物理在场门与 pending 存取。

只保留一道**物理门**：她睡着 = 真没看见 → 攒着，不调 LLM（这不是判断，是她没意识）。
其余「要不要现在回、回得多上心」由聊天 Executive 输出结构化 action 决定，没有 high/mid/low 桶。
`DEFER_MARKER` / `is_defer_reply` 仅为旧接口兼容，当前聊天主链不再生成或消费特殊字符串。

睡着时漏掉的消息攒进 life_world_state.pending_messages，等她醒来/缓过来由 world_loop 重新
让她考虑。`reconsider_after` 是冷却：她说了「暂不回」后，别每拍都拿 Opus 再问一遍。
"""
from __future__ import annotations

import json
import time

from app.storage import db as db_storage
from app.utils.logging_utils import log_event

from .experience_recorder import ExperienceRecorder, InnerExperienceIn
from .world_store import WorldStore

_recorder = ExperienceRecorder()

# 旧接口兼容：当前聊天 prompt 不再要求模型输出该标记。
DEFER_MARKER = "[暂不回]"
# 她「暂不回」后，多久才让 world_loop 拿 Opus 再问一次（秒，真实时间）
DEFER_COOLDOWN_SECONDS = 180.0


def is_physically_asleep(trace_id: str | None = None) -> bool:
    """她此刻是不是睡着（物理事实，唯一的硬门）。读不到状态按醒着处理。"""
    try:
        row = db_storage.fetch_one(
            "SELECT state_json FROM agent_state WHERE id = 1 LIMIT 1"
        )
        if not row:
            return False
        astate = json.loads(row["state_json"])
        return str((astate.get("energy", {}) or {}).get("status", "awake")) == "sleeping"
    except Exception as exc:  # noqa: BLE001 — 出错绝不阻断聊天，按醒着处理
        log_event("chat", "presence_asleep_check_warning", trace_id=trace_id,
                  error_type=type(exc).__name__, error_message=str(exc))
        return False


def is_defer_reply(reply: str | None) -> bool:
    """对话 LLM 这次是不是选择了「暂不回」。容忍少量噪声/标点。"""
    if not reply:
        return False
    r = reply.strip()
    return DEFER_MARKER in r and len(r.replace(DEFER_MARKER, "").strip()) < 8


def record_incoming_message_experience(
    content: str, user_message_ids: list[int], trace_id: str | None = None,
) -> int | None:
    """消息进世界：把「有人找我」记成她活过的一刻经历（不进压力泵，纯经历流）。

    expression_status='unspoken' = 一段她还没回应的经历，悬着；她回了再翻成 expressed。
    同步一行 insert，所有分支(睡着/回/不回)都记——这事确实发生在她生命里了。
    """
    try:
        text = str(content or "").strip().replace("\n", " ")
        if len(text) > 60:
            text = text[:60] + "…"
        return _recorder._record_sync(InnerExperienceIn(
            trace_id=trace_id or "msg", source="user_message", kind="message",
            content=f"有人找我，说了「{text}」",
            related_message_ids=[int(i) for i in (user_message_ids or [])],
            expression_status="unspoken", salience=0.5,
        ))
    except Exception as exc:  # noqa: BLE001 — 记经历失败绝不阻断聊天
        log_event("chat", "msg_experience_record_warning", trace_id=trace_id,
                  error_type=type(exc).__name__, error_message=str(exc))
        return None


def mark_message_experience_expressed(experience_id: int | None,
                                      trace_id: str | None = None) -> None:
    """她回应了这条消息 → 把那段经历从 unspoken 翻成 expressed（已搭理）。"""
    if experience_id is None:
        return
    try:
        _recorder._mark_expression_status_sync(int(experience_id), "expressed", None)
    except Exception as exc:  # noqa: BLE001
        log_event("chat", "msg_experience_mark_warning", trace_id=trace_id,
                  error_type=type(exc).__name__, error_message=str(exc))


def stash_pending_message(entry: dict, *, cooldown: float = 0.0,
                          trace_id: str | None = None) -> None:
    """把一条「现在没回」的消息攒进世界状态，等她缓过来/醒来再考虑。

    cooldown>0（她主动说暂不回）→ 设 reconsider_after，避免每拍重复打扰 Opus。
    cooldown=0（睡着没看见）→ 醒了就立刻重新考虑。

    并发取舍：pending 骑现有单行世界 JSON，聊天侧(同步)与 world_loop(异步)都会写整行，
    本地单用户、消息稀疏，覆盖窗口很小；真要硬化再把写入路由进单写者队列或独立表。
    """
    try:
        store = WorldStore()
        ws = store._read_sync()
        pending = list(ws.pending_messages or [])
        entry = dict(entry)
        now = time.time()
        entry.setdefault("received_at", now)
        entry.setdefault("received_sim_min", ws.sim_minutes)
        entry["reconsider_after"] = now + cooldown if cooldown > 0 else 0.0
        pending.append(entry)
        ws.pending_messages = pending[-20:]  # 上限兜底，别无限攒
        store._write_sync(ws)
    except Exception as exc:  # noqa: BLE001
        log_event("chat", "presence_stash_warning", trace_id=trace_id,
                  error_type=type(exc).__name__, error_message=str(exc))
