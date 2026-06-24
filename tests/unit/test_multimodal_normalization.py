import pytest
from app.schemas import MediaAttachment
from app.services.chat import multimodal_input_service as service

def make_attachment() -> MediaAttachment:
    return MediaAttachment(
        kind="image",
        url="https://example.com/test.jpg",
        source="wx",
    )


def test_multimodal_normalization_accepts_local_mobile_image(tmp_path):
    image = tmp_path / "mobile.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    attachment = MediaAttachment(
        kind="image",
        media_path=str(image),
        mime_type="image/png",
        source="mobile",
    )
    original = service.generate_multimodal_chat_reply

    def fake_generate_multimodal_chat_reply(
        *, text_prompt: str, attachments: list[MediaAttachment], trace_id: str | None = None
    ) -> str:
        assert attachments[0].media_path == str(image)
        return "image content"

    service.generate_multimodal_chat_reply = fake_generate_multimodal_chat_reply
    try:
        normalized = service.normalize_multimodal_message(
            message="look",
            attachments=[attachment],
            trace_id="test-local-mobile-image",
        )
    finally:
        service.generate_multimodal_chat_reply = original

    assert "image content" in normalized


@pytest.mark.parametrize("name,message,model_output,expected_text_in_prompt,expected_in_result", [
    (
        "pure_image",
        None,
        "这张图氛围好温柔，一个长发女孩举着黑色玩偶，逆光下很梦幻。",
        "[用户发送了一张图片，以下是图片理解结果]",
        "图片内容：这张图氛围好温柔，一个长发女孩举着黑色玩偶，逆光下很梦幻。",
    ),
    (
        "image_with_question",
        "这张图你能看到什么？",
        "[用户发送了一张图片，以下是图片理解结果]\n图片内容：一名长发女孩背对镜头，头发上有黑色蝴蝶结，手中举着深色玩偶，整体是逆光场景。",
        "[用户发送了一张图片，以下是图片理解结果]",
        "用户附带文字：这张图你能看到什么？",
    ),
    (
        "image_with_comment",
        "今天拍得还不错吧",
        "图片内容：一名长发女孩背对镜头，举着深色玩偶，处在逆光环境中。\n补充判断：整体像是偏柔和的人像风格。",
        "[用户发送了一张图片，以下是图片理解结果]",
        "用户附带文字：今天拍得还不错吧",
    ),
])
def test_multimodal_normalization_prompt_fix(name, message, model_output, expected_text_in_prompt, expected_in_result):
    original = service.generate_multimodal_chat_reply

    def fake_generate_multimodal_chat_reply(*, text_prompt: str, attachments: list[MediaAttachment], trace_id: str | None = None) -> str:
        assert expected_text_in_prompt in text_prompt
        assert "像用户本人发给 Neno 的一句话" not in text_prompt
        assert attachments[0].kind == "image"
        return model_output

    service.generate_multimodal_chat_reply = fake_generate_multimodal_chat_reply
    try:
        normalized = service.normalize_multimodal_message(
            message=message,
            attachments=[make_attachment()],
            trace_id=f"test-{name}",
        )
    finally:
        service.generate_multimodal_chat_reply = original

    assert normalized.startswith("[用户发送了一张图片，以下是图片理解结果]")
    assert "图呢" not in normalized
    assert expected_in_result in normalized
