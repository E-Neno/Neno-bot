import json
from unittest.mock import patch

from app.services.chat.memory_candidate_service import process_memory_candidate


def run_case(name: str, message: str, input_record: dict, mocked_candidate: dict, expected_action: str, expected_auto_added: bool):
    added_memories: list[tuple[str, str]] = []

    def fake_add_memory(content: str, memory_type: str = "general"):
      added_memories.append((content, memory_type))

    with patch(
        "app.services.chat.memory_candidate_service.request_model_response",
        return_value=json.dumps(mocked_candidate, ensure_ascii=False),
    ), patch(
        "app.services.memory_candidate_decision_service.find_similar_memories",
        return_value=[],
    ), patch(
        "app.services.memory_candidate_decision_service.memory_exists",
        return_value=False,
    ), patch(
        "app.services.memory_candidate_decision_service.add_memory",
        side_effect=fake_add_memory,
    ):
        result = process_memory_candidate(
            message,
            trace_id=f"case-{name}",
            input_record=input_record,
        )

    decision = result["candidate_memory_decision"]
    candidate_debug = result.get("candidate_memory_debug") or {}
    auto_added = bool(result["auto_added_memory"])

    assert decision["action"] == expected_action, f"{name}: expected action={expected_action}, got {decision['action']}"
    assert auto_added == expected_auto_added, f"{name}: expected auto_added={expected_auto_added}, got {auto_added}"

    print(f"[{name}]")
    print(f"  source={candidate_debug.get('source_modality')}")
    print(f"  candidate={candidate_debug.get('content')!r}")
    print(f"  action={decision.get('action')} risk={decision.get('risk_level')} auto_added={auto_added}")
    print(f"  reason={decision.get('reason')}")
    if added_memories:
        print(f"  stored={added_memories}")
    print()


def main():
    run_case(
        name="voice_project_auto_add",
        message="我最近在准备雅思口语",
        input_record={
            "message_type": "voice",
            "raw_input": "我最近在准备雅思口语",
            "normalized_input": "我最近在准备雅思口语",
        },
        mocked_candidate={
            "should_store": True,
            "content": "用户最近在准备雅思口语",
            "memory_type": "project",
        },
        expected_action="auto_add",
        expected_auto_added=True,
    )

    run_case(
        name="image_scene_ignore",
        message="[用户发送了一张图片，以下是图片理解结果]\n图片内容：桌上放着一杯咖啡和一本书",
        input_record={
            "message_type": "image",
            "raw_input": "",
            "normalized_input": "[用户发送了一张图片，以下是图片理解结果]\n图片内容：桌上放着一杯咖啡和一本书",
        },
        mocked_candidate={
            "should_store": True,
            "content": "用户刚刚拍了一张桌上有咖啡和书的照片",
            "memory_type": "profile",
        },
        expected_action="ignore",
        expected_auto_added=False,
    )

    run_case(
        name="image_project_needs_confirm",
        message="[用户发送了一张图片，以下是图片理解结果]\n图片内容：用户的电脑屏幕是一个名为 Neno 控制台的项目看板\n用户附带文字：这是我最近在做的项目",
        input_record={
            "message_type": "image",
            "raw_input": "这是我最近在做的项目",
            "normalized_input": "[用户发送了一张图片，以下是图片理解结果]\n图片内容：用户的电脑屏幕是一个名为 Neno 控制台的项目看板\n用户附带文字：这是我最近在做的项目",
        },
        mocked_candidate={
            "should_store": True,
            "content": "用户正在做 Neno 控制台项目",
            "memory_type": "project",
        },
        expected_action="needs_confirm",
        expected_auto_added=False,
    )

    run_case(
        name="text_project_auto_add",
        message="我最近在做 Neno 控制台改版",
        input_record={
            "message_type": "text",
            "raw_input": "我最近在做 Neno 控制台改版",
            "normalized_input": "我最近在做 Neno 控制台改版",
        },
        mocked_candidate={
            "should_store": True,
            "content": "用户最近在做 Neno 控制台改版",
            "memory_type": "project",
        },
        expected_action="auto_add",
        expected_auto_added=True,
    )


if __name__ == "__main__":
    main()
