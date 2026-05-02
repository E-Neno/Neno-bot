from app.config import (
    CHAT_MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    VISION_MODEL_NAME,
)
from app.llm.openrouter_client import chat_with_openrouter, multimodal_chat_with_openrouter
from app.schemas import MediaAttachment


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
    image_urls = [item.url for item in attachments if item.kind == "image" and item.url]
    if not image_urls:
        raise RuntimeError("no supported multimodal attachments")

    return multimodal_chat_with_openrouter(
        api_key=require_api_key(),
        url=OPENROUTER_URL,
        model_name=VISION_MODEL_NAME,
        text_prompt=text_prompt,
        image_urls=image_urls,
        timeout=60,
        trace_id=trace_id,
    )
