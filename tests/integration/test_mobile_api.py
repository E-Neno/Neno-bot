from __future__ import annotations

from typing import Any


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
        "attachments": False,
        "notifications": False,
        "quick_reply": False,
    }


def test_mobile_conversations_returns_chinese_contacts(client, monkeypatch):
    response = client.get("/mobile/conversations", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    data = response.json()
    titles = [item["title"] for item in data["conversations"]]
    assert titles[:3] == ["Neno", "写作助手", "代码助手"]
    assert data["conversations"][0]["id"] == "neno"
    assert data["conversations"][0]["pinned"] is True
    assert data["conversations"][0]["kind"] == "primary"


def test_mobile_messages_do_not_expose_debug_fields(client, monkeypatch):
    from app.storage.db import add_message

    add_message("mobile:neno", "user", "在吗", trace_id="trace-mobile")
    add_message("mobile:neno", "assistant", "在。", trace_id="trace-mobile")

    response = client.get("/mobile/conversations/neno/messages", headers=mobile_headers(monkeypatch))

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "neno"
    assert [item["text"] for item in body["messages"]] == ["在吗", "在。"]
    encoded = str(body)
    assert "candidate_memory_debug" not in encoded
    assert "relationship_context" not in encoded
    assert "metadata_json" not in encoded


def test_mobile_send_message_uses_mobile_source_and_returns_public_shape(client, monkeypatch):
    import app.services.mobile_api_service as mobile_service

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
        return {
            "reply": "在。",
            "trace_id": trace_id,
            "user_message_id": 201,
            "assistant_message_id": 202,
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
        "id": 201,
        "role": "user",
        "text": "在吗",
        "created_at": None,
        "pending": False,
    }
    assert body["assistant_message"] == {
        "id": 202,
        "role": "assistant",
        "text": "在。",
        "created_at": None,
        "pending": False,
    }
    assert captured["session_id"] == "mobile:neno"
    assert captured["message"] == "在吗"
    assert captured["trace_id"]
    assert captured["input_record"]["source"] == "mobile"
    assert captured["input_record"]["message_type"] == "text"


def test_mobile_send_message_handles_silent_reply(client, monkeypatch):
    """选择层选择不回 / 在场门控暂存时，assistant_message_id 为 None。
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

