from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

from app.services.chat.selection_layer import fallback_decision
from app.services.chat.selection_layer import SelectionDecision
from app.services.chat.inner_deliberation import InnerImpulse
from app.services.chat.chat_executive import ExecutiveDecision


def _init_test_db(tmp_path: Path) -> None:
    import app.storage.db as db_storage

    data_dir = tmp_path / "data"
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


def test_executive_output_failure_falls_back_to_legacy_prompt():
    from app.services.chat.turn_orchestrator import _generate_chat_reply_with_fallback

    isolated = [{"role": "user", "content": "isolated"}]
    legacy = [{"role": "user", "content": "legacy"}]
    with patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        side_effect=[RuntimeError("output failed"), "fallback reply"],
    ) as generate:
        reply = _generate_chat_reply_with_fallback(
            isolated,
            fallback_messages=legacy,
            trace_id="trace-output-fallback",
        )

    assert reply == "fallback reply"
    assert generate.call_args_list[0].args[0] is isolated
    assert generate.call_args_list[1].args[0] is legacy


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


def test_visual_assets_are_resolved_before_context_building():
    from app.services.chat.turn_orchestrator import run_chat_turn

    contexts = {
        "history": [],
        "relationship_context": "你和对方还没太熟。",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "【对方刚说】\n看图"}]}],
        "used_memories": [],
        "memory_context": {},
        "time_context": {},
        "history_digest": "",
        "self_state_context": "【此刻的你】\n你叫 Neno，18 岁。",
    }
    captured_kwargs = {}

    def fake_load_chat_contexts(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return contexts

    with patch(
        # 单测隔离：关掉统一判断层，否则命中线上 MiMo（.env 选择层开着 + 真 key）使断言飘。
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.resolve_current_turn_image_inputs",
        return_value=["data:image/png;base64,abc"],
    ) as resolver, patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts",
        side_effect=fake_load_chat_contexts,
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
        "app.services.chat.turn_orchestrator.add_message", side_effect=[11, 22]
    ), patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience",
        return_value=33,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        return_value="看到了",
    ), patch(
        "app.services.chat.turn_orchestrator.mark_message_experience_expressed"
    ), patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update",
        return_value={"stage": 0},
    ):
        run_chat_turn(
            "s",
            "看图",
            trace_id="t",
            input_record={"message_type": "image", "visual_assets": [{"asset_uid": "vimg_x"}]},
        )

    resolver.assert_called_once()
    assert captured_kwargs["current_turn_image_inputs"] == ["data:image/png;base64,abc"]


def test_visual_asset_links_are_written_after_user_message_persist(tmp_path: Path):
    import app.storage.db as db_storage
    from app.schemas import MediaAttachment
    from app.services.chat.turn_orchestrator import run_chat_turn
    from app.services.visual_asset_store import VisualAssetStore

    _init_test_db(tmp_path)
    image = tmp_path / "screen.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (2).to_bytes(4, "big")
        + (2).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    asset = VisualAssetStore(root=tmp_path / "data" / "visual_assets", base_dir=tmp_path).archive_image_attachment(
        MediaAttachment(kind="image", media_path=str(image), mime_type="image/png"),
        session_id="s",
        trace_id="trace-link-write",
    )
    contexts = {
        "history": [],
        "relationship_context": "你和对方还没太熟。",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "【对方刚说】\n看图"}]}],
        "used_memories": [],
        "memory_context": {},
        "time_context": {},
        "history_digest": "",
        "self_state_context": "【此刻的你】\n你叫 Neno，18 岁。",
    }

    with patch(
        # 单测隔离：关掉统一判断层，否则命中线上 MiMo（.env 选择层开着 + 真 key），
        # LLM 判「不回」时 reply="" 且链接不落库，使断言飘。本测试只验资产链接落库。
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.resolve_current_turn_image_inputs",
        return_value=["data:image/png;base64,abc"],
    ), patch(
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
        "app.services.chat.turn_orchestrator.record_incoming_message_experience",
        return_value=33,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        return_value="看到了",
    ), patch(
        "app.services.chat.turn_orchestrator.mark_message_experience_expressed"
    ), patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update",
        return_value={"stage": 0},
    ):
        result = run_chat_turn(
            "s",
            "看图",
            trace_id="trace-link-write",
            input_record={"message_type": "image", "visual_assets": [asset.to_attachment_metadata()]},
        )

    rows = db_storage.fetch_all(
        "SELECT message_id, relation FROM visual_asset_links ORDER BY relation"
    )
    assert {(row["message_id"], row["relation"]) for row in rows} == {
        (result["user_message_id"], "current_turn_viewed"),
        (result["user_message_id"], "user_sent"),
    }


