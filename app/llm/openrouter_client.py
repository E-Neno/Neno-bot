import time

import requests

from app.config import OPENROUTER_PROXY
from app.utils.logging_utils import log_event


def _proxies() -> dict | None:
    if OPENROUTER_PROXY:
        return {"http": OPENROUTER_PROXY, "https": OPENROUTER_PROXY}
    return None


def chat_with_openrouter(
    api_key: str,
    url: str,
    model_name: str,
    messages: list,
    timeout: int = 60,
    trace_id: str | None = None,
    extra_body: dict | None = None,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict = {
        "model": model_name,
        "messages": messages,
    }
    if max_tokens is not None:
        # 回复长度上限：兜住模型偶发跑飞（脑补一长串假对话），顺便省 token。
        payload["max_tokens"] = int(max_tokens)
    if stop:
        # 角色轮次标记（如换行后的 "Assistant"）一出现就停，防止污染入库引发反馈环。
        payload["stop"] = list(stop)
    if model_name.startswith("anthropic/"):
        payload["provider"] = {"order": ["Anthropic"]}
    if extra_body:
        # 厂商特定参数（如 MiMo 关深度思考 thinking={"type":"disabled"} 把 15s 压到 ~1.2s）
        payload.update(extra_body)

    started = time.perf_counter()
    log_event(
        "openrouter",
        "openrouter_request_start",
        trace_id=trace_id,
        model=model_name,
        message_count=len(messages),
    )

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout, proxies=_proxies())
    except requests.RequestException as e:
        log_event(
            "openrouter",
            "openrouter_request_failed",
            trace_id=trace_id,
            status_code=None,
            error_type=type(e).__name__,
            error_message=str(e),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise RuntimeError("LLM request failed") from e

    if resp.status_code != 200:
        log_event(
            "openrouter",
            "openrouter_request_failed",
            trace_id=trace_id,
            status_code=resp.status_code,
            error_type="HTTPError",
            error_message=resp.text[:200],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise RuntimeError("LLM provider error")

    data = resp.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        log_event(
            "openrouter",
            "openrouter_request_failed",
            trace_id=trace_id,
            status_code=resp.status_code,
            error_type=type(exc).__name__,
            error_message="Invalid response format from OpenRouter",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        raise RuntimeError("Invalid response format from OpenRouter") from exc

    log_event(
        "openrouter",
        "openrouter_request_ok",
        trace_id=trace_id,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return content


def multimodal_chat_with_openrouter(
    api_key: str,
    url: str,
    model_name: str,
    text_prompt: str,
    image_urls: list[str],
    timeout: int = 60,
    trace_id: str | None = None,
) -> str:
    content = [{"type": "text", "text": text_prompt}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": image_url},
        }
        for image_url in image_urls
    )
    messages = [{"role": "user", "content": content}]
    return chat_with_openrouter(
        api_key=api_key,
        url=url,
        model_name=model_name,
        messages=messages,
        timeout=timeout,
        trace_id=trace_id,
    )
