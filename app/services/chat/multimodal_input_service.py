from __future__ import annotations

from collections.abc import Iterable

from app.schemas import MediaAttachment
from app.services.chat.llm_gateway import generate_multimodal_chat_reply
from app.utils.logging_utils import log_event

SUPPORTED_INPUT_KINDS = {"image"}


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

    if not primary.url:
        raise MultimodalInputError("image attachment missing url")

    prompt = build_image_understanding_prompt(base_message, primary)
    try:
        result = generate_multimodal_chat_reply(
            text_prompt=prompt,
            attachments=[primary],
            trace_id=trace_id,
        ).strip()
    except Exception as exc:  # pragma: no cover - provider failures are surfaced to API
        log_event(
            "multimodal",
            "image_understanding_failed",
            trace_id=trace_id,
            kind=primary.kind,
            source=primary.source,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise MultimodalInputError("image understanding failed") from exc

    if not result:
        raise MultimodalInputError("image understanding returned empty result")

    log_event(
        "multimodal",
        "image_understanding_ok",
        trace_id=trace_id,
        kind=primary.kind,
        source=primary.source,
        text_hint=bool(primary.text_hint),
        prompt_len=len(prompt),
        result_len=len(result),
    )
    return result


def build_image_understanding_prompt(message: str, attachment: MediaAttachment) -> str:
    user_text = message.strip()
    hint_text = (attachment.text_hint or "").strip()

    lines = [
        "你在为一个聊天系统做图片输入理解。",
        "任务：把这张图片理解成一段适合继续聊天主链处理的中文用户输入。",
        "要求：",
        "1. 只输出给聊天主链看的文本，不要解释你是视觉模型。",
        "2. 如果图片里有明确可读文字，优先概括用户可能想表达或让你看的内容。",
        "3. 如果用户同时发了文字，要结合文字一起理解。",
        "4. 输出尽量自然、简洁，像用户本人发给 Neno 的一句话或一小段话。",
    ]
    if user_text:
        lines.append(f"用户附带文本：{user_text}")
    if hint_text:
        lines.append(f"平台附带提示：{hint_text}")
    lines.append("请直接输出归一化后的用户输入。")
    return "\n".join(lines)
