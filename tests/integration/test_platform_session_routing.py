from __future__ import annotations

import app.security as security
from app.routers import platform as platform_router
from app.services.relationship_service import get_relationship_state_for_api
from app.storage.db import get_session_messages
from app.services.chat.selection_layer import fallback_decision


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


def _patch_turn_dependencies(monkeypatch):
    from app.services.chat import turn_orchestrator

    def fake_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
        del trace_id
        content = messages[-1]["content"]
        if isinstance(content, list):
            text = str(content[-1].get("text", ""))
            message = text.split("【对方刚说】\n", 1)[-1]
        else:
            message = str(content)
        return f"reply:{message}"

    monkeypatch.setattr(turn_orchestrator, "generate_chat_reply", fake_generate_chat_reply)
    monkeypatch.setattr(turn_orchestrator, "process_memory_candidate", lambda *args, **kwargs: _memory_result())
    monkeypatch.setattr(turn_orchestrator, "select_response_sync", lambda messages, *args, **kwargs: fallback_decision(messages))
    monkeypatch.setattr(platform_router, "record_platform_proactive_target", lambda **kwargs: None)
    monkeypatch.setattr(security, "is_loopback_client", lambda request: True)


def test_platform_session_routing_override_controls_future_messages_only(client, admin_headers, monkeypatch):
    _patch_turn_dependencies(monkeypatch)
    auto_session_id = "wx:private:wx-route-user"
    manual_session_id = "wx:manual:session-a"

    explain_before = client.get(
        "/platform/session-routing",
        params={
            "platform": "wx",
            "user_id": "wx-route-user",
            "chat_type": "private",
        },
        headers=admin_headers,
    )
    assert explain_before.status_code == 200
    assert explain_before.json()["explain"]["routing_mode"] == "auto"
    assert explain_before.json()["explain"]["auto_session_id"] == auto_session_id
    assert explain_before.json()["explain"]["final_session_id"] == auto_session_id
    assert explain_before.json()["explain"]["override"]["exists"] is False

    set_response = client.post(
        "/platform/session-routing/override",
        json={
            "platform": "wx",
            "user_id": "wx-route-user",
            "chat_type": "private",
            "session_id": manual_session_id,
            "operator": "tester",
            "reason": "switch to manual session",
        },
        headers=admin_headers,
    )
    assert set_response.status_code == 200
    set_data = set_response.json()
    assert set_data["explain"]["routing_mode"] == "override"
    assert set_data["explain"]["auto_session_id"] == auto_session_id
    assert set_data["explain"]["final_session_id"] == manual_session_id
    assert set_data["explain"]["override"]["active"] is True

    first_message = client.post(
        "/platform/openclaw/message",
        json={
            "platform": "wx",
            "user_id": "wx-route-user",
            "chat_type": "private",
            "message": "走人工指定会话",
        },
    )
    assert first_message.status_code == 200
    assert first_message.json()["session_id"] == manual_session_id

    manual_messages = get_session_messages(manual_session_id)
    assert [item["content"] for item in manual_messages] == [
        "走人工指定会话",
        "reply:走人工指定会话",
    ]
    assert get_session_messages(auto_session_id) == []
    manual_metadata = manual_messages[0]["metadata"] or {}
    assert manual_metadata["routing"]["routing_mode"] == "override"
    assert manual_metadata["routing"]["auto_session_id"] == auto_session_id
    assert manual_metadata["routing"]["final_session_id"] == manual_session_id
    assert manual_messages[0]["preview_payload"]["preview"]["current_user_message"] == "走人工指定会话"
    assert get_relationship_state_for_api(manual_session_id)["conversation_count"] == 1

    clear_response = client.post(
        "/platform/session-routing/clear",
        json={
            "platform": "wx",
            "user_id": "wx-route-user",
            "chat_type": "private",
            "operator": "tester",
            "reason": "back to auto",
        },
        headers=admin_headers,
    )
    assert clear_response.status_code == 200
    clear_data = clear_response.json()
    assert clear_data["cleared"] is True
    assert clear_data["explain"]["routing_mode"] == "auto"
    assert clear_data["explain"]["final_session_id"] == auto_session_id
    assert clear_data["explain"]["override"]["exists"] is True
    assert clear_data["explain"]["override"]["active"] is False

    second_message = client.post(
        "/platform/openclaw/message",
        json={
            "platform": "wx",
            "user_id": "wx-route-user",
            "chat_type": "private",
            "message": "恢复自动归属",
        },
    )
    assert second_message.status_code == 200
    assert second_message.json()["session_id"] == auto_session_id

    auto_messages = get_session_messages(auto_session_id)
    assert [item["content"] for item in auto_messages] == [
        "恢复自动归属",
        "reply:恢复自动归属",
    ]
    auto_metadata = auto_messages[0]["metadata"] or {}
    assert auto_metadata["routing"]["routing_mode"] == "auto"
    assert auto_metadata["routing"]["final_session_id"] == auto_session_id
    assert get_relationship_state_for_api(auto_session_id)["conversation_count"] == 1

    manual_messages_after = get_session_messages(manual_session_id)
    assert [item["content"] for item in manual_messages_after] == [
        "走人工指定会话",
        "reply:走人工指定会话",
    ]


def test_platform_session_routing_override_is_scoped_by_account_id(client, admin_headers, monkeypatch):
    _patch_turn_dependencies(monkeypatch)

    set_response = client.post(
        "/platform/session-routing/override",
        json={
            "platform": "wx",
            "account_id": "wx-main",
            "user_id": "wx-account-user",
            "chat_type": "private",
            "session_id": "wx:manual:main-account",
        },
        headers=admin_headers,
    )
    assert set_response.status_code == 200

    main_response = client.post(
        "/platform/openclaw/message",
        json={
            "platform": "wx",
            "account_id": "wx-main",
            "user_id": "wx-account-user",
            "chat_type": "private",
            "message": "主账号命中 override",
        },
    )
    assert main_response.status_code == 200
    assert main_response.json()["session_id"] == "wx:manual:main-account"

    alt_response = client.post(
        "/platform/openclaw/message",
        json={
            "platform": "wx",
            "account_id": "wx-alt",
            "user_id": "wx-account-user",
            "chat_type": "private",
            "message": "副账号走自动归属",
        },
    )
    assert alt_response.status_code == 200
    assert alt_response.json()["session_id"] == "wx:private:wx-account-user"

    main_metadata = get_session_messages("wx:manual:main-account")[0]["metadata"] or {}
    assert main_metadata["account_id"] == "wx-main"
    assert main_metadata["routing"]["routing_mode"] == "override"
    assert main_metadata["routing"]["routing_key"] == "wx:wx-main:private:wx-account-user"

    alt_metadata = get_session_messages("wx:private:wx-account-user")[0]["metadata"] or {}
    assert alt_metadata["account_id"] == "wx-alt"
    assert alt_metadata["routing"]["routing_mode"] == "auto"
    assert alt_metadata["routing"]["routing_key"] == "wx:wx-alt:private:wx-account-user"