def _executive_test_contexts():
    return {
        "history": [{"id": 88, "role": "assistant", "content": "你慢慢说，我在。"}],
        "relationship_context": "已经很熟",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "【对方刚说】\n我今天被裁了"}]}],
        "used_memories": [],
        "memory_context": {},
        "time_context": {},
        "history_digest": "",
        "self_state_context": "【此刻的你】\n你在客厅，有点累。",
        "voice_context": "嗯，先缓一下。",
        "past_events": "",
    }


def test_main_executive_can_override_triage_silence_and_reply():
    from app.services.chat.turn_orchestrator import run_chat_turn

    triage = SelectionDecision(
        focus=[101], ignore=[], hooked_by=101, reply_strategy="single",
        should_respond=False, depth="deep", emotion_hit=True,
        emotion_tone="心里一沉", emotion_intensity=0.9,
    )
    executive = ExecutiveDecision(
        action="reply_now", reason="应该接住", response_points=["先问他现在怎么样"],
        max_chars=40, max_beats=1, inner_reaction="有点担心",
        world_intents=["晚点出门走走，消化一下这件事"],
    )
    isolated_messages = [{"role": "user", "content": "isolated output prompt"}]

    with patch(
        "app.services.chat.turn_orchestrator.EXECUTIVE_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.MULTILAYER_THINKING_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.MIMO_API_KEY", "key",
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts",
        return_value=_executive_test_contexts(),
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
        return_value={
            "candidate_memory": None, "candidate_memory_debug": None,
            "candidate_memory_decision": {"action": "ignore"}, "auto_added_memory": False,
        },
    ), patch(
        "app.services.chat.turn_orchestrator.build_chat_messages_preview_from_contexts", return_value={},
    ), patch(
        "app.services.chat.turn_orchestrator.add_message", side_effect=[101, 202],
    ), patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience", return_value=303,
    ), patch(
        "app.services.chat.turn_orchestrator.select_response_sync", return_value=triage,
    ), patch(
        "app.services.chat.turn_orchestrator.deliberate_sync",
        return_value=[InnerImpulse("approach", "想接住", "先听他说", 0.8)],
    ) as deliberate, patch(
        "app.services.chat.turn_orchestrator.decide_chat_turn_sync", return_value=executive,
    ) as decide, patch(
        "app.services.chat.turn_orchestrator.record_executive_decision",
    ) as persist_decision, patch(
        "app.services.chat.turn_orchestrator.build_executive_output_messages",
        return_value=isolated_messages,
    ) as build_output, patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply", return_value="你现在还好吗？",
    ) as generate, patch(
        "app.services.chat.turn_orchestrator.stash_pending_message",
    ) as stash, patch(
        "app.services.chat.turn_orchestrator.mark_message_experience_expressed",
    ), patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update", return_value={"stage": 2},
    ):
        result = run_chat_turn("s", "我今天被裁了", trace_id="trace-exec-reply")

    assert result["reply"] == "你现在还好吗？"
    assert result["world_action"] == "reply_now"
    deliberate.assert_called_once()
    decide.assert_called_once()
    assert "你慢慢说，我在。" in decide.call_args.kwargs["state"]["recent_dialogue"]
    assert persist_decision.call_args.kwargs["world_intents"] == [
        "晚点出门走走，消化一下这件事"
    ]
    build_output.assert_called_once()
    generate.assert_called_once_with(isolated_messages, trace_id="trace-exec-reply")
    stash.assert_not_called()


def test_main_executive_defer_stashes_without_calling_output_model():
    from app.services.chat.turn_orchestrator import run_chat_turn

    executive = ExecutiveDecision(
        action="defer", reason="现在确实不想硬回", response_points=[],
        max_chars=0, max_beats=1, inner_reaction="累",
    )

    with patch(
        "app.services.chat.turn_orchestrator.EXECUTIVE_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.WORLD_PRESENCE_GATE_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts",
        return_value=_executive_test_contexts(),
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
        return_value={
            "candidate_memory": None, "candidate_memory_debug": None,
            "candidate_memory_decision": {"action": "ignore"}, "auto_added_memory": False,
        },
    ), patch(
        "app.services.chat.turn_orchestrator.build_chat_messages_preview_from_contexts", return_value={},
    ), patch(
        "app.services.chat.turn_orchestrator.add_message", return_value=101,
    ), patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience", return_value=303,
    ), patch(
        "app.services.chat.turn_orchestrator.decide_chat_turn_sync", return_value=executive,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
    ) as generate, patch(
        "app.services.chat.turn_orchestrator.stash_pending_message",
    ) as stash, patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update", return_value={"stage": 2},
    ):
        result = run_chat_turn("s", "你在吗", trace_id="trace-exec-defer")

    assert result["reply"] == ""
    assert result["assistant_message_id"] is None
    assert result["world_action"] == "reply_later"
    assert result["world_reason"] == "main_executive"
    generate.assert_not_called()
    stash.assert_called_once()


