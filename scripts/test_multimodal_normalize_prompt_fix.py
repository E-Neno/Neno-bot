from app.schemas import MediaAttachment
from app.services.chat import multimodal_input_service as service


def make_attachment() -> MediaAttachment:
    return MediaAttachment(
        kind="image",
        url="https://example.com/test.jpg",
        source="wx",
    )


def run_case(name: str, message: str | None, model_output: str) -> str:
    original = service.generate_multimodal_chat_reply

    def fake_generate_multimodal_chat_reply(*, text_prompt: str, attachments: list[MediaAttachment], trace_id: str | None = None) -> str:
        assert "[用户发送了一张图片，以下是图片理解结果]" in text_prompt
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

    print(f"== {name} ==")
    print(normalized)
    print()
    assert normalized.startswith("[用户发送了一张图片，以下是图片理解结果]")
    assert "图呢" not in normalized
    return normalized


def main() -> None:
    pure_image = run_case(
        "pure_image",
        None,
        "这张图氛围好温柔，一个长发女孩举着黑色玩偶，逆光下很梦幻。",
    )
    assert "图片内容：这张图氛围好温柔，一个长发女孩举着黑色玩偶，逆光下很梦幻。" in pure_image

    image_with_question = run_case(
        "image_with_question",
        "这张图你能看到什么？",
        "[用户发送了一张图片，以下是图片理解结果]\n图片内容：一名长发女孩背对镜头，头发上有黑色蝴蝶结，手中举着深色玩偶，整体是逆光场景。",
    )
    assert "用户附带文字：这张图你能看到什么？" in image_with_question

    image_with_comment = run_case(
        "image_with_comment",
        "今天拍得还不错吧",
        "图片内容：一名长发女孩背对镜头，举着深色玩偶，处在逆光环境中。\n补充判断：整体像是偏柔和的人像风格。",
    )
    assert "用户附带文字：今天拍得还不错吧" in image_with_comment
    assert "补充判断：整体像是偏柔和的人像风格。" in image_with_comment

    print("all multimodal normalization checks passed")


if __name__ == "__main__":
    main()
