from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.routers import platform as platform_router
from app.services.relationship_service import get_relationship_state_for_api
from app.services.session_aggregation_controller import SessionAggregationController
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


def _patch_turn_dependencies(monkeypatch, *, window_seconds: float = 0.05, reply_sleep: float = 0.08):
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
            time.sleep(reply_sleep)
            content = messages[-1]["content"]
            if isinstance(content, list):
                text = str(content[-1].get("text", ""))
                message = text.split("【对方刚说】\n", 1)[-1]
            else:
                message = str(content)
            return f"reply:{message}"
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", fake_generate_chat_reply)
    monkeypatch.setattr(turn_orchestrator, "process_memory_candidate", lambda *args, **kwargs: _memory_result())
    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(platform_router, "session_submit_controller", SessionSubmitController())
    monkeypatch.setattr(
        platform_router,
        "session_aggregation_controller",
        SessionAggregationController(window_seconds=window_seconds),
    )
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)

    return lambda: max_active


def test_wx_image_then_text_is_aggregated_into_one_batch(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-image-text"

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：这是一张流程图"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-image-text",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "image", "url": "https://example.com/chart.png", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-image-text",
        "chat_type": "private",
        "message": "这是什么意思",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        image_future = executor.submit(_post_platform_message, client, image_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    image_status, image_data = image_future.result()
    text_status, text_data = text_future.result()

    assert image_status == 200
    assert text_status == 200
    assert image_data["reply"] == text_data["reply"]
    assert "这是什么意思" in image_data["reply"]
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 2
    assert messages[1]["metadata"]["aggregation"]["source_count"] == 2
    assert messages[0]["trace_id"] == messages[1]["trace_id"] == messages[2]["trace_id"]
    assert messages[0]["preview_payload"]["preview"]["current_user_message"].startswith("[用户在短时间内连续发送了 2 条内容]")

    preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[0]['id']}",
        headers=admin_headers,
    )
    payload = preview_response.json()
    assert payload["preview"]["current_user_message"].startswith("[用户在短时间内连续发送了 2 条内容]")
    assert payload["message"]["metadata"]["aggregation"]["source_count"] == 2


