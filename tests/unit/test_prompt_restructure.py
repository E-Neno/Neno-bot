from __future__ import annotations

from unittest.mock import patch

from app.services.relationship_service import (
    build_relationship_context_readonly,
    calculate_stage,
)
from app.services.time_context_service import build_time_context_message


def test_time_context_message_is_one_sentence():
    text = build_time_context_message(
        {
            "now_local": "2026-06-17 21:30",
            "weekday": "周三",
            "time_segment": "晚上",
            "gap_minutes": 3,
            "gap_text": "3分钟",
            "is_new_day": False,
        }
    )

    assert text == "现在晚上，刚聊过没多久。"
    assert "时间上下文：" not in text
    assert "当前本地时间" not in text
    assert "是否跨天" not in text
    assert "\n" not in text


def test_relationship_context_is_continuous_phrase_and_does_not_read_stage_file():
    states = [
        {
            "stage": 0,
            "conversation_count": 0,
            "familiarity_score": 0,
            "trust_score": 0,
            "emotional_depth_score": 0,
            "boundary_score": 0,
        },
        {
            "stage": 2,
            "conversation_count": 60,
            "familiarity_score": 40,
            "trust_score": 18,
            "emotional_depth_score": 12,
            "boundary_score": 8,
        },
        {
            "stage": 4,
            "conversation_count": 260,
            "familiarity_score": 180,
            "trust_score": 100,
            "emotional_depth_score": 80,
            "boundary_score": 40,
        },
    ]

    with patch("app.services.relationship_service.get_relationship_state", side_effect=states), patch(
        "pathlib.Path.read_text", side_effect=AssertionError("stage file should not be read")
    ):
        phrases = [build_relationship_context_readonly("s") for _ in states]

    assert len(set(phrases)) == 3
    assert all("你和对方" in phrase for phrase in phrases)
    assert all("conversation_count" not in phrase for phrase in phrases)
    assert all("分" not in phrase for phrase in phrases)
    behavior_words = ("别每次", "反问", "少客套", "不要提到关系阶段")
    assert all(not any(word in phrase for word in behavior_words) for phrase in phrases)


def test_relationship_stage_calculation_remains_unchanged():
    assert calculate_stage({"conversation_count": 0}) == 0
    assert calculate_stage({"conversation_count": 12, "familiarity_score": 8}) == 1
    assert calculate_stage({"conversation_count": 40, "familiarity_score": 25}) == 2
    assert calculate_stage(
        {
            "conversation_count": 120,
            "familiarity_score": 25,
            "trust_score": 25,
            "emotional_depth_score": 20,
        }
    ) == 3
