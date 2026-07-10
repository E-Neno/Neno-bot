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


def test_no_dynamic_context_message_block_only():
    msgs, _ = build_chat_messages(history=[], message="在吗")
    user = msgs[-1]
    assert user["role"] == "user"
    # 无动态上下文 → 块列表里只剩「对方刚说」一块，不带缓存断点
    assert isinstance(user["content"], list)
    assert len(user["content"]) == 1
    assert user["content"][0]["text"] == "【对方刚说】\n在吗"
    assert not _cache_blocks(user["content"])


def test_current_turn_image_blocks_follow_last_user_text_and_never_enter_history():
    msgs, _ = build_chat_messages(
        history=[
            {"role": "user", "content": "旧图片的文本投影 visual_asset_id: vimg_old"},
            {"role": "assistant", "content": "我看到了"},
        ],
        message="[用户发送了一张图片]\n用户附带文字：看这个",
        current_turn_image_inputs=["data:image/png;base64,abc"],
    )

    history_text = str(msgs[1]["content"]) + str(msgs[2]["content"])
    user_blocks = msgs[-1]["content"]

    assert "image_url" not in history_text
    assert user_blocks[-2]["type"] == "text"
    assert user_blocks[-2]["text"].startswith("【对方刚说】")
    assert user_blocks[-1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,abc"},
    }
    assert not _cache_blocks(user_blocks)


def test_history_messages_include_frozen_world_time():
    msgs, _ = build_chat_messages(
        history=[
            {
                "role": "user",
                "content": "last night",
                "metadata": {
                    "world_time": {
                        "display_date": "2026-06-26",
                        "display_time": "23:41",
                    }
                },
            },
        ],
        message="continue",
    )

    content = msgs[1]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "【当时世界日期】2026-06-26\n【当时世界时间】23:41\nlast night"


def test_history_messages_keep_legacy_world_time_without_date():
    msgs, _ = build_chat_messages(
        history=[
            {
                "role": "user",
                "content": "old row",
                "metadata": {"world_time": {"display_time": "08:56"}},
            },
        ],
        message="continue",
    )

    content = msgs[1]["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "【当时世界时间】08:56\nold row"


def test_empty_history_no_crash_system_still_cached():
    msgs, _ = build_chat_messages(history=[], message="在吗", self_state_context="你在睡觉")
    assert msgs[0]["role"] == "system"
    assert _cache_blocks(msgs[0]["content"])
    # 没有历史 → 只有 system + user 两条
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_dynamic_context_is_labeled_blocks_and_not_cached():
    history = [
        {"role": "user", "content": "上一句"},
        {"role": "assistant", "content": "上一句回复"},
    ]
    time_context = {
        "now_local": "2026-06-17 21:30",
        "weekday": "周三",
        "time_segment": "晚上",
        "gap_minutes": 3,
        "gap_text": "3分钟",
        "is_new_day": False,
    }

    msgs, _ = build_chat_messages(
        history=history,
        message="在吗",
        relationship_context="你和对方处得算熟了，像常聊的朋友。",
        time_context=time_context,
        self_state_context="【此刻的你】\n你叫 Neno，18 岁。\n你在客厅画画。",
        history_digest="历史摘要片段",
    )

    dynamic_needles = [
        "你叫 Neno",
        "你在客厅画画",
        "你和对方处得算熟了",
        "现在晚上",
    ]
    system_text = " ".join(b["text"] for b in msgs[0]["content"])
    history_text = " ".join(
        block.get("text", "")
        for msg in msgs[1:-1]
        for block in (msg["content"] if isinstance(msg["content"], list) else [{"text": msg["content"]}])
    )
    user_text = "\n".join(block["text"] for block in msgs[-1]["content"])

    user_blocks = msgs[-1]["content"]
    assert msgs[-1]["role"] == "user"
    # 动态区拆成多个带标签的块（不再「当前情境」大壳）；第一块是此刻的你、最后一块永远是对方刚说
    assert user_blocks[0]["text"].startswith("【此刻的你】")
    assert user_blocks[-1]["text"].startswith("【对方刚说】")
    assert len(user_blocks) >= 3  # 此刻的你 / 你和对方 / 此刻 / 对方刚说 …多块
    for needle in dynamic_needles:
        assert needle in user_text
        assert needle not in system_text       # 缓存不变量：动态内容不漏进 system 前缀
        assert needle not in history_text       # 也不漏进历史
    assert not _cache_blocks(user_blocks)       # 动态块一律不带缓存断点
    assert "时间上下文：" not in user_text
    assert "当前本地时间" not in user_text
    assert "是否跨天" not in user_text
