from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

from app.services.chat.selection_layer import fallback_decision


def _init_test_db(tmp_path: Path) -> None:
    import app.storage.db as db_storage

    data_dir = tmp_path / "data"
    db_storage.DB_DIR = data_dir
    db_storage.DB_PATH = data_dir / "bot.db"
    db_storage.init_db()


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
