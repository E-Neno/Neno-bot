from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.routers import platform as platform_router
from app.services.relationship_service import get_relationship_state_for_api
from app.services.session_submit_controller import SessionSubmitController
from app.storage.db import get_session_messages


def _memory_result() -> dict:
    return {
        "candidate_memory": None,
        "candidate_memory_debug": None,
        "candidate_memory_decision": {
            "action": "skip",
            "reason": "test",
            "risk_level": "low",
        },
        "auto_added_memory": False,
    }


def _post_platform_message(client, payload: dict) -> tuple[int, dict]:
    response = client.post("/platform/openclaw/message", json=payload)
    return response.status_code, response.json()


def _patch_turn_dependencies(monkeypatch):
    import app.security as security
    from app.services.chat import turn_orchestrator

    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
        nonlocal active
        nonlocal max_active
        del trace_id
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.08)
            return f"reply:{messages[-1]['content']}"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", fake_generate_chat_reply)
    monkeypatch.setattr(turn_orchestrator, "process_memory_candidate", lambda *args, **kwargs: _memory_result())
    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(platform_router, "session_submit_controller", SessionSubmitController())
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)

    return lambda: max_active


def test_wx_text_requests_stay_serialized_per_session(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-text"

    first_payload = {
        "platform": "wx",
        "user_id": "wx-user-text",
        "chat_type": "private",
        "message": "第一条文本",
    }
    second_payload = {
        "platform": "wx",
        "user_id": "wx-user-text",
        "chat_type": "private",
        "message": "第二条文本",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_post_platform_message, client, first_payload)
        time.sleep(0.02)
        second_future = executor.submit(_post_platform_message, client, second_payload)

    first_status, first_data = first_future.result()
    second_status, second_data = second_future.result()

    assert first_status == 200
    assert second_status == 200
    assert first_data["reply"] == "reply:第一条文本"
    assert second_data["reply"] == "reply:第二条文本"
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["content"] for item in messages] == [
        "第一条文本",
        "reply:第一条文本",
        "第二条文本",
        "reply:第二条文本",
    ]
    assert messages[0]["trace_id"] == messages[1]["trace_id"]
    assert messages[2]["trace_id"] == messages[3]["trace_id"]
    assert messages[0]["preview_payload"]["preview"]["current_user_message"] == "第一条文本"
    assert messages[2]["preview_payload"]["preview"]["current_user_message"] == "第二条文本"

    first_metadata = messages[0]["metadata"] or {}
    second_metadata = messages[2]["metadata"] or {}
    assert first_metadata["ingress"]["arrival_seq"] == 1
    assert second_metadata["ingress"]["arrival_seq"] == 2
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 2


def test_wx_image_preprocess_can_finish_late_but_submit_keeps_arrival_order(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-image"

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        time.sleep(0.15)
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：一只猫"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-image",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "image", "url": "https://example.com/cat.jpg", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-image",
        "chat_type": "private",
        "message": "后到的文本",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        image_future = executor.submit(_post_platform_message, client, image_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    image_status, image_data = image_future.result()
    text_status, text_data = text_future.result()

    assert image_status == 200
    assert text_status == 200
    assert image_data["reply"] == "reply:[用户发送了一张图片，以下是图片理解结果]\n图片内容：一只猫"
    assert text_data["reply"] == "reply:后到的文本"
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["content"] for item in messages] == [
        "[用户发送了一张图片，以下是图片理解结果]\n图片内容：一只猫",
        "reply:[用户发送了一张图片，以下是图片理解结果]\n图片内容：一只猫",
        "后到的文本",
        "reply:后到的文本",
    ]
    image_metadata = messages[0]["metadata"] or {}
    text_metadata = messages[2]["metadata"] or {}
    assert image_metadata["ingress"]["arrival_seq"] == 1
    assert text_metadata["ingress"]["arrival_seq"] == 2
    assert messages[0]["preview_payload"]["preview"]["current_user_message"].startswith("[用户发送了一张图片")
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 2


def test_wx_voice_preprocess_can_finish_late_but_submit_keeps_arrival_order(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-voice"

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        del media_path, trace_id
        time.sleep(0.15)
        return "语音转写内容"

    monkeypatch.setattr(platform_router, "transcribe_voice", fake_transcribe_voice)

    voice_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "voice", "media_path": "/tmp/fake.silk", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice",
        "chat_type": "private",
        "message": "后到的文本",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(_post_platform_message, client, voice_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    voice_status, voice_data = voice_future.result()
    text_status, text_data = text_future.result()

    assert voice_status == 200
    assert text_status == 200
    assert voice_data["reply"] == "reply:语音转写内容"
    assert text_data["reply"] == "reply:后到的文本"
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["content"] for item in messages] == [
        "语音转写内容",
        "reply:语音转写内容",
        "后到的文本",
        "reply:后到的文本",
    ]
    voice_metadata = messages[0]["metadata"] or {}
    text_metadata = messages[2]["metadata"] or {}
    assert voice_metadata["message_type"] == "voice"
    assert voice_metadata["ingress"]["arrival_seq"] == 1
    assert text_metadata["ingress"]["arrival_seq"] == 2
    assert messages[0]["preview_payload"]["preview"]["current_user_message"] == "语音转写内容"
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 2
