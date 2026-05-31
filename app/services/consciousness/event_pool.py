"""Event pool — dual-layer topic_hash dedup, priority dequeue, topic decay, 24h expiry."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import pydantic

from app.storage.db import fetch_all, fetch_one, get_conn

from .config import ConsciousnessConfig

logger = logging.getLogger(__name__)

STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "这个", "那个", "还", "而", "被", "让", "给", "吧",
    "啊", "呢", "吗", "哦", "嗯", "哈", "呀", "哇", "嘛",
}


class EventIn(pydantic.BaseModel):
    topic_hash: str
    priority: int  # 0=P0, 1=P1, 2=P2, 3=P3
    content: str
    tags: list[str] = pydantic.Field(default_factory=list)
    mood_impact: float = 0.0
    source: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _extract_keywords(text: str) -> list[str]:
    """Extract Chinese keywords from text by splitting on stopwords/punctuation."""
    cleaned = re.sub(r"[，,。！!？?、；;：:\s]+", " ", text)
    words = cleaned.split()
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


class EventPool:
    """事件池管理：入池、去重、话题衰减、优先级查询。所有持久化走 event_log 表。"""

    def __init__(self, db, config: ConsciousnessConfig) -> None:
        self._db = db
        self._cfg = config

    # ── topic_hash generation ──────────────────────────────

    @staticmethod
    def make_hash_structured(event_type: str, date_str: str) -> str:
        return f"{event_type}_{date_str}"

    @staticmethod
    def make_hash_unstructured(content: str) -> str:
        keywords = _extract_keywords(content)
        if not keywords:
            key_text = content[:20]
        else:
            key_text = "".join(sorted(set(keywords)))
        digest = hashlib.md5(key_text.encode("utf-8")).hexdigest()[:8]
        tag = "hot" if any(kw in content for kw in ("热搜", "热榜")) else "misc"
        return f"{tag}_{digest}"

    # ── push ───────────────────────────────────────────────

    async def push(self, event: EventIn) -> bool:
        now = _utcnow()
        today = now.strftime("%Y-%m-%d")

        # Check 1: same topic_hash today (pending or consumed)
        existing = fetch_one(
            """SELECT id FROM event_log
               WHERE topic_hash = ? AND status IN ('pending','consumed')
                 AND created_at >= ?
               LIMIT 1""",
            (event.topic_hash, today),
        )
        if existing is not None:
            logger.debug("event deduped by topic_hash: %s", event.topic_hash)
            return False

        # Check 2: expressed topic cooldown
        expressed = fetch_one(
            """SELECT id FROM event_log
               WHERE topic_hash = ? AND status = 'expressed'
                 AND created_at >= ?
               LIMIT 1""",
            (event.topic_hash, today),
        )
        if expressed is not None:
            logger.debug("event rejected by topic cooldown: %s", event.topic_hash)
            return False

        # Insert
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO event_log (topic_hash, priority, content, tags, mood_impact, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    event.topic_hash,
                    event.priority,
                    event.content,
                    json.dumps(event.tags, ensure_ascii=False),
                    event.mood_impact,
                    now.isoformat(),
                ),
            )
        logger.debug("event pushed: %s (pri=%d)", event.topic_hash, event.priority)
        return True

    # ── pop ────────────────────────────────────────────────

    async def pop_pending(self, priority_le: int = 2) -> list[EventIn]:
        now = _utcnow().isoformat()
        rows = fetch_all(
            """SELECT topic_hash, priority, content, tags, mood_impact
               FROM event_log
               WHERE status = 'pending' AND priority <= ?
               ORDER BY priority ASC, created_at ASC
               LIMIT 10""",
            (priority_le,),
        )
        result: list[EventIn] = []
        for row in rows:
            result.append(EventIn(
                topic_hash=row["topic_hash"],
                priority=int(row["priority"]),
                content=row["content"],
                tags=json.loads(row["tags"]) if row["tags"] else [],
                mood_impact=float(row["mood_impact"]),
            ))
        if result:
            hashes = [e.topic_hash for e in result]
            placeholders = ",".join("?" for _ in hashes)
            with get_conn() as conn:
                conn.execute(
                    f"UPDATE event_log SET status = 'consumed' WHERE topic_hash IN ({placeholders})",
                    hashes,
                )
        return result

    # ── expressed topic tracking ───────────────────────────

    async def mark_topic_expressed(self, topic_hash: str) -> None:
        now = _utcnow().isoformat()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO event_log (topic_hash, priority, content, tags, mood_impact, status, created_at)
                   VALUES (?, 3, '', '[]', 0.0, 'expressed', ?)""",
                (topic_hash, now),
            )

    # ── expire ─────────────────────────────────────────────

    async def expire_old_events(self) -> int:
        cutoff = (_utcnow() - timedelta(hours=24)).isoformat()
        with get_conn() as conn:
            cursor = conn.execute(
                "UPDATE event_log SET status = 'expired' WHERE status = 'pending' AND created_at < ?",
                (cutoff,),
            )
            count = cursor.rowcount
        return count
