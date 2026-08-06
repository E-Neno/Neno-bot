from app.services.chat.chat_executive import (
    ExecutiveDecision,
    build_output_guidance,
    decide_chat_turn_sync,
    enforce_executive_runtime_capabilities,
    fallback_executive_decision,
    parse_executive_decision,
)
from app.services.chat.inner_deliberation import InnerImpulse
from app.services.chat.selection_layer import SelectionDecision


def test_parse_executive_decision_accepts_main_brain_commands_and_clamps_limits():
    raw = """{
      "action":"reply_now",
      "reason":"这件事值得认真接住",
      "response_points":["先确认对方现在是否安全","别急着给方案"],
      "max_chars":999,
      "max_beats":8,
      "inner_reaction":"心里一沉，但不想表演关心",
      "world_intents":["晚点仍惦记这件事"],
      "memory_candidates":["对方今天被裁员"]
    }"""

    decision = parse_executive_decision(raw, fallback_message="我今天被裁了")

    assert decision.action == "reply_now"
    assert decision.max_chars == 240
    assert decision.max_beats == 3
    assert decision.world_intents == ["晚点仍惦记这件事"]
    assert decision.inner_reaction.startswith("心里一沉")


def test_parse_executive_bad_json_falls_back_to_reply():
    decision = parse_executive_decision("不是 JSON", fallback_message="在吗")
    assert decision == fallback_executive_decision("在吗")
    assert decision.action == "reply_now"


def test_defer_fails_open_to_reply_when_no_reconsideration_channel_exists():
    decision = ExecutiveDecision(
        action="defer",
        reason="现在不想回",
        response_points=[],
        max_chars=0,
        max_beats=1,
    )

    normalized = enforce_executive_runtime_capabilities(
        decision,
        can_defer=False,
        fallback_message="在吗",
    )

    assert normalized.action == "reply_now"
    assert normalized.response_points


def test_main_executive_sees_state_triage_and_private_impulses():
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return '{"action":"defer","reason":"现在不想硬回","response_points":[],"max_chars":0,"max_beats":1,"inner_reaction":"累","world_intents":[],"memory_candidates":[]}'

    result = decide_chat_turn_sync(
        message="你在吗",
        batch=[{"id": 7, "content": "你在吗"}],
        state={"state": "刚忙完，很累", "relationship": "熟悉"},
        triage=SelectionDecision(
            focus=[7], ignore=[], hooked_by=None, reply_strategy="single",
            should_respond=False, depth="deep",
        ),
        impulses=[InnerImpulse("boundary", "想躲一下", "先别硬撑", 0.8)],
        model_name="main-model",
        trace_id="trace-exec",
        request_client=fake_request,
    )

    prompt = captured["messages"][-1]["content"]
    assert "刚忙完，很累" in prompt
    assert "先别硬撑" in prompt
    assert "TRIAGE" in prompt
    assert result.action == "defer"


def test_main_executive_receives_current_images_without_text_flattening():
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return '{"action":"reply_now","reason":"看见了","response_points":["回应图片本身"],"max_chars":40,"max_beats":1,"inner_reaction":"","world_intents":[],"memory_candidates":[]}'

    decide_chat_turn_sync(
        message="你看这个",
        batch=[{"id": 8, "content": "你看这个"}],
        state={},
        triage=SelectionDecision(
            focus=[8], ignore=[], hooked_by=None, reply_strategy="single",
            should_respond=True, depth="shallow",
        ),
        impulses=[],
        model_name="main-model",
        current_turn_image_inputs=["data:image/png;base64,abc"],
        request_client=fake_request,
    )

    content = captured["messages"][-1]["content"]
    assert content[0]["type"] == "text"
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,abc"},
    }


def test_output_guidance_contains_only_decision_surface_not_private_state():
    decision = ExecutiveDecision(
        action="reply_now",
        reason="private reason",
        response_points=["接住他被裁这件事", "先问他现在怎么样"],
        max_chars=42,
        max_beats=1,
        inner_reaction="心里一沉",
        world_intents=["晚上继续惦记"],
        memory_candidates=["对方被裁员"],
    )

    guidance = build_output_guidance(decision)

    assert "接住他被裁这件事" in guidance
    assert "42" in guidance and "1" in guidance
    assert "心里一沉" not in guidance
    assert "晚上继续惦记" not in guidance
    assert "private reason" not in guidance
