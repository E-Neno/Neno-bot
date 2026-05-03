from __future__ import annotations

from collections.abc import Iterable

from app.schemas import MediaAttachment
from app.services.chat.llm_gateway import generate_multimodal_chat_reply
from app.utils.logging_utils import log_event

SUPPORTED_INPUT_KINDS = {"image"}
MULTIMODAL_USER_ERROR_MESSAGE = "这张图我刚刚没看清，你再发一次试试。"
MAX_IMAGE_CONTENT_LENGTH = 120
MAX_JUDGMENT_LENGTH = 60


class MultimodalInputError(RuntimeError):
    pass


def normalize_multimodal_message(
    *,
    message: str | None,
    attachments: Iterable[MediaAttachment] | None,
    trace_id: str | None = None,
) -> str:
    base_message = (message or "").strip()
    normalized_attachments = [item for item in (attachments or []) if item.kind in SUPPORTED_INPUT_KINDS]

    if not normalized_attachments:
        return base_message

    primary = normalized_attachments[0]
    if primary.kind != "image":
        return base_message

    log_event(
        "multimodal",
        "image_attachment_detected",
        trace_id=trace_id,
        kind=primary.kind,
        source=primary.source,
        has_url=bool(primary.url),
        text_hint=bool(primary.text_hint),
        message_len=len(base_message),
    )

    if not primary.url:
        log_event(
            "multimodal",
            "image_attachment_missing_url",
            trace_id=trace_id,
            kind=primary.kind,
            source=primary.source,
        )
        raise MultimodalInputError("image attachment missing url")

    prompt = build_image_understanding_prompt(base_message, primary)
    log_event(
        "multimodal",
        "multimodal_normalize_start",
        trace_id=trace_id,
        kind=primary.kind,
        source=primary.source,
        prompt_len=len(prompt),
        attachment_count=len(normalized_attachments),
    )
    try:
        result = generate_multimodal_chat_reply(
            text_prompt=prompt,
            attachments=[primary],
            trace_id=trace_id,
        ).strip()
    except Exception as exc:  # pragma: no cover - provider failures are surfaced to API
        log_event(
            "multimodal",
            "multimodal_normalize_failed",
            trace_id=trace_id,
            kind=primary.kind,
            source=primary.source,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise MultimodalInputError("image understanding failed") from exc

    if not result:
        log_event(
            "multimodal",
            "multimodal_normalize_failed",
            trace_id=trace_id,
            kind=primary.kind,
            source=primary.source,
            error_type="EmptyResult",
            error_message="image understanding returned empty result",
        )
        raise MultimodalInputError("image understanding returned empty result")

    result = format_image_understanding_result(result, base_message)

    log_event(
        "multimodal",
        "multimodal_normalize_ok",
        trace_id=trace_id,
        kind=primary.kind,
        source=primary.source,
        text_hint=bool(primary.text_hint),
        has_user_text=bool(base_message),
        prompt_len=len(prompt),
        result_len=len(result),
    )
    return result


def build_image_understanding_prompt(message: str, attachment: MediaAttachment) -> str:
    user_text = message.strip()
    hint_text = (attachment.text_hint or "").strip()

    lines = [
        "你在为一个聊天系统做图片输入理解。",
        "任务：输出给聊天主链看的图片理解结果，不要改写成像用户本人在空口描述图片的普通聊天句子。",
        "要求：",
        "1. 必须明确保留“用户已经真实发送了一张图片”这个事实，避免让后续模型误以为用户没有发图。",
        "2. 先写客观可见的图片内容，再决定是否补充很弱的主观判断；不要先写氛围、情绪、治愈、梦幻、温柔之类评价。",
        "3. 如果图片里有明确可读文字，优先提取并概括这些文字和画面主体。",
        "4. 如果用户同时发了文字，要结合文字理解，并单独保留“用户附带文字”这一项。",
        "5. 输出要简洁稳定，严格使用下面格式，不要添加额外开场白、解释或对话语气。",
        "固定输出格式：",
        "[用户发送了一张图片，以下是图片理解结果]",
        "图片内容：<客观描述>",
        "用户附带文字：<仅在用户确实附带文字时输出>",
        "补充判断：<可选，且只能放在最后>",
    ]
    if user_text:
        lines.append(f"用户附带文本：{user_text}")
    if hint_text:
        lines.append(f"平台附带提示：{hint_text}")
    lines.append("请直接输出归一化后的用户输入。")
    return "\n".join(lines)


def format_image_understanding_result(result: str, message: str) -> str:
    user_text = message.strip()
    cleaned_lines = [line.strip() for line in result.splitlines() if line.strip()]

    image_content = ""
    extra_lines: list[str] = []
    has_header = False
    for line in cleaned_lines:
        if line.startswith("[用户发送了一张图片"):
            has_header = True
            continue
        if line.startswith("图片内容："):
            image_content = line.split("：", 1)[1].strip()
            continue
        if line.startswith("用户附带文字："):
            continue
        if line.startswith("补充判断："):
            extra_lines.append(line)
            continue
        if not image_content:
            image_content = line
            continue
        extra_lines.append(line)

    if not image_content:
        image_content = result.strip()

    image_content = truncate_text(image_content, MAX_IMAGE_CONTENT_LENGTH)

    formatted_lines = ["[用户发送了一张图片，以下是图片理解结果]"]
    formatted_lines.append(f"图片内容：{image_content}")

    if user_text:
        formatted_lines.append(f"用户附带文字：{user_text}")

    if has_header:
        for line in extra_lines:
            if line not in formatted_lines:
                if line.startswith("补充判断："):
                    judgment = truncate_text(line.split("：", 1)[1].strip(), MAX_JUDGMENT_LENGTH)
                    if judgment:
                        formatted_lines.append(f"补充判断：{judgment}")
                    continue
                formatted_lines.append(line)
    else:
        for line in extra_lines:
            if line.startswith("用户附带文字：") or line.startswith("补充判断："):
                if line.startswith("补充判断："):
                    judgment = truncate_text(line.split("：", 1)[1].strip(), MAX_JUDGMENT_LENGTH)
                    if judgment:
                        formatted_lines.append(f"补充判断：{judgment}")
                    continue
                formatted_lines.append(line)

    return "\n".join(formatted_lines)


def truncate_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: limit - 1].rstrip("，。；;、 ")
    return f"{shortened}…"
