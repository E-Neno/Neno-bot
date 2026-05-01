import json

from app.config import MEMORY_MODEL_NAME
from app.services.chat.llm_gateway import request_model_response
from app.services.memory_candidate_decision_service import (
    apply_memory_candidate_decision,
    decide_memory_candidate,
)
from app.utils.logging_utils import log_event

MEMORY_EXTRACTION_PROMPT = """
请判断下面这句话是否包含适合长期记忆的信息。

判断标准：
1. 只有在这句话未来大概率还会反复影响聊天体验时，才允许存。
2. 普通口味、随口提到的小偏好、一次性表达，默认不存。
3. 如果适合存，请提炼成简短自然的一句话
4. memory_type 只能是以下之一：
profile
preference
boundary
routine
relationship
project
5. 提炼后的 content 必须使用自然、简洁、贴近中文口语的表达
6. 不要使用“他们”、“她们”、“其”、“该用户”这类泛化或书面化代词
7. 统一写成“用户……”开头，或者直接写自然事实，不要写得像报告

请只返回 JSON，不要解释，不要加代码块。

格式如下：
{{
  "should_store": true,
  "content": "提炼后的记忆",
  "memory_type": "preference"
}}

如果不该存，就返回：
{{
  "should_store": false,
  "content": "",
  "memory_type": ""
}}

用户原话：
{message}
""".strip()


def request_memory_candidate(message: str, trace_id: str | None = None) -> dict | None:
    prompt = MEMORY_EXTRACTION_PROMPT.format(message=message)
    messages = [
        {"role": "system", "content": "你是一个专门负责提取长期记忆的助手。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = request_model_response(
            model_name=MEMORY_MODEL_NAME,
            messages=messages,
            timeout=60,
            trace_id=trace_id,
        )
        data = json.loads(result)
    except Exception as exc:
        log_event(
            "chat",
            "memory_candidate_error",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return None

    if data.get("content"):
        data["content"] = data["content"].strip().rstrip("。")

    return data


def process_memory_candidate(message: str, trace_id: str | None = None) -> dict:
    candidate_memory_raw = request_memory_candidate(message, trace_id=trace_id)
    candidate_memory_decision = decide_memory_candidate(candidate_memory_raw)
    candidate_result = apply_memory_candidate_decision(
        candidate_memory_raw,
        candidate_memory_decision,
    )
    return {
        "candidate_memory_decision": candidate_memory_decision,
        "candidate_memory": candidate_result["candidate_memory"],
        "auto_added_memory": candidate_result["auto_added"],
    }