def test_wx_text_burst_within_window_becomes_one_batch(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-text-burst"

    payloads = [
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第一句"},
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第二句"},
        {"platform": "wx", "user_id": "wx-user-text-burst", "chat_type": "private", "message": "第三句"},
    ]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for payload in payloads:
            futures.append(executor.submit(_post_platform_message, client, payload))
            time.sleep(0.015)

    results = [future.result() for future in futures]
    assert all(status == 200 for status, _ in results)
    assert len({data["reply"] for _, data in results}) == 1
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "user", "assistant"]
    assert [item["content"] for item in messages[:3]] == ["第一句", "第二句", "第三句"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 3
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 1


def test_wx_voice_and_text_are_aggregated_together(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-voice-text"

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        del media_path, trace_id
        return "语音里说的是这个位置"

    monkeypatch.setattr(platform_router, "transcribe_voice", fake_transcribe_voice)

    voice_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice-text",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "voice", "media_path": "/tmp/fake.silk", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-voice-text",
        "chat_type": "private",
        "message": "我是说这个地方",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(_post_platform_message, client, voice_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    voice_status, voice_data = voice_future.result()
    text_status, text_data = text_future.result()
    assert voice_status == 200
    assert text_status == 200
    assert voice_data["reply"] == text_data["reply"]
    assert "语音里说的是这个位置" in voice_data["reply"]
    assert "我是说这个地方" in voice_data["reply"]
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    assert messages[0]["metadata"]["message_type"] == "voice"
    assert messages[1]["metadata"]["message_type"] == "text"


def test_wx_messages_outside_window_split_into_two_batches(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch, window_seconds=0.04)
    session_id = "wx:private:wx-user-window-split"

    first_status, first_data = _post_platform_message(
        client,
        {"platform": "wx", "user_id": "wx-user-window-split", "chat_type": "private", "message": "第一批"},
    )
    time.sleep(0.08)
    second_status, second_data = _post_platform_message(
        client,
        {"platform": "wx", "user_id": "wx-user-window-split", "chat_type": "private", "message": "第二批"},
    )

    assert first_status == 200
    assert second_status == 200
    assert first_data["reply"] != second_data["reply"]
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["batch_id"] != messages[2]["metadata"]["aggregation"]["batch_id"]
    assert get_relationship_state_for_api(session_id)["conversation_count"] == 2


def test_wx_batch_waits_for_slow_preprocess_before_single_submit(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch, window_seconds=0.08)
    session_id = "wx:private:wx-user-slow-preprocess"
    release_image = threading.Event()

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        release_image.wait(timeout=1)
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：慢图"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-slow-preprocess",
        "chat_type": "private",
        "message": "",
        "attachments": [{"kind": "image", "url": "https://example.com/slow.png", "source": "wx"}],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-slow-preprocess",
        "chat_type": "private",
        "message": "后补一句",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        image_future = executor.submit(_post_platform_message, client, image_payload)
        time.sleep(0.01)
        text_future = executor.submit(_post_platform_message, client, text_payload)
        time.sleep(0.09)
        snapshot_response = client.get(
            f"/debug/session-aggregation?session_id={session_id}",
            headers=admin_headers,
        )
        release_image.set()

    snapshot = snapshot_response.json()
    assert snapshot["active_batch_count"] == 1
    assert snapshot["active_batches"][0]["batch_state"] == "batch_waiting_ready"
    assert snapshot["active_batches"][0]["source_count"] == 2

    image_status, image_data = image_future.result()
    text_status, text_data = text_future.result()
    assert image_status == 200
    assert text_status == 200
    assert image_data["reply"] == text_data["reply"]
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]


def test_wx_batches_still_submit_serially_across_windows(client, monkeypatch):
    get_max_active = _patch_turn_dependencies(monkeypatch, window_seconds=0.04, reply_sleep=0.15)
    session_id = "wx:private:wx-user-two-batches"

    with ThreadPoolExecutor(max_workers=3) as executor:
        first_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第一批-1"},
        )
        time.sleep(0.015)
        second_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第一批-2"},
        )
        time.sleep(0.08)
        third_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-two-batches", "chat_type": "private", "message": "第二批-1"},
        )

    assert first_future.result()[0] == 200
    assert second_future.result()[0] == 200
    assert third_future.result()[0] == 200
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant", "user", "assistant"]
    assert messages[0]["metadata"]["aggregation"]["batch_id"] == messages[1]["metadata"]["aggregation"]["batch_id"]
    assert messages[3]["metadata"]["aggregation"]["batch_id"] != messages[0]["metadata"]["aggregation"]["batch_id"]


def test_wx_aggregated_trace_preview_and_delete_stay_explainable(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-delete"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-delete", "chat_type": "private", "message": "先发图片说明"},
        )
        time.sleep(0.02)
        second_future = executor.submit(
            _post_platform_message,
            client,
            {"platform": "wx", "user_id": "wx-user-delete", "chat_type": "private", "message": "再补一句问题"},
        )

    assert first_future.result()[0] == 200
    assert second_future.result()[0] == 200
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    assert [item["role"] for item in messages] == ["user", "user", "assistant"]
    first_trace_id = messages[0]["trace_id"]
    assert first_trace_id == messages[1]["trace_id"] == messages[2]["trace_id"]
    assert messages[0]["metadata"]["aggregation"]["source_count"] == 2
    assert len(messages[0]["metadata"]["aggregation"]["source_message_ids"]) == 2

    preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[0]['id']}",
        headers=admin_headers,
    )
    preview_payload = preview_response.json()
    assert preview_payload["trace_id"] == first_trace_id
    assert preview_payload["message"]["metadata"]["aggregation"]["source_count"] == 2

    assistant_preview_response = client.get(
        f"/debug/chat-preview/message?message_id={messages[2]['id']}",
        headers=admin_headers,
    )
    assert assistant_preview_response.status_code == 200
    assistant_preview = assistant_preview_response.json()
    assert assistant_preview["message"]["role"] == "assistant"
    assert assistant_preview["preview_source_message_id"] == messages[0]["id"]
    assert assistant_preview["preview_source_metadata"]["aggregation"]["source_count"] == 2

    delete_response = client.post(
        "/session/delete-message",
        json={"message_id": messages[0]["id"]},
        headers=admin_headers,
    )
    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["deleted_scope"] == "turn"
    assert deleted["trace_id"] == first_trace_id
    assert deleted["deleted_ids"] == [messages[0]["id"], messages[1]["id"], messages[2]["id"]]
    assert get_session_messages(session_id) == []
