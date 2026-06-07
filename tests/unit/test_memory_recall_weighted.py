from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.storage import db as db_storage
from app.services.consciousness.memory_recall import MemoryRecall
from app.services.consciousness.config import ConsciousnessConfig


def _init_test_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def _insert_memory(content: str, *, salience: float, created_at: str, tags: str = "[]"):
    db_storage.execute_write(
        "INSERT INTO long_term_memory (content, tags, subject, salience, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (content, tags, "", salience, created_at),
    )


def _recall(tmp_path: Path) -> MemoryRecall:
    _init_test_db(tmp_path)
    return MemoryRecall(db=None, config=ConsciousnessConfig(memory_recall_top_k=5))


def test_weighted_prefers_recent_among_relevant(tmp_path: Path):
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    rec = _recall(tmp_path)
    _insert_memory("上周读到一段关于孤独的文字", salience=0.6,
                   created_at=(now - timedelta(hours=48)).isoformat())   # A 相关但旧
    _insert_memory("今天又想起那本孤独的书", salience=0.6,
                   created_at=(now - timedelta(hours=1)).isoformat())    # B 相关且新
    _insert_memory("天气预报说明天下雨", salience=0.9,
                   created_at=(now - timedelta(hours=1)).isoformat())    # C 不相关

    out = asyncio.run(rec.recall_weighted("孤独", now=now))
    contents = [r["content"] for r in out]
    assert contents, "should recall relevant memories"
    assert "今天又想起那本孤独的书" in contents[0]      # 新的相关记忆排第一
    assert any("上周读到" in c for c in contents)        # 旧的相关也召回
    assert all("天气预报" not in c for c in contents)    # 不相关不召回


def test_weighted_empty_query_returns_empty(tmp_path: Path):
    rec = _recall(tmp_path)
    _insert_memory("随便一条", salience=0.5,
                   created_at=datetime.now(timezone.utc).isoformat())
    out = asyncio.run(rec.recall_weighted("", now=datetime.now(timezone.utc)))
    assert out == []


def test_weighted_returns_score_and_created_at(tmp_path: Path):
    now = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)
    rec = _recall(tmp_path)
    _insert_memory("关于读书的记忆", salience=0.7,
                   created_at=(now - timedelta(hours=2)).isoformat())
    out = asyncio.run(rec.recall_weighted("读书", now=now))
    assert out and "score" in out[0] and "created_at" in out[0]
    assert isinstance(out[0]["score"], float)
