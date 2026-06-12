from __future__ import annotations

from app.config import SYSTEM_PROMPT
from app.services.chat.context_builder import build_chat_messages


def _cache_blocks(content):
    """返回 content(块列表)里带 cache_control 的块。"""
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict) and b.get("cache_control")]
    return []


def test_stable_prefix_and_history_are_cached():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "嗯"},
    ]
    msgs, _ = build_chat_messages(
        history=history,
        message="在吗",
        relationship_context="当前阶段：陌生",
        self_state_context="你此刻在客厅",
        history_digest="历史摘要片段",
    )

    # 系统消息：稳定前缀，最后一块带缓存断点
    system = msgs[0]
    assert system["role"] == "system"
    assert _cache_blocks(system["content"]), "系统稳定前缀应带缓存断点"
    sys_text = " ".join(b["text"] for b in system["content"])
    assert SYSTEM_PROMPT[:20] in sys_text and "历史摘要片段" in sys_text
    # 动态块不应出现在系统消息（否则打断历史缓存）
    assert "当前阶段" not in sys_text
    assert "在客厅" not in sys_text

    # 最后一条历史消息带缓存断点 → 缓存 [系统+全部历史]
    last_hist = msgs[-2]
    assert last_hist["role"] == "assistant"
    assert _cache_blocks(last_hist["content"]), "最后一条历史应带缓存断点"


def test_dynamic_context_rides_user_turn_uncached():
    msgs, _ = build_chat_messages(
        history=[{"role": "user", "content": "x"}],
        message="在吗",
        relationship_context="当前阶段：陌生",
        self_state_context="你此刻在客厅刷手机",
    )
    user = msgs[-1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    joined = " ".join(b["text"] for b in user["content"])
    assert "当前阶段" in joined          # 关系
    assert "在客厅刷手机" in joined       # self_state
    assert "在吗" in joined               # 用户原话
    # 动态上下文那块不应带缓存断点（每次变）
    assert not _cache_blocks(user["content"])


def test_no_dynamic_context_plain_user_string():
    msgs, _ = build_chat_messages(history=[], message="在吗")
    user = msgs[-1]
    assert user["role"] == "user"
    assert user["content"] == "在吗"  # 无动态上下文 → 纯字符串


def test_empty_history_no_crash_system_still_cached():
    msgs, _ = build_chat_messages(history=[], message="在吗", self_state_context="你在睡觉")
    assert msgs[0]["role"] == "system"
    assert _cache_blocks(msgs[0]["content"])
    # 没有历史 → 只有 system + user 两条
    assert [m["role"] for m in msgs] == ["system", "user"]
