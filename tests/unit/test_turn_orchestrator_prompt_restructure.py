from __future__ import annotations

from unittest.mock import patch

from app.services.chat.selection_layer import fallback_decision


def test_awake_chat_no_longer_consumes_defer_marker():
    from app.services.chat.turn_orchestrator import run_chat_turn
    from app.services.consciousness.presence import DEFER_MARKER

    contexts = {
        "history": [],
        "relationship_context": "你和对方还没太熟。",
        "messages": [{"role": "user", "content": "在吗"}],
        "used_memories": [],
        "memory_context": {},
        "time_context": {},
        "history_digest": "",
        "self_state_context": "【此刻的你】\n你叫 Neno，18 岁。",
    }

    with patch(
        "app.services.chat.turn_orchestrator.WORLD_PRESENCE_GATE_ENABLED", True
    ), patch(
        "app.services.chat.turn_orchestrator.is_physically_asleep", return_value=False
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts", return_value=contexts
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
        "app.services.chat.turn_orchestrator.add_message", side_effect=[101, 202]
    ) as add_message, patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience",
        return_value=303,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        return_value=DEFER_MARKER,
    ), patch(
        "app.services.chat.turn_orchestrator.select_response_sync",
        side_effect=lambda messages, *args, **kwargs: fallback_decision(messages),
    ), patch(
        "app.services.chat.turn_orchestrator.stash_pending_message"
    ) as stash, patch(
        "app.services.chat.turn_orchestrator.mark_message_experience_expressed"
    ) as mark, patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update",
        return_value={"stage": 0},
    ):
        result = run_chat_turn("s", "在吗", trace_id="t")

    assert result["reply"] == DEFER_MARKER
    assert result["world_action"] == "reply_now"
    assert result["assistant_message_id"] == 202
    assert add_message.call_count == 2
    stash.assert_not_called()
    mark.assert_called_once_with(303, trace_id="t")
