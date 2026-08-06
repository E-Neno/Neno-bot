from __future__ import annotations

import json
from typing import Any

from starlette.websockets import WebSocketDisconnect


TEST_MOBILE_TOKEN = "mobile-test-token"


def mobile_headers(monkeypatch) -> dict[str, str]:
    from app import config
    from app import security

    monkeypatch.setattr(config, "MOBILE_TOKEN", TEST_MOBILE_TOKEN, raising=False)
    monkeypatch.setattr(security, "MOBILE_TOKEN", TEST_MOBILE_TOKEN, raising=False)
    return {"Authorization": f"Bearer {TEST_MOBILE_TOKEN}"}


def test_mobile_status_requires_token(client):
    response = client.get("/mobile/status")

    assert response.status_code == 403


def test_mobile_status_accepts_bearer_token(client, monkeypatch):
    response = client.get("/mobile/status", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["api"] == "mobile-v0"
    assert body["features"] == {
        "attachments": True,
        "notifications": False,
        "quick_reply": False,
    }


def test_mobile_upload_saves_file_and_returns_attachment(client, monkeypatch):
    response = client.post(
        "/mobile/uploads",
        params={"kind": "file", "filename": "笔记.txt"},
        headers={**mobile_headers(monkeypatch), "Content-Type": "text/plain"},
        content=b"hello from mobile",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    attachment = body["attachment"]
    assert attachment["kind"] == "file"
    assert attachment["source"] == "mobile"
    assert attachment["mime_type"] == "text/plain"
    assert attachment["text_hint"] == "笔记.txt"
    assert attachment["media_path"].endswith(".txt")


def test_mobile_conversations_returns_chinese_contacts(client, monkeypatch):
    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    data = response.json()
    titles = [item["title"] for item in data["conversations"]]
    assert titles[:3] == ["Neno", "写作助手", "代码助手"]
    assert data["conversations"][0]["id"] == "neno"
    assert data["conversations"][0]["pinned"] is True
    assert data["conversations"][0]["kind"] == "primary"


def test_mobile_conversations_summarize_attachment_only_messages(client, monkeypatch):
    from app.storage.db import add_message

    add_message(
        "mobile:neno",
        "user",
        "[用户发送了一张图片]\n图片内容：一张截图",
        trace_id="mobile-preview-image",
        message_type="image",
        source="mobile",
        metadata={
            "raw_input": "",
            "attachments": [{"kind": "image", "url": "https://example.com/a.png", "source": "mobile"}],
        },
    )

    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json()["conversations"][0]["last_message"] == "发来一张图片"

    add_message(
        "mobile:neno",
        "user",
        "语音识别出来的话",
        trace_id="mobile-preview-voice",
        message_type="voice",
        source="mobile",
        metadata={
            "raw_input": "",
            "attachments": [{"kind": "voice", "media_path": "uploads/mobile/voice/a.m4a", "source": "mobile"}],
        },
    )

    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json()["conversations"][0]["last_message"] == "发来一段语音"


def test_presence_mapping_pure():
    from app.services.mobile_api_service import _presence_from

    assert _presence_from("sleeping", 0) == "睡着了"
    assert _presence_from("sleeping", 3) == "睡着了"  # 睡着优先于欠回复
    assert _presence_from("awake", 2) == "稍后回复"
    assert _presence_from("awake", 0) == "在线"
    assert _presence_from(None, 0) == "在线"


def test_sync_presence_degrades_inside_running_loop_without_warning(monkeypatch, recwarn):
    import asyncio
    import gc

    import app.services.mobile_api_service as mobile_service

    async def fake_read_presence_state():
        return "awake", 0

    async def run_in_loop():
        return mobile_service.neno_presence()

    monkeypatch.setattr(mobile_service, "_read_presence_state", fake_read_presence_state)

    assert asyncio.run(run_in_loop()) == mobile_service.DEFAULT_PRESENCE
    gc.collect()
    leaked = [warning for warning in recwarn if "was never awaited" in str(warning.message)]
    assert leaked == []


def test_mobile_messages_include_presence(client, monkeypatch):
    import app.routers.mobile as mobile_router

    monkeypatch.setattr(mobile_router, "neno_presence", lambda: "睡着了")

    response = client.get("/mobile/conversations/neno/messages", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json()["presence"] == "睡着了"


def test_mobile_websocket_requires_token(client):
    try:
        with client.websocket_connect("/mobile/ws"):
            raise AssertionError("websocket should reject missing token")
    except WebSocketDisconnect as exc:
        assert exc.code == 1008


def test_mobile_websocket_sends_hello_and_presence(client, monkeypatch):
    import app.routers.mobile as mobile_router

    async def fake_presence():
        return "睡着了"

    monkeypatch.setattr(mobile_router, "read_neno_presence", fake_presence)
    headers = mobile_headers(monkeypatch)

    with client.websocket_connect("/mobile/ws", headers=headers) as websocket:
        hello = websocket.receive_json()
        presence = websocket.receive_json()
        conversations = websocket.receive_json()
        messages = websocket.receive_json()
        websocket.send_text("ping")
        pong = websocket.receive_json()

    assert hello == {"type": "hello", "api": "mobile-v0"}
    assert pong == {"type": "pong"}
    assert conversations["type"] == "conversations"
    assert conversations["conversations"][0]["id"] == "neno"
    assert messages["type"] == "messages"
    assert messages["conversation_id"] == "neno"
    assert isinstance(messages["messages"], list)
    assert presence == {
        "type": "presence",
        "conversation_id": "neno",
        "presence": "睡着了",
    }


def test_mobile_websocket_pushes_message_events(client, monkeypatch):
    from app.services.mobile_realtime import publish_mobile_event

    headers = mobile_headers(monkeypatch)

    with client.websocket_connect("/mobile/ws", headers=headers) as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.receive_json()
        websocket.receive_json()
        publish_mobile_event(
            {
                "type": "message",
                "conversation_id": "neno",
                "message": {
                    "id": 42,
                    "role": "assistant",
                    "text": "late reply",
                    "created_at": None,
                    "display_time": "23:41",
                    "pending": False,
                },
            }
        )
        event = websocket.receive_json()

    assert event["type"] == "message"
    assert event["conversation_id"] == "neno"
    assert event["message"]["text"] == "late reply"
    assert event["message"]["display_time"] == "23:41"


def test_mobile_conversations_include_neno_presence(client, monkeypatch):
    import app.services.mobile_api_service as mobile_service

    monkeypatch.setattr(mobile_service, "neno_presence", lambda: "稍后回复")

    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    neno = response.json()["conversations"][0]
    assert neno["id"] == "neno"
    assert neno["presence"] == "稍后回复"


def test_mobile_messages_do_not_expose_debug_fields(client, monkeypatch):
    import app.storage.db as db_storage
    from app.storage.db import add_message

    db_storage.execute_write(
        "INSERT INTO life_world_state (id, state_json, updated_at) VALUES (1, ?, ?)",
        (
            json.dumps({"sim_minutes": 14 * 60 + 37}),
            "2026-06-24T14:37:00+08:00",
        ),
    )

    add_message("mobile:neno", "user", "在吗", trace_id="trace-mobile")
    add_message("mobile:neno", "assistant", "在。", trace_id="trace-mobile")

    response = client.get("/mobile/conversations/neno/messages", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "neno"
    assert [item["text"] for item in body["messages"]] == ["在吗", "在。"]
    assert [item["display_time"] for item in body["messages"]] == ["14:37", "14:37"]
    encoded = str(body)
    assert "candidate_memory_debug" not in encoded
    assert "relationship_context" not in encoded
    assert "metadata_json" not in encoded


def test_mobile_send_message_uses_mobile_source_and_returns_public_shape(client, monkeypatch):
    import app.services.mobile_api_service as mobile_service
    import app.storage.db as db_storage
    from app.storage.db import add_message

    db_storage.execute_write(
        "INSERT INTO life_world_state (id, state_json, updated_at) VALUES (1, ?, ?)",
        (
            json.dumps({"sim_minutes": 14 * 60 + 37}),
            "2026-06-24T14:37:00+08:00",
        ),
    )

    captured: dict[str, Any] = {}

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        captured.update(
            {
                "session_id": session_id,
                "message": message,
                "trace_id": trace_id,
                "input_record": input_record,
            }
        )
        user_id = add_message("mobile:neno", "user", message, trace_id=trace_id, source="mobile")
        assistant_id = add_message("mobile:neno", "assistant", "在。", trace_id=trace_id, source="mobile")
        return {
            "reply": "在。",
            "trace_id": trace_id,
            "user_message_id": user_id,
            "assistant_message_id": assistant_id,
        }

    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={"text": " 在吗 "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "neno"
    assert body["user_message"] == {
        "id": body["user_message"]["id"],
        "role": "user",
        "text": "在吗",
        "created_at": body["user_message"]["created_at"],
        "display_time": "14:37",
        "attachments": [],
        "pending": False,
    }
    assert body["assistant_message"] == {
        "id": body["assistant_message"]["id"],
        "role": "assistant",
        "text": "在。",
        "created_at": body["assistant_message"]["created_at"],
        "display_time": "14:37",
        "attachments": [],
        "pending": False,
    }
    assert captured["session_id"] == "mobile:neno"
    assert captured["message"] == "在吗"
    assert captured["trace_id"]
    assert captured["input_record"]["source"] == "mobile"
    assert captured["input_record"]["message_type"] == "text"


def test_mobile_send_message_normalizes_file_attachment(client, monkeypatch, tmp_path):
    import app.services.mobile_api_service as mobile_service
    from app.storage.db import add_message

    note = tmp_path / "note.txt"
    note.write_text("文件里的内容", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        captured.update(
            {
                "session_id": session_id,
                "message": message,
                "trace_id": trace_id,
                "input_record": input_record,
            }
        )
        user_id = add_message("mobile:neno", "user", message, trace_id=trace_id, source="mobile")
        return {
            "reply": "",
            "trace_id": trace_id,
            "user_message_id": user_id,
            "assistant_message_id": None,
        }

    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={
            "text": "看看这个",
            "attachments": [
                {
                    "kind": "file",
                    "media_path": str(note),
                    "mime_type": "text/plain",
                    "source": "mobile",
                    "text_hint": "note.txt",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert captured["input_record"]["message_type"] == "file"
    assert captured["input_record"]["pipeline"]["file"]["success"] is True
    assert "文件里的内容" in captured["message"]
    assert "看看这个" in captured["message"]


def test_mobile_send_message_normalizes_voice_attachment(client, monkeypatch, tmp_path):
    import app.services.mobile_api_service as mobile_service
    from app.storage.db import add_message

    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"fake")
    captured: dict[str, Any] = {}

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        assert media_path == str(audio)
        assert trace_id
        return "语音识别出来的话"

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        captured.update({"message": message, "input_record": input_record})
        user_id = add_message(
            "mobile:neno",
            "user",
            message,
            trace_id=trace_id,
            message_type="voice",
            source="mobile",
            metadata=input_record,
        )
        return {"reply": "", "trace_id": trace_id, "user_message_id": user_id, "assistant_message_id": None}

    monkeypatch.setattr(mobile_service, "transcribe_voice", fake_transcribe_voice)
    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={
            "text": "",
            "attachments": [
                {
                    "kind": "voice",
                    "media_path": str(audio),
                    "mime_type": "audio/wav",
                    "source": "mobile",
                    "text_hint": "voice.wav",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert captured["input_record"]["message_type"] == "voice"
    assert captured["input_record"]["pipeline"]["asr"]["success"] is True
    assert captured["input_record"]["attachments"][0]["text_hint"] == "语音识别出来的话"
    assert "语音识别出来的话" in captured["message"]
    body = response.json()
    assert body["user_message"]["text"] == ""
    assert body["user_message"]["attachments"][0]["text_hint"] == "语音识别出来的话"
    assert "用户发送了一段语音" not in body["user_message"]["text"]


def test_mobile_send_message_normalizes_image_attachment(client, monkeypatch):
    import app.services.mobile_api_service as mobile_service
    from app.storage.db import add_message

    captured: dict[str, Any] = {}

    def fake_normalize_multimodal_message(*, message, attachments, trace_id=None):
        assert message == "这张图呢"
        assert attachments[0].kind == "image"
        return "[用户发送了一张图片]\n图片内容：一张截图"

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        captured.update({"message": message, "input_record": input_record})
        user_id = add_message(
            "mobile:neno",
            "user",
            message,
            trace_id=trace_id,
            message_type="image",
            source="mobile",
            metadata=input_record,
        )
        return {"reply": "", "trace_id": trace_id, "user_message_id": user_id, "assistant_message_id": None}

    monkeypatch.setattr(mobile_service, "normalize_multimodal_message", fake_normalize_multimodal_message)
    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={
            "text": "这张图呢",
            "attachments": [{"kind": "image", "url": "https://example.com/a.png", "source": "mobile"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_message"]["text"] == "这张图呢"
    assert body["user_message"]["attachments"][0]["kind"] == "image"
    assert captured["input_record"]["message_type"] == "image"
    assert captured["input_record"]["pipeline"]["vision"]["success"] is True
    assert "图片内容" in captured["message"]
    assert "图片内容" not in body["user_message"]["text"]


def test_mobile_image_visual_memory_archives_without_caption_normalization(client, monkeypatch, tmp_path):
    import app.config as config
    import app.services.mobile_api_service as mobile_service
    from app.storage.db import add_message

    image = tmp_path / "screen.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (6).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )
    monkeypatch.setattr(config, "VISUAL_MEMORY_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "VISUAL_ASSET_ROOT", str(tmp_path / "data" / "visual_assets"), raising=False)
    captured: dict[str, Any] = {}

    def fail_normalize_multimodal_message(*, message, attachments, trace_id=None):
        raise AssertionError("visual memory path should not call caption normalization")

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        captured.update({"message": message, "input_record": input_record})
        user_id = add_message(
            "mobile:neno",
            "user",
            message,
            trace_id=trace_id,
            message_type="image",
            source="mobile",
            metadata=input_record,
        )
        return {"reply": "", "trace_id": trace_id, "user_message_id": user_id, "assistant_message_id": None}

    monkeypatch.setattr(mobile_service, "normalize_multimodal_message", fail_normalize_multimodal_message)
    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={
            "text": "看这个",
            "attachments": [
                {
                    "kind": "image",
                    "media_path": str(image),
                    "mime_type": "image/png",
                    "source": "mobile",
                    "text_hint": "screen.png",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert captured["message"].startswith("[用户发送了一张图片]")
    assert "用户附带文字：看这个" in captured["message"]
    assert "图片内容" not in captured["message"]
    visual_assets = captured["input_record"]["visual_assets"]
    assert visual_assets[0]["asset_uid"].startswith("vimg_")
    assert visual_assets[0]["width"] == 6
    assert captured["input_record"]["attachments"][0]["asset_uid"] == visual_assets[0]["asset_uid"]
    encoded = str(captured["input_record"])
    assert "base64" not in encoded
    assert "data:image" not in encoded


def test_mobile_send_message_returns_400_when_image_normalization_fails(client, monkeypatch):
    import app.services.mobile_api_service as mobile_service
    from app.services.chat.multimodal_input_service import MultimodalInputError

    def fake_normalize_multimodal_message(*, message, attachments, trace_id=None):
        raise MultimodalInputError("image attachment missing input")

    def fake_run_chat_turn(*args, **kwargs):
        raise AssertionError("chat core must not run after attachment normalization fails")

    monkeypatch.setattr(mobile_service, "normalize_multimodal_message", fake_normalize_multimodal_message)
    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={
            "text": "",
            "attachments": [{"kind": "image", "media_path": "uploads/mobile/image/a.png", "source": "mobile"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]


def test_mobile_send_message_handles_silent_reply(client, monkeypatch):
    """主脑选择不回 / 在场门控暂存时，assistant_message_id 为 None。
    必须返回 200 且 assistant_message=null，而不是 500（int(None) 崩溃）。"""
    import app.services.mobile_api_service as mobile_service

    def fake_run_chat_turn(session_id, message, trace_id=None, input_record=None):
        return {
            "reply": "",
            "trace_id": trace_id,
            "user_message_id": 301,
            "assistant_message_id": None,
            "world_action": "chose_silence",
        }

    monkeypatch.setattr(mobile_service, "run_chat_turn", fake_run_chat_turn)

    response = client.post(
        "/mobile/conversations/neno/messages",
        headers=mobile_headers(monkeypatch),
        json={"text": "在嘛"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["user_message"]["id"] == 301
    assert body["user_message"]["text"] == "在嘛"
    assert body["assistant_message"] is None
