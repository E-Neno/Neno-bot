import pytest
from fastapi import HTTPException

from app.routers.chat import chat
from app.schemas import ChatRequest, MediaAttachment
from app.services.chat import multimodal_input_service as service

def make_request(message: str = "") -> ChatRequest:
    return ChatRequest(
        session_id="test-multimodal-polish",
        message=message,
        attachments=[
            MediaAttachment(
                kind="image",
                url="https://example.com/test.jpg",
                media_path="/tmp/test.jpg",
                source="wx",
            )
        ],
    )

def test_normalized_structure() -> None:
    original = service.generate_multimodal_chat_reply

    def fake_generate_multimodal_chat_reply(*, text_prompt: str, attachments: list[MediaAttachment], trace_id: str | None = None) -> str:
        assert "[用户发送了一张图片，以下是图片理解结果]" in text_prompt
        return (
            "[用户发送了一张图片，以下是图片理解结果]\n"
            "图片内容：一只橘猫坐在地面上，眼睛看向镜头，后面还有一些杂乱背景和很多不重要的环境描述，"
            "这些描述如果太长会稀释用户真正的问题，所以这里故意写得比较长一点看看会不会被收住。\n"
            "用户附带文字：你能看懂它在想什么吗\n"
            "补充判断：整体氛围很温柔很治愈很梦幻，还带着一点发呆的感觉。"
        )

    service.generate_multimodal_chat_reply = fake_generate_multimodal_chat_reply
    try:
        normalized = service.normalize_multimodal_message(
            message="这张图你能看到什么？",
            attachments=make_request().attachments,
            trace_id="test-structure",
        )
    finally:
        service.generate_multimodal_chat_reply = original

    assert normalized.startswith("[用户发送了一张图片，以下是图片理解结果]")
    assert "用户附带文字：这张图你能看到什么？" in normalized
    assert "用户附带文字：你能看懂它在想什么吗" not in normalized

def test_user_facing_failure_message() -> None:
    original = service.generate_multimodal_chat_reply

    def fake_generate_multimodal_chat_reply(*, text_prompt: str, attachments: list[MediaAttachment], trace_id: str | None = None) -> str:
        raise RuntimeError("provider timeout")

    service.generate_multimodal_chat_reply = fake_generate_multimodal_chat_reply
    try:
        with pytest.raises(HTTPException) as excinfo:
            chat(make_request("这张图你能看到什么？"))
        
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == service.MULTIMODAL_USER_ERROR_MESSAGE
    finally:
        service.generate_multimodal_chat_reply = original
