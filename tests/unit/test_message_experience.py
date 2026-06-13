from __future__ import annotations

from pathlib import Path

from app.storage import db as db_storage
from app.services.consciousness.presence import (
    mark_message_experience_expressed,
    record_incoming_message_experience,
)


def _init_db(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir(exist_ok=True)
    db_storage.DB_DIR = d
    db_storage.DB_PATH = d / "bot.db"
    db_storage.init_db()


def _exp(eid):
    return db_storage.fetch_one(
        "SELECT kind, source, content, expression_status, related_message_ids "
        "FROM inner_experience_log WHERE id = ?",
        (eid,),
    )


def test_incoming_message_becomes_unspoken_experience(tmp_path: Path):
    _init_db(tmp_path)
    eid = record_incoming_message_experience("在吗 在干嘛", [11, 12], trace_id="t1")
    assert eid is not None
    row = _exp(eid)
    assert row["kind"] == "message"
    assert row["source"] == "user_message"
    assert "有人找我" in row["content"] and "在吗" in row["content"]
    assert row["expression_status"] == "unspoken"   # 还没回应 = 悬着
    assert "11" in row["related_message_ids"]         # 指回真实消息


def test_long_content_truncated(tmp_path: Path):
    _init_db(tmp_path)
    eid = record_incoming_message_experience("床" * 100, [1], trace_id="t1")
    row = _exp(eid)
    assert "…" in row["content"]
    assert len(row["content"]) < 90


def test_mark_expressed_flips_status(tmp_path: Path):
    _init_db(tmp_path)
    eid = record_incoming_message_experience("睡了吗", [5], trace_id="t1")
    assert _exp(eid)["expression_status"] == "unspoken"
    mark_message_experience_expressed(eid, trace_id="t1")
    assert _exp(eid)["expression_status"] == "expressed"   # 她回应了 = 已搭理


def test_mark_none_is_noop(tmp_path: Path):
    _init_db(tmp_path)
    mark_message_experience_expressed(None)  # 不该炸


def test_record_failure_returns_none_not_raise(tmp_path: Path):
    # 没 init_db（无表）→ 记经历失败应吞掉返回 None，绝不阻断聊天
    db_storage.DB_DIR = tmp_path / "nodir"
    db_storage.DB_PATH = (tmp_path / "nodir") / "bot.db"
    assert record_incoming_message_experience("x", [1], trace_id="t1") is None
