from app.config import CHAT_MODEL_NAME, OPENROUTER_API_KEY, OPENROUTER_URL
from app.llm.openrouter_client import chat_with_openrouter


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
