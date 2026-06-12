"""她在不在状态 —— 给主聊天用的同步入口（④：判断交给她自己，不是规则表）。

只保留一道**物理门**：她睡着 = 真没看见 → 攒着，不调 LLM（这不是判断，是她没意识）。
其余「要不要现在回、回得多上心」全交给对话 LLM 在她真实状态下临场决定：它要么自然地回，
要么只输出 `DEFER_MARKER`（暂不回）。没有 high/mid/low 桶、没有阈值表。

睡着时漏掉的消息攒进 life_world_state.pending_messages，等她醒来/缓过来由 world_loop 重新
让她考虑。`reconsider_after` 是冷却：她说了「暂不回」后，别每拍都拿 Opus 再问一遍。
"""
from __future__ import annotations

import json
import time

from app.storage import db as db_storage
from app.utils.logging_utils import log_event

from .world_store import WorldStore

# 她不想现在回时输出的标记（prompt 里告诉她可以这么做）
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
