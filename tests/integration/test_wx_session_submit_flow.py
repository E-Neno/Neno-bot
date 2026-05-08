from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.routers import platform as platform_router
from app.services.relationship_service import get_relationship_state_for_api
from app.services.session_submit_controller import SessionSubmitController
from app.storage.db import get_session_messages, list_debug_events, list_memories


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


def _platform_events(trace_id: str | None = None) -> list[dict]:
    events = list_debug_events(module="platform", trace_id=trace_id)
    for event in events:
        event["metadata"] = json.loads(event.get("metadata_json") or "{}")
    return events


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


def test_wx_memory_pipeline_stays_serialized_and_second_turn_sees_first_memory(client, monkeypatch):
    import app.security as security
    from app.services.chat import turn_orchestrator
    from app.services.chat import memory_candidate_service

    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(platform_router, "session_submit_controller", SessionSubmitController())
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)
    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", lambda messages, trace_id=None: f"reply:{messages[-1]['content']}")

    def fake_request_model_response(
        *,
        model_name: str | None = None,
        messages: list[dict] | None = None,
        timeout: int | None = None,
        trace_id: str | None = None,
    ) -> str:
        del model_name, timeout, trace_id
        prompt = (messages or [{}, {}])[-1].get("content", "")
        if "我喜欢乌龙茶" in prompt:
            return json.dumps(
                {
                    "should_store": True,
                    "content": "用户喜欢乌龙茶",
                    "memory_type": "preference",
                    "reason": "稳定偏好",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "should_store": False,
                "content": "",
                "memory_type": "",
                "reason": "无需记录",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(memory_candidate_service, "request_model_response", fake_request_model_response)

    first_payload = {
        "platform": "wx",
        "user_id": "wx-user-memory",
        "chat_type": "private",
        "message": "我喜欢乌龙茶",
    }
    second_payload = {
        "platform": "wx",
        "user_id": "wx-user-memory",
        "chat_type": "private",
        "message": "你还记得我刚才说了什么偏好吗",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_post_platform_message, client, first_payload)
        time.sleep(0.02)
        second_future = executor.submit(_post_platform_message, client, second_payload)

    assert first_future.result()[0] == 200
    assert second_future.result()[0] == 200

    memories = list_memories("WHERE is_active = 1")
    assert [(item["content"], item["memory_type"]) for item in memories] == [("用户喜欢乌龙茶", "preference")]

    messages = get_session_messages("wx:private:wx-user-memory")
    first_user = messages[0]
    second_user = messages[2]
    assert first_user["preview_payload"]["preview"]["selected_memories"] == []
    assert second_user["preview_payload"]["preview"]["selected_memories"][0]["content"] == "用户喜欢乌龙茶"
    assert first_user["metadata"]["submit_debug"]["submit_state"] == "completed"
    assert second_user["metadata"]["submit_debug"]["submit_state"] == "completed"


def test_delete_message_turn_only_removes_matching_trace_when_async_preprocess_exists(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-delete"

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        del media_path, trace_id
        time.sleep(0.12)
        return "第一轮语音"

    monkeypatch.setattr(platform_router, "transcribe_voice", fake_transcribe_voice)

    voice_payload = {
        "platform": "wx",
        "user_id": "wx-user-delete",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "voice", "media_path": "/tmp/fake-delete.silk", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-delete",
        "chat_type": "private",
        "message": "第二轮文本",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(_post_platform_message, client, voice_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    assert voice_future.result()[0] == 200
    assert text_future.result()[0] == 200
    assert get_max_active() == 1

    messages = get_session_messages(session_id)
    first_trace_id = messages[0]["trace_id"]
    second_trace_id = messages[2]["trace_id"]
    assert first_trace_id != second_trace_id

    response = client.post(
        "/session/delete-message",
        json={"message_id": messages[0]["id"]},
        headers=admin_headers,
    )
    assert response.status_code == 200
    deleted = response.json()
    assert deleted["deleted_scope"] == "turn"
    assert deleted["deleted_ids"] == [messages[0]["id"], messages[1]["id"]]
    assert deleted["trace_id"] == first_trace_id

    remaining = get_session_messages(session_id)
    assert [item["trace_id"] for item in remaining] == [second_trace_id, second_trace_id]
    assert [item["content"] for item in remaining] == ["第二轮文本", "reply:第二轮文本"]

    preview_response = client.get(
        f"/debug/chat-preview/message?message_id={remaining[0]['id']}",
        headers=admin_headers,
    )
    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["trace_id"] == second_trace_id
    assert payload["preview"]["current_user_message"] == "第二轮文本"


def test_wx_waiting_for_turn_is_visible_in_debug_snapshot(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)
    session_id = "wx:private:wx-user-waiting"
    release_first = threading.Event()

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        release_first.wait(timeout=1)
        return "[用户发送了一张图片，以下是图片理解结果]\n图片内容：等待中的大图"

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-waiting",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "image", "url": "https://example.com/slow.png", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-waiting",
        "chat_type": "private",
        "message": "我在后面等",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        image_future = executor.submit(_post_platform_message, client, image_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)
        time.sleep(0.05)
        snapshot_response = client.get(
            f"/debug/session-submit?session_id={session_id}",
            headers=admin_headers,
        )
        release_first.set()

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    active_items = {item["arrival_seq"]: item for item in snapshot["active"]}
    assert active_items[1]["submit_state"] == "preprocessing"
    assert active_items[2]["submit_state"] == "waiting_for_turn"
    assert active_items[2]["blocked_by_seq"] == 1

    assert image_future.result()[0] == 200
    assert text_future.result()[0] == 200
    assert get_max_active() == 1


def test_wx_asr_fallback_releases_later_turn_and_records_fallback_state(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)

    def fake_transcribe_voice(media_path: str, trace_id: str) -> str:
        del media_path, trace_id
        raise platform_router.VoiceASRError("asr failed")

    monkeypatch.setattr(platform_router, "transcribe_voice", fake_transcribe_voice)

    voice_payload = {
        "platform": "wx",
        "user_id": "wx-user-asr-fallback",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "voice", "media_path": "/tmp/asr-fail.silk", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-asr-fallback",
        "chat_type": "private",
        "message": "第二条还能继续",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_future = executor.submit(_post_platform_message, client, voice_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    voice_status, voice_data = voice_future.result()
    text_status, text_data = text_future.result()

    assert voice_status == 200
    assert voice_data["reply"] == "这条语音我刚刚没听清，你再发一次试试。"
    assert text_status == 200
    assert text_data["reply"] == "reply:第二条还能继续"
    assert get_max_active() == 1

    messages = get_session_messages("wx:private:wx-user-asr-fallback")
    assert [item["content"] for item in messages] == ["第二条还能继续", "reply:第二条还能继续"]

    snapshot_response = client.get(
        "/debug/session-submit",
        params={"session_id": "wx:private:wx-user-asr-fallback"},
        headers=admin_headers,
    )
    snapshot = snapshot_response.json()
    recent_items = {item["arrival_seq"]: item for item in snapshot["recent"]}
    assert recent_items[1]["submit_state"] == "fallback_completed"
    assert recent_items[1]["failed_phase"] == "preprocess"
    assert recent_items[1]["error_type"] == "VoiceASRError"
    assert recent_items[2]["submit_state"] == "completed"


def test_wx_preprocess_failure_does_not_block_later_turn(client, monkeypatch, admin_headers):
    get_max_active = _patch_turn_dependencies(monkeypatch)

    def fake_normalize_multimodal_message(*, message: str | None, attachments, trace_id: str | None = None) -> str:
        del message, attachments, trace_id
        raise platform_router.MultimodalInputError("vision timeout")

    monkeypatch.setattr(platform_router, "normalize_multimodal_message", fake_normalize_multimodal_message)

    image_payload = {
        "platform": "wx",
        "user_id": "wx-user-preprocess-fail",
        "chat_type": "private",
        "message": "",
        "attachments": [
            {"kind": "image", "url": "https://example.com/fail.png", "source": "wx"},
        ],
    }
    text_payload = {
        "platform": "wx",
        "user_id": "wx-user-preprocess-fail",
        "chat_type": "private",
        "message": "后续文本要继续",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        image_future = executor.submit(_post_platform_message, client, image_payload)
        time.sleep(0.02)
        text_future = executor.submit(_post_platform_message, client, text_payload)

    image_status, image_data = image_future.result()
    text_status, text_data = text_future.result()

    assert image_status == 400
    assert text_status == 200
    assert text_data["reply"] == "reply:后续文本要继续"

    snapshot_response = client.get(
        "/debug/session-submit",
        params={"session_id": "wx:private:wx-user-preprocess-fail"},
        headers=admin_headers,
    )
    snapshot = snapshot_response.json()
    assert any(item["submit_state"] == "completed" for item in snapshot["recent"] + snapshot["active"])
    failed_events = [
        event for event in _platform_events()
        if event["event"] == "session_submit_failed"
    ]
    assert any(event["metadata"].get("failed_phase") == "preprocess" for event in failed_events)
    assert "detail" in image_data


def test_wx_submit_failure_cleans_running_state_and_later_turns_continue(client, monkeypatch, admin_headers):
    import app.security as security
    from app.services.chat import turn_orchestrator

    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(platform_router, "session_submit_controller", SessionSubmitController())
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)
    monkeypatch.setattr(turn_orchestrator, "process_memory_candidate", lambda *args, **kwargs: _memory_result())

    def flaky_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
        del trace_id
        time.sleep(0.05)
        if messages[-1]["content"] == "第一条会失败":
            raise RuntimeError("model boom")
        return f"reply:{messages[-1]['content']}"

    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", flaky_generate_chat_reply)

    first_payload = {
        "platform": "wx",
        "user_id": "wx-user-submit-fail",
        "chat_type": "private",
        "message": "第一条会失败",
    }
    second_payload = {
        "platform": "wx",
        "user_id": "wx-user-submit-fail",
        "chat_type": "private",
        "message": "第二条会成功",
    }
    third_payload = {
        "platform": "wx",
        "user_id": "wx-user-submit-fail",
        "chat_type": "private",
        "message": "第三条继续成功",
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_post_platform_message, client, first_payload)
        time.sleep(0.02)
        second_future = executor.submit(_post_platform_message, client, second_payload)

    first_status, first_data = first_future.result()
    second_status, second_data = second_future.result()
    third_status, third_data = _post_platform_message(client, third_payload)

    assert first_status == 500
    assert first_data["detail"] == "chat failed"
    assert second_status == 200
    assert second_data["reply"] == "reply:第二条会成功"
    assert third_status == 200
    assert third_data["reply"] == "reply:第三条继续成功"

    snapshot_response = client.get(
        "/debug/session-submit",
        params={"session_id": "wx:private:wx-user-submit-fail"},
        headers=admin_headers,
    )
    snapshot = snapshot_response.json()
    assert any(item["arrival_seq"] == 3 and item["submit_state"] == "completed" for item in snapshot["recent"] + snapshot["active"])

    events = _platform_events()
    failed_events = [
        event for event in events
        if event["event"] == "session_submit_failed"
    ]
    finished_events = [
        event for event in events
        if event["event"] == "session_submit_finished"
    ]
    assert any(event["metadata"].get("failed_phase") == "submit" for event in failed_events)
    assert sum(1 for event in finished_events if event["metadata"].get("submit_state") == "completed") >= 2
