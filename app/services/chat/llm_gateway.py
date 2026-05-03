import base64
import mimetypes
from pathlib import Path

from app.config import (
    CHAT_MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    VISION_MODEL_NAME,
)
from app.llm.openrouter_client import chat_with_openrouter, multimodal_chat_with_openrouter
from app.schemas import MediaAttachment
from app.utils.logging_utils import log_event


def require_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OPENROUTER_API_KEY


def request_model_response(
    *,
    model_name: str,
    messages: list[dict],
    timeout: int = 60,
    trace_id: str | None = None,
) -> str:
    return chat_with_openrouter(
        api_key=require_api_key(),
        url=OPENROUTER_URL,
        model_name=model_name,
        messages=messages,
        timeout=timeout,
        trace_id=trace_id,
    )


def generate_chat_reply(messages: list[dict], trace_id: str | None = None) -> str:
    return request_model_response(
        model_name=CHAT_MODEL_NAME,
        messages=messages,
        timeout=60,
        trace_id=trace_id,
    )


def generate_multimodal_chat_reply(
    *,
    text_prompt: str,
    attachments: list[MediaAttachment],
    trace_id: str | None = None,
) -> str:
    image_inputs = []
    for item in attachments:
        if item.kind != "image":
            continue
        image_input = resolve_multimodal_image_input(item, trace_id=trace_id)
        if image_input:
            image_inputs.append(image_input)

    if not image_inputs:
        raise RuntimeError("no supported multimodal attachments")

    return multimodal_chat_with_openrouter(
        api_key=require_api_key(),
        url=OPENROUTER_URL,
        model_name=VISION_MODEL_NAME,
        text_prompt=text_prompt,
        image_urls=image_inputs,
        timeout=60,
        trace_id=trace_id,
    )


def resolve_multimodal_image_input(
    attachment: MediaAttachment,
    *,
    trace_id: str | None = None,
) -> str | None:
    media_path = (attachment.media_path or "").strip()
    if media_path:
        return build_image_data_url(media_path, attachment.mime_type, trace_id=trace_id)

    image_url = (attachment.url or "").strip()
    if image_url:
        log_event(
            "multimodal",
            "image_attachment_input_selected",
            trace_id=trace_id,
            source=attachment.source,
            input_kind="url",
            has_media_path=False,
            has_url=True,
        )
        return image_url

    return None


def build_image_data_url(
    media_path: str,
    mime_type: str | None,
    *,
    trace_id: str | None = None,
) -> str:
    path = Path(media_path).expanduser()
    if not path.is_file():
        raise RuntimeError("image attachment local file missing")

    image_bytes = path.read_bytes()
    resolved_mime = resolve_image_mime_type(path, image_bytes, mime_type)
    encoded = base64.b64encode(image_bytes).decode("ascii")

    log_event(
        "multimodal",
        "image_attachment_input_selected",
        trace_id=trace_id,
        input_kind="data_url",
        mime_type=resolved_mime,
        byte_len=len(image_bytes),
        has_media_path=True,
        has_url=False,
    )
    return f"data:{resolved_mime};base64,{encoded}"


def resolve_image_mime_type(path: Path, image_bytes: bytes, mime_type: str | None) -> str:
    normalized = (mime_type or "").strip().lower()
    if normalized.startswith("image/"):
        return normalized

    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed

    magic = image_bytes[:16]
    if magic.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if magic.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if magic.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if magic.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if magic.startswith(b"BM"):
        return "image/bmp"

    raise RuntimeError("image attachment local file is not a supported image")
