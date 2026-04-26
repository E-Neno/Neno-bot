from typing import Any
from pathlib import Path

from app.storage.relationship import (
    ensure_relationship_state,
    reset_relationship_state,
    update_relationship_state,
    update_relationship_state_manual,
)

MAX_SCORE = 999
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STAGE_PROMPT_DIR = PROJECT_ROOT / "prompts" / "stages"
RELATIONSHIP_CONTEXT_FALLBACK = "保持自然、短句、克制，不要提到关系阶段或分数。"

GREETINGS = ["你好", "哈喽", "在吗", "嗯", "好", "哈哈", "哈哈哈", "？", "哦", "行"]
PREFERENCE_KEYWORDS = ["我喜欢", "我不喜欢", "我希望", "我想要", "我讨厌"]
BOUNDARY_KEYWORDS = ["别", "不要", "别这样", "不喜欢", "讨厌", "受不了"]
EMOTION_KEYWORDS = ["累", "烦", "难受", "焦虑", "压力", "崩", "emo", "害怕", "紧张", "不舒服"]

STAGE_LABELS = {
    0: "陌生",
    1: "初步熟悉",
    2: "稳定聊天对象",
    3: "比较亲近",
    4: "深度陪伴",
}

SCORE_FIELDS = [
    "familiarity_score",
    "trust_score",
    "emotional_depth_score",
    "boundary_score",
]


def _contains_any(message: str, keywords: list[str]) -> bool:
    return any(keyword in message for keyword in keywords)


def _is_greeting(message: str) -> bool:
    return message in GREETINGS


def _clamp_score(value: int) -> int:
    return max(0, min(MAX_SCORE, value))


def calculate_relationship_delta(user_message: str) -> dict[str, int]:
    message = (user_message or "").strip()
    delta = {
        "conversation_count": 1,
        "familiarity_score": 0,
        "trust_score": 0,
        "emotional_depth_score": 0,
        "boundary_score": 0,
    }

    if _is_greeting(message):
        return delta

    if len(message) >= 8:
        delta["familiarity_score"] += 1

    if _contains_any(message, PREFERENCE_KEYWORDS):
        delta["familiarity_score"] += 2

    if _contains_any(message, BOUNDARY_KEYWORDS):
        delta["boundary_score"] += 2

    if _contains_any(message, EMOTION_KEYWORDS):
        delta["trust_score"] += 1
        delta["emotional_depth_score"] += 2

    return delta


def calculate_stage(state: dict) -> int:
    conversation_count = int(state.get("conversation_count") or 0)
    familiarity_score = int(state.get("familiarity_score") or 0)
    trust_score = int(state.get("trust_score") or 0)
    emotional_depth_score = int(state.get("emotional_depth_score") or 0)

    if conversation_count >= 120 and trust_score >= 25 and emotional_depth_score >= 20:
        return 3
    if conversation_count >= 40 and familiarity_score >= 25:
        return 2
    if conversation_count >= 12 and familiarity_score >= 8:
        return 1
    return 0


def with_stage_label(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if state is None:
        return None
    output = dict(state)
    output["stage_label"] = STAGE_LABELS.get(int(output.get("stage") or 0), "未知")
    return output


def apply_relationship_update(session_id: str, user_message: str) -> dict[str, Any]:
    state = ensure_relationship_state(session_id)
    delta = calculate_relationship_delta(user_message)

    updated = {
        "conversation_count": int(state.get("conversation_count") or 0) + delta["conversation_count"],
    }
    for field in SCORE_FIELDS:
        updated[field] = _clamp_score(int(state.get(field) or 0) + delta[field])

    next_state = {**state, **updated}
    current_stage = int(state.get("stage") or 0)
    updated["stage"] = current_stage if current_stage >= 4 else calculate_stage(next_state)

    return with_stage_label(update_relationship_state(session_id, updated))


def build_relationship_context(session_id: str) -> str:
    state = ensure_relationship_state(session_id)
    stage = int(state.get("stage") or 0)
    prompt_path = STAGE_PROMPT_DIR / f"stage_{stage}.txt"
    try:
        content = prompt_path.read_text(encoding="utf-8").strip()
    except OSError:
        return RELATIONSHIP_CONTEXT_FALLBACK
    return content or RELATIONSHIP_CONTEXT_FALLBACK


def get_relationship_state_for_api(session_id: str) -> dict[str, Any]:
    return with_stage_label(ensure_relationship_state(session_id))


def update_relationship_state_manual_for_api(session_id: str, updates: dict) -> dict[str, Any]:
    return with_stage_label(update_relationship_state_manual(session_id, updates))


def reset_relationship_state_for_api(session_id: str) -> dict[str, Any]:
    return with_stage_label(reset_relationship_state(session_id))
