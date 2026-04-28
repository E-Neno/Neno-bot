import time

import requests

from app.utils.logging_utils import log_event


def chat_with_openrouter(
    api_key: str,
    url: str,
    model_name: str,
    messages: list,
    timeout: int = 60,
    trace_id: str | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": messages,
    }

    started = time.perf_counter()
    log_event(
        "openrouter",
        "openrouter_request_start",
        trace_id=trace_id,
        model=model_name,
        message_count=len(messages),
    )

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
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
