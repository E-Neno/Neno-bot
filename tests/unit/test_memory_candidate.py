import pytest
import json
from unittest.mock import patch

from app.services.chat.memory_candidate_service import process_memory_candidate

@pytest.mark.parametrize("name,message,input_record,mocked_candidate,expected_action,expected_auto_added", [
    (
        "voice_project_auto_add",
        "我最近在准备雅思口语",
        {
            "message_type": "voice",
            "raw_input": "我最近在准备雅思口语",
            "normalized_input": "我最近在准备雅思口语",
        },
        {
            "should_store": True,
            "content": "用户最近在准备雅思口语",
            "memory_type": "project",
        },
        "auto_add",
        True,
    ),
    (
        "image_scene_ignore",
        "[用户发送了一张图片，以下是图片理解结果]\n图片内容：桌上放着一杯咖啡和一本书",
        {
            "message_type": "image",
            "raw_input": "",
            "normalized_input": "[用户发送了一张图片，以下是图片理解结果]\n图片内容：桌上放着一杯咖啡和一本书",
        },
        {
            "should_store": True,
            "content": "用户刚刚拍了一张桌上有咖啡和书的照片",
            "memory_type": "profile",
        },
        "ignore",
        False,
    ),
    (
        "image_project_needs_confirm",
        "[用户发送了一张图片，以下是图片理解结果]\n图片内容：用户的电脑屏幕是一个名为 Neno 控制台的项目看板\n用户附带文字：这是我最近在做的项目",
        {
            "message_type": "image",
            "raw_input": "这是我最近在做的项目",
            "normalized_input": "[用户发送了一张图片，以下是图片理解结果]\n图片内容：用户的电脑屏幕是一个名为 Neno 控制台的项目看板\n用户附带文字：这是我最近在做的项目",
        },
        {
            "should_store": True,
            "content": "用户正在做 Neno 控制台项目",
            "memory_type": "project",
        },
        "needs_confirm",
        False,
    ),
    (
        "text_project_auto_add",
        "我最近在做 Neno 控制台改版",
        {
            "message_type": "text",
            "raw_input": "我最近在做 Neno 控制台改版",
            "normalized_input": "我最近在做 Neno 控制台改版",
        },
        {
            "should_store": True,
            "content": "用户最近在做 Neno 控制台改版",
            "memory_type": "project",
        },
        "auto_add",
        True,
    ),
])
def test_memory_candidate_processing(name, message, input_record, mocked_candidate, expected_action, expected_auto_added):
    added_memories = []

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
    auto_added = bool(result["auto_added_memory"])

    assert decision["action"] == expected_action
    assert auto_added == expected_auto_added