def test_main_executive_can_leave_message_unanswered_without_pending():
    from app.services.chat.turn_orchestrator import run_chat_turn

    executive = ExecutiveDecision(
        action="leave_unanswered", reason="这句不需要接", response_points=[],
        max_chars=0, max_beats=1, inner_reaction="没什么想说的",
    )

    with patch(
        "app.services.chat.turn_orchestrator.EXECUTIVE_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts",
        return_value=_executive_test_contexts(),
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
        return_value={
            "candidate_memory": None, "candidate_memory_debug": None,
            "candidate_memory_decision": {"action": "ignore"}, "auto_added_memory": False,
        },
    ), patch(
        "app.services.chat.turn_orchestrator.build_chat_messages_preview_from_contexts", return_value={},
    ), patch(
        "app.services.chat.turn_orchestrator.add_message", return_value=101,
    ), patch(
        "app.services.chat.turn_orchestrator.record_incoming_message_experience", return_value=303,
    ), patch(
        "app.services.chat.turn_orchestrator.decide_chat_turn_sync", return_value=executive,
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
    ) as generate, patch(
        "app.services.chat.turn_orchestrator.stash_pending_message",
    ) as stash, patch(
        "app.services.chat.turn_orchestrator.apply_relationship_update", return_value={"stage": 2},
    ):
        result = run_chat_turn("s", "嗯嗯", trace_id="trace-exec-unanswered")

    assert result["reply"] == ""
    assert result["assistant_message_id"] is None
    assert result["world_action"] == "chose_silence"
    assert result["world_reason"] == "main_executive"
    generate.assert_not_called()
    stash.assert_not_called()


def test_pending_reconsideration_still_lets_main_executive_defer():
    from app.services.chat.turn_orchestrator import run_chat_turn_from_persisted_user_messages

    executive = ExecutiveDecision(
        action="defer", reason="还是不想现在回", response_points=[],
        max_chars=0, max_beats=1, inner_reaction="想再缓缓",
    )
    contexts = _executive_test_contexts()
    contexts["history"] = [{"id": 101, "role": "user", "content": "你在吗"}]

    with patch(
        "app.services.chat.turn_orchestrator.EXECUTIVE_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts", return_value=contexts,
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
    ), patch(
        "app.services.chat.turn_orchestrator.resolve_persisted_turn_image_inputs", return_value=[],
    ), patch(
        "app.services.chat.turn_orchestrator.decide_chat_turn_sync", return_value=executive,
    ), patch(
        "app.services.chat.turn_orchestrator.record_executive_decision",
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
    ) as generate, patch(
        "app.services.chat.turn_orchestrator.add_message",
    ) as add:
        result = run_chat_turn_from_persisted_user_messages(
            session_id="s",
            message="你在吗",
            trace_id="trace-pending-defer",
            user_message_ids=[101],
        )

    assert result["deferred"] is True
    assert result["unanswered"] is False
    generate.assert_not_called()
    add.assert_not_called()


def test_pending_reconsideration_can_end_as_deliberate_non_reply():
    from app.services.chat.turn_orchestrator import run_chat_turn_from_persisted_user_messages

    executive = ExecutiveDecision(
        action="leave_unanswered", reason="这句就停在这里", response_points=[],
        max_chars=0, max_beats=1, inner_reaction="没想接",
    )
    contexts = _executive_test_contexts()
    contexts["history"] = [{"id": 101, "role": "user", "content": "嗯嗯"}]

    with patch(
        "app.services.chat.turn_orchestrator.EXECUTIVE_LAYER_ENABLED", True,
    ), patch(
        "app.services.chat.turn_orchestrator.SELECTION_LAYER_ENABLED", False,
    ), patch(
        "app.services.chat.turn_orchestrator.load_chat_contexts", return_value=contexts,
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
    ), patch(
        "app.services.chat.turn_orchestrator.resolve_persisted_turn_image_inputs", return_value=[],
    ), patch(
        "app.services.chat.turn_orchestrator.decide_chat_turn_sync", return_value=executive,
    ), patch(
        "app.services.chat.turn_orchestrator.record_executive_decision",
    ), patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
    ) as generate, patch(
        "app.services.chat.turn_orchestrator.add_message",
    ) as add:
        result = run_chat_turn_from_persisted_user_messages(
            session_id="s",
            message="嗯嗯",
            trace_id="trace-pending-unanswered",
            user_message_ids=[101],
        )

    assert result["deferred"] is False
    assert result["unanswered"] is True
    generate.assert_not_called()
    add.assert_not_called()
