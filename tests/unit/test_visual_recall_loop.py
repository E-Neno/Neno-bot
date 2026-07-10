from unittest.mock import patch


def test_visual_recall_tag_is_not_persisted_as_assistant_reply(monkeypatch):
    import app.config as config
    from app.services.chat.turn_orchestrator import run_chat_turn

    monkeypatch.setattr(config, "VISUAL_RECALL_ENABLED", True, raising=False)
    # 单测隔离：中和统一判断层与在场门，否则会真打线上 MiMo（.env 选择层开着 + 真 key）、
    # 或读真实非隔离 DB 的精力判她「睡着」，两者都让 reply="" 使断言飘。视觉回想循环是本测试的
    # 被测对象，与选择层/在场门无关。
    monkeypatch.setattr(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False, raising=False
    )
    monkeypatch.setattr(
        "app.services.chat.turn_orchestrator.WORLD_PRESENCE_GATE_ENABLED", False, raising=False
    )
    contexts = {
        "history": [],
        "relationship_context": "你和对方还没太熟。",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "【对方刚说】\n上次那张图呢"}]}],
        "used_memories": [],
        "memory_context": {},
        "time_context": {},
        "history_digest": "",
        "self_state_context": "【此刻的你】\n你叫 Neno，18 岁。",
    }
    saved_messages = []
    reply_calls = {"count": 0}

    def fake_add_message(session_id, role, content, **kwargs):
        saved_messages.append({"role": role, "content": content})
        return len(saved_messages)

    def fake_generate_chat_reply(messages, trace_id=None):
        reply_calls["count"] += 1
        if reply_calls["count"] == 1:
            return '<visual_recall>{"query":"上次那张报错截图","question":"核心报错是什么"}</visual_recall>'
        assert any(
            block.get("text", "").startswith("【视觉回想】")
            for block in messages[-1]["content"]
            if isinstance(block, dict)
        )
        return "核心是 Gradle task failed。"

    with patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts",
        return_value=contexts,
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
        return_value={
            "candidate_memory": None,
            "candidate_memory_debug": None,
            "candidate_memory_decision": {"action": "ignore"},
            "auto_added_memory": False,
        },
    ), patch(
        "app.services.chat.turn_orchestrator.build_chat_messages_preview_from_contexts",
        return_value={},
    ), patch(
        "app.services.chat.turn_orchestrator.add_message",
        side_effect=fake_add_message,
    ), patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience",
        return_value=33,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        side_effect=fake_generate_chat_reply,
    ), patch(
        "app.services.chat.turn_orchestrator.search_visual_memory",
        return_value={"candidates": [{"asset_uid": "vimg_123"}]},
    ) as search, patch(
        "app.services.chat.turn_orchestrator.inspect_visual_asset",
        return_value={"asset_uid": "vimg_123", "observation": "核心报错是 Gradle task failed"},
    ) as inspect, patch(
        "app.services.chat.turn_orchestrator.mark_message_experience_expressed"
    ), patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update",
        return_value={"stage": 0},
    ):
        result = run_chat_turn("s", "上次那张图呢", trace_id="trace-recall")

    assert result["reply"] == "核心是 Gradle task failed。"
    assert saved_messages[-1] == {"role": "assistant", "content": "核心是 Gradle task failed。"}
    assert "<visual_recall>" not in str(saved_messages)
    search.assert_called_once()
    inspect.assert_called_once_with("vimg_123", question="核心报错是什么", trace_id="trace-recall")
