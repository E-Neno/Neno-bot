from __future__ import annotations

from unittest.mock import patch

import pytest


MESSAGE = "今天有点烦"
STAGE_PRESETS = [
    (
        {
            "stage": 0,
            "conversation_count": 0,
            "familiarity_score": 0,
            "trust_score": 0,
            "emotional_depth_score": 0,
            "boundary_score": 0,
        },
        "陌生",
        "当前阶段：陌生。",
    ),
    (
        {
            "stage": 2,
            "conversation_count": 45,
            "familiarity_score": 28,
            "trust_score": 8,
            "emotional_depth_score": 5,
            "boundary_score": 10,
        },
        "稳定聊天对象",
        "当前阶段：稳定聊天对象。",
    ),
    (
        {
            "stage": 4,
            "conversation_count": 300,
            "familiarity_score": 120,
            "trust_score": 80,
            "emotional_depth_score": 70,
            "boundary_score": 40,
        },
        "深度陪伴",
        "当前阶段：深度陪伴。",
    ),
]


def fake_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
    del trace_id
    content = messages[-1]["content"]
    context_text = str(content[0].get("text", "")) if isinstance(content, list) else ""
    user_text = str(content[-1].get("text", "")) if isinstance(content, list) else str(content)
    stage_by_prompt = {
        "你和对方刚开始聊天，还不熟。": "当前阶段：陌生。",
        "你和对方算稳定聊天对象了，互相有点了解。": "当前阶段：稳定聊天对象。",
        "你和对方已经很熟了，不需要任何表演。": "当前阶段：深度陪伴。",
    }
    stage_line = next(
        stage for prompt_line, stage in stage_by_prompt.items()
        if prompt_line in context_text
    )
    user_message = user_text.split("【对方刚说】\n", 1)[-1].strip()
    return f"{stage_line} | mock reply to: {user_message}"


def fake_process_memory_candidate(message: str, trace_id: str | None = None, input_record: dict | None = None) -> dict:
    del message, trace_id, input_record
    return {
        "candidate_memory_decision": {
            "action": "ignore",
            "reason": "integration test stub",
            "risk_level": "low",
        },
        "candidate_memory": None,
        "candidate_memory_debug": None,
        "auto_added_memory": False,
    }


@pytest.mark.parametrize(("preset", "stage_label", "stage_prompt_line"), STAGE_PRESETS)
def test_relationship_stage_update_affects_chat_context_and_reply(
    client,
    admin_headers: dict[str, str],
    preset: dict[str, int],
    stage_label: str,
    stage_prompt_line: str,
) -> None:
    session_id = f"integration-relationship-{preset['stage']}"

    update_response = client.post(
        "/relationship/update",
        json={**preset, "session_id": session_id},
        headers=admin_headers,
    )
    assert update_response.status_code == 200
    updated_state = update_response.json()
    assert updated_state["stage"] == preset["stage"]
    assert updated_state["stage_label"] == stage_label

    state_response = client.get("/relationship/state", params={"session_id": session_id})
    assert state_response.status_code == 200
    assert state_response.json()["stage_label"] == stage_label

    with patch(
        "app.services.chat.turn_orchestrator.generate_chat_reply",
        side_effect=fake_generate_chat_reply,
    ), patch(
        "app.services.chat.turn_orchestrator.process_memory_candidate",
        side_effect=fake_process_memory_candidate,
    ):
        chat_response = client.post(
            "/chat",
            json={"session_id": session_id, "message": MESSAGE},
        )

    assert chat_response.status_code == 200
    payload = chat_response.json()

    assert payload["reply"].startswith(stage_prompt_line)
    expected_context_first_line = {
        0: "\u4f60\u548c\u5bf9\u65b9\u521a\u5f00\u59cb\u804a\u5929\uff0c\u8fd8\u4e0d\u719f\u3002",
        2: "\u4f60\u548c\u5bf9\u65b9\u7b97\u7a33\u5b9a\u804a\u5929\u5bf9\u8c61\u4e86\uff0c\u4e92\u76f8\u6709\u70b9\u4e86\u89e3\u3002",
        4: "\u4f60\u548c\u5bf9\u65b9\u5df2\u7ecf\u5f88\u719f\u4e86\uff0c\u4e0d\u9700\u8981\u4efb\u4f55\u8868\u6f14\u3002",
    }[preset["stage"]]
    assert (
        payload["relationship_context"].splitlines()[0].strip()
        == expected_context_first_line
    )
    assert payload["candidate_memory"] is None
    assert payload["used_memories"] == []

    relationship_state = payload["relationship_state"]
    assert relationship_state["stage_label"] == stage_label
    assert relationship_state["conversation_count"] == preset["conversation_count"] + 1


def test_app_root_smoke(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
