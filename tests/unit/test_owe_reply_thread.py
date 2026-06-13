from __future__ import annotations

from app.services.consciousness.world_model import (
    find_thread,
    reconcile_owe_reply_thread,
)

_ID = "goal:还没回对方消息"


def _pending(age_sec, now=10_000.0):
    return {"session_id": "web:t", "received_at": now - age_sec}


def test_owed_too_long_awake_creates_thread():
    now = 10_000.0
    threads = reconcile_owe_reply_thread(
        [], [_pending(7200, now)], now=now, today="2026-06-13", threshold=3600.0, awake=True
    )
    t = find_thread(threads, _ID)
    assert t is not None
    assert t["kind"] == "goal" and t["topic"] == "还没回对方消息"
    assert t["carry_count"] >= 2  # 现成 self_state 过滤要 carry>=2 才冒出来
    assert not t["resolved"]


def test_fresh_pending_no_thread():
    now = 10_000.0
    threads = reconcile_owe_reply_thread(
        [], [_pending(60, now)], now=now, today="d", threshold=3600.0, awake=True
    )
    assert find_thread(threads, _ID) is None  # 刚发的不算欠太久


def test_asleep_does_not_nag():
    now = 10_000.0
    threads = reconcile_owe_reply_thread(
        [], [_pending(7200, now)], now=now, today="d", threshold=3600.0, awake=False
    )
    assert find_thread(threads, _ID) is None  # 睡着没意识，不挂


def test_cleared_resolves_thread():
    now = 10_000.0
    # 先有牵挂
    threads = reconcile_owe_reply_thread(
        [], [_pending(7200, now)], now=now, today="d", threshold=3600.0, awake=True
    )
    assert not find_thread(threads, _ID)["resolved"]
    # 欠的都回上了（pending 空）→ 了结
    threads = reconcile_owe_reply_thread(threads, [], now=now, today="d2", threshold=3600.0, awake=True)
    assert find_thread(threads, _ID)["resolved"] is True


def test_no_duplicate_on_repeat():
    now = 10_000.0
    threads = reconcile_owe_reply_thread(
        [], [_pending(7200, now)], now=now, today="d", threshold=3600.0, awake=True
    )
    threads = reconcile_owe_reply_thread(
        threads, [_pending(7300, now)], now=now, today="d2", threshold=3600.0, awake=True
    )
    owe = [t for t in threads if t["id"] == _ID]
    assert len(owe) == 1                       # 不重复建
    assert owe[0]["last_touch_day"] == "d2"     # 但刷新惦记时间
