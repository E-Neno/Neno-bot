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

VOICE_PLACEHOLDER_MESSAGES = {"[语音消息]", "[语音消息(未听清)]"}


def _source_modality(input_record: dict | None) -> str:
    value = str((input_record or {}).get("message_type") or "text").strip().lower()
    return value or "text"


def _source_label(source_modality: str) -> str:
    labels = {
        "text": "text",
        "image": "image",
        "voice": "voice",
    }
    return labels.get(source_modality, source_modality or "text")


def _is_skippable_message(message: str, source_modality: str) -> bool:
    text = str(message or "").strip()
    if not text:
        return True
    if source_modality == "voice" and text in VOICE_PLACEHOLDER_MESSAGES:
        return True
    return False


def build_memory_extraction_prompt(message: str, input_record: dict | None = None) -> str:
    source_modality = _source_modality(input_record)
    message_marker = "\n\n用户原话：\n{message}"
    prompt = (
        MEMORY_EXTRACTION_PROMPT[: -len(message_marker)]
        if MEMORY_EXTRACTION_PROMPT.endswith(message_marker)
        else MEMORY_EXTRACTION_PROMPT
    )

    if source_modality == "voice":
        prompt += """

补充说明：
- 这句话来自用户语音转写。
- 请把它当作用户真实说出来的文字内容处理。
- 不要提取 ASR 过程信息、转写质量、音频元数据。
"""
    elif source_modality == "image":
        prompt += """

补充说明：
- 这句话来自“用户发送图片”后的归一化理解结果，不是普通纯文本输入。
- 只有在图片内容明确反映用户长期稳定信息时，才允许存入长期记忆。
- 单次场景、临时视觉细节、一次性画面内容、模型根据图片脑补出的细节，默认不要存。
- 如果只是“这张图里有什么”，或只对当前轮有效，应返回 should_store=false。
"""

    return f"{prompt}{message_marker}".format(message=message)


def request_memory_candidate(
    message: str,
    trace_id: str | None = None,
    input_record: dict | None = None,
) -> dict | None:
    source_modality = _source_modality(input_record)
    if _is_skippable_message(message, source_modality):
        return {
            "should_store": False,
            "content": "",
            "memory_type": "",
            "source_modality": source_modality,
            "source_label": _source_label(source_modality),
            "reason": "消息内容为空或不适合作为长期记忆提取输入",
        }

    prompt = build_memory_extraction_prompt(message, input_record=input_record)
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

    data["source_modality"] = source_modality
    data["source_label"] = _source_label(source_modality)
    data["normalized_input"] = str((input_record or {}).get("normalized_input") or message).strip()
    raw_input = str((input_record or {}).get("raw_input") or "").strip()
    if raw_input:
        data["raw_input"] = raw_input

    log_event(
        "chat",
        "memory_candidate_extracted",
        trace_id=trace_id,
        source_modality=source_modality,
        should_store=bool(data.get("should_store")),
        memory_type=str(data.get("memory_type") or ""),
        content_len=len(str(data.get("content") or "")),
    )
    return data


def process_memory_candidate(
    message: str,
    trace_id: str | None = None,
    input_record: dict | None = None,
) -> dict:
    candidate_memory_raw = request_memory_candidate(
        message,
        trace_id=trace_id,
        input_record=input_record,
    )
    candidate_memory_decision = decide_memory_candidate(candidate_memory_raw)
    candidate_result = apply_memory_candidate_decision(
        candidate_memory_raw,
        candidate_memory_decision,
    )
    log_event(
        "chat",
        "memory_candidate_decided",
        trace_id=trace_id,
        source_modality=str((candidate_memory_raw or {}).get("source_modality") or "text"),
        action=str(candidate_memory_decision.get("action") or ""),
        risk_level=str(candidate_memory_decision.get("risk_level") or ""),
        reason=str(candidate_memory_decision.get("reason") or ""),
        auto_added=bool(candidate_result["auto_added"]),
    )
    return {
        "candidate_memory_decision": candidate_memory_decision,
        "candidate_memory": candidate_result["candidate_memory"],
        "candidate_memory_debug": candidate_memory_raw,
        "auto_added_memory": candidate_result["auto_added"],
    }
