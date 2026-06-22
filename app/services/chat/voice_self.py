"""声音自我：从她真实回过的话里结晶「她说话的样子」，喂回 prompt。

和自我库（subject="neno"）同构，但针对**声音/调性**——让她的风格从「她一直怎么说话」长出来，
不靠 system 写死的规则。存 `long_term_memory` subject="neno_voice"（只留最新一条 + 游标）。

铁律：任何失败静默跳过，绝不阻断聊天。默认关（CHAT_VOICE_SELF_ENABLED）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import (
    MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL,
    SELECTION_THINKING_OFF, SELECTION_TIMEOUT,
    VOICE_SELF_ENABLED, VOICE_SELF_MIN_NEW_REPLIES,
)
from app.llm.openrouter_client import chat_with_openrouter
from app.storage.db import execute_write, fetch_all, fetch_one
from app.utils.logging_utils import log_event

_VOICE_SUBJECT = "neno_voice"

_SYSTEM_PROMPT = """下面是她最近真实回过的一些话。请总结「她说话的样子」——
长短、口语程度、语气、习惯用词、什么时候话多 / 话少 / 冷淡。
2-3 句白描，给她自己照着保持一致。只描述风格，别复述内容、别评价好坏、别给建议。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_voice_context() -> str:
    """读最新「她说话的样子」（聊天 prompt 用，sync）。无 / 失败返 ""。"""
    try:
        row = fetch_one(
            "SELECT content FROM long_term_memory WHERE subject = ? ORDER BY id DESC LIMIT 1",
            (_VOICE_SUBJECT,),
        )
        return str(row["content"]).strip() if row else ""
    except Exception:  # noqa: BLE001
        return ""


def _last_cursor() -> int:
    """上次蒸馏到的最后一条 assistant 消息 id（存在 voice 行的 tags 里）。"""
    try:
        row = fetch_one(
            "SELECT tags FROM long_term_memory WHERE subject = ? ORDER BY id DESC LIMIT 1",
            (_VOICE_SUBJECT,),
        )
        if not row:
            return 0
        for t in json.loads(row["tags"] or "[]"):
            if isinstance(t, str) and t.startswith("cursor:"):
                return int(t.split(":", 1)[1])
    except Exception:  # noqa: BLE001
        pass
    return 0


def maybe_refresh_voice(trace_id: str | None = None) -> None:
    """攒够新回复就重新蒸馏一次「她说话的样子」。设计为后台 fire-and-forget 调用，别阻塞回复。"""
    if not VOICE_SELF_ENABLED or not MIMO_API_KEY:
        return
    try:
        rows = fetch_all(
            "SELECT id, content FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 25"
        )
        replies = [(r["id"], str(r["content"] or "").strip()) for r in (rows or [])]
        replies = [(i, c) for i, c in replies if c]
        if not replies:
            return
        newest_id = replies[0][0]
        if newest_id - _last_cursor() < VOICE_SELF_MIN_NEW_REPLIES:
            return  # 还没攒够新回复，不重蒸馏
        sample = "\n".join(f"- {c}" for _i, c in reversed(replies))
        raw = chat_with_openrouter(
            api_key=MIMO_API_KEY, url=MIMO_BASE_URL.rstrip("/") + "/chat/completions",
            model_name=MIMO_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": sample},
            ],
            timeout=SELECTION_TIMEOUT, trace_id=trace_id or "voice_self",
            extra_body=SELECTION_THINKING_OFF,
        )
        voice = str(raw or "").strip()
        if not voice:
            return
        execute_write(
            "INSERT INTO long_term_memory (content, tags, subject, salience, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (voice, json.dumps(["voice", f"cursor:{newest_id}"], ensure_ascii=False),
             _VOICE_SUBJECT, 0.5, _now_iso()),
        )
        # 只留最新一条，删旧的
        execute_write(
            "DELETE FROM long_term_memory WHERE subject = ? AND id < "
            "(SELECT MAX(id) FROM long_term_memory WHERE subject = ?)",
            (_VOICE_SUBJECT, _VOICE_SUBJECT),
        )
        log_event("chat", "voice_self_refreshed", trace_id=trace_id, based_on_msg_id=newest_id)
    except Exception as exc:  # noqa: BLE001 — 绝不阻断聊天
        log_event(
            "chat", "voice_self_warning", trace_id=trace_id, level="warning",
            error_type=type(exc).__name__, error_message=str(exc),
        )
