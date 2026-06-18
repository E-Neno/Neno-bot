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
        "你和对方还没太熟，关系还在慢慢建立。",
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
        "你和对方开始熟起来了，聊着比一开始自然一点。",
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
        "你和对方已经很亲近了，像能说心里话的人。",
    ),
]


def fake_generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
    del trace_id
    content = messages[-1]["content"]
    context_text = str(content[0].get("text", "")) if isinstance(content, list) else ""
    user_text = str(content[-1].get("text", "")) if isinstance(content, list) else str(content)
    stage_by_prompt = {
        "你和对方还没太熟，关系还在慢慢建立。": "当前阶段：陌生。",
        "你和对方开始熟起来了，聊着比一开始自然一点。": "当前阶段：稳定聊天对象。",
        "你和对方已经很亲近了，像能说心里话的人。": "当前阶段：深度陪伴。",
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


@pytest.mark.parametrize(
    ("preset", "stage_label", "stage_prompt_line", "relationship_phrase"),
    STAGE_PRESETS,
)
def test_relationship_stage_update_affects_chat_context_and_reply(
    client,
    admin_headers: dict[str, str],
    preset: dict[str, int],
    stage_label: str,
    stage_prompt_line: str,
    relationship_phrase: str,
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
    assert payload["relationship_context"].strip() == relationship_phrase
    assert payload["candidate_memory"] is None
    assert payload["used_memories"] == []

    relationship_state = payload["relationship_state"]
    assert relationship_state["stage_label"] == stage_label
    assert relationship_state["conversation_count"] == preset["conversation_count"] + 1


def test_app_root_smoke(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
