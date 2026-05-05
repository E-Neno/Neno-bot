from app.services.memory_service import find_similar_memories
from app.storage.db import add_memory, memory_exists

LOW_RISK_TYPES = {"routine", "project"}
MEDIUM_RISK_TYPES = {"profile", "relationship"}
HIGH_RISK_TYPES = {"boundary"}
STABLE_PREFERENCE_KEYWORDS = [
    "喜欢",
    "不喜欢",
    "偏好",
    "爱吃",
    "口味",
    "颜色",
    "音乐",
    "电影",
]
SENSITIVE_KEYWORDS = [
    "密码",
    "身份证",
    "手机号",
    "住址",
    "银行卡",
    "转账",
    "隐私",
    "秘密",
    "崩溃",
    "自杀",
    "自残",
    "伤害",
    "抑郁",
    "焦虑",
    "难受",
]
UNSTABLE_KEYWORDS = ["今天", "刚刚", "现在", "临时", "突然", "可能", "也许", "好像", "心情"]
HIGH_SIMILARITY_SCORE = 10
IMAGE_STRICT_TYPES = {"preference", "routine", "project", "boundary"}
IMAGE_SCENE_KEYWORDS = [
    "照片",
    "截图",
    "画面",
    "看起来",
    "背景",
    "桌上",
    "墙上",
    "手里",
    "镜头",
    "今天",
    "刚刚",
]
IMAGE_STABLE_HINTS = [
    "喜欢",
    "不喜欢",
    "偏好",
    "习惯",
    "经常",
    "通常",
    "正在做",
    "项目",
    "计划",
    "目标",
    "不要",
    "别",
    "不能",
]


def _candidate_content(candidate: dict | None) -> str:
    return str((candidate or {}).get("content") or "").strip()


def _candidate_type(candidate: dict | None) -> str:
    return str((candidate or {}).get("memory_type") or "").strip() or "general"


def _candidate_source(candidate: dict | None) -> str:
    return str((candidate or {}).get("source_modality") or "text").strip().lower() or "text"


def classify_memory_risk(candidate: dict | None) -> tuple[str, str]:
    content = _candidate_content(candidate)
    memory_type = _candidate_type(candidate)

    if memory_type in HIGH_RISK_TYPES:
        return "high", "boundary 类型默认高风险"
    if any(keyword in content for keyword in SENSITIVE_KEYWORDS):
        return "high", "包含敏感或强情绪关键词"
    if any(keyword in content for keyword in UNSTABLE_KEYWORDS):
        return "high", "表达可能偏临时或不稳定"
    if memory_type in MEDIUM_RISK_TYPES:
        return "medium", f"{memory_type} 类型默认中风险"
    if memory_type == "preference":
        if any(keyword in content for keyword in STABLE_PREFERENCE_KEYWORDS):
            return "low", "稳定 preference，低风险"
        return "medium", "preference 稳定性不足，保守确认"
    if memory_type in LOW_RISK_TYPES:
        return "low", f"{memory_type} 类型默认低风险"
    return "medium", "未知类型，保守确认"


def evaluate_image_candidate_guardrail(candidate: dict | None) -> tuple[str, str] | None:
    if _candidate_source(candidate) != "image":
        return None

    content = _candidate_content(candidate)
    memory_type = _candidate_type(candidate)

    if memory_type not in IMAGE_STRICT_TYPES:
        return "ignore", f"image 来源的 {memory_type} 类型误记风险高，v1 先忽略"

    if any(keyword in content for keyword in IMAGE_SCENE_KEYWORDS):
        return "ignore", "image 来源包含明显单次画面/场景描述，v1 先忽略"

    if not any(keyword in content for keyword in IMAGE_STABLE_HINTS):
        return "needs_confirm", "image 来源信息不足以自动记忆，保守进入人工确认"

    return "needs_confirm", "image 来源即使较稳定，v1 仍不自动写入，保守人工确认"


def _high_similarity_same_type(similar_memories: list[dict], memory_type: str) -> dict | None:
    for memory in similar_memories:
        if memory.get("memory_type") == memory_type and int(memory.get("score") or 0) >= HIGH_SIMILARITY_SCORE:
            return memory
    return None


def decide_memory_candidate(candidate: dict | None) -> dict:
    content = _candidate_content(candidate)
    memory_type = _candidate_type(candidate)
    source_modality = _candidate_source(candidate)

    if not candidate or not candidate.get("should_store") or not content:
        return {
            "action": "ignore",
            "confidence": 1.0,
            "risk_level": "low",
            "source_modality": source_modality,
            "similar_memories": [],
            "reason": "候选为空或 should_store=false",
        }

    risk_level, risk_reason = classify_memory_risk(candidate)
    similar_memories = find_similar_memories(content=content, memory_type=memory_type, limit=5)

    if memory_exists(content):
        return {
            "action": "ignore",
            "confidence": 1.0,
            "risk_level": risk_level,
            "source_modality": source_modality,
            "similar_memories": similar_memories,
            "reason": "已有完全相同的 active memory",
        }

    similar_same_type = _high_similarity_same_type(similar_memories, memory_type)
    if similar_same_type:
        return {
            "action": "merge_existing",
            "confidence": 0.82,
            "risk_level": risk_level,
            "source_modality": source_modality,
            "similar_memories": similar_memories,
            "reason": f"存在高相似同类型记忆，建议合并：id={similar_same_type.get('id')}",
        }

    image_guardrail = evaluate_image_candidate_guardrail(candidate)
    if image_guardrail:
        action, reason = image_guardrail
        return {
            "action": action,
            "confidence": 0.7 if action == "needs_confirm" else 0.92,
            "risk_level": "high" if action == "ignore" else "medium",
            "source_modality": source_modality,
            "similar_memories": similar_memories,
            "reason": reason,
        }

    if risk_level == "low":
        return {
            "action": "auto_add",
            "confidence": 0.78,
            "risk_level": risk_level,
            "source_modality": source_modality,
            "similar_memories": similar_memories,
            "reason": f"{risk_reason}，且没有重复或高相似记忆",
        }

    return {
        "action": "needs_confirm",
        "confidence": 0.66 if risk_level == "medium" else 0.58,
        "risk_level": risk_level,
        "source_modality": source_modality,
        "similar_memories": similar_memories,
        "reason": f"{risk_reason}，需要人工确认",
    }


def apply_memory_candidate_decision(candidate: dict | None, decision: dict) -> dict:
    action = decision.get("action")
    content = _candidate_content(candidate)
    memory_type = _candidate_type(candidate)
    auto_added = False

    if action == "auto_add" and content:
        if not memory_exists(content):
            add_memory(content, memory_type)
        auto_added = True

    return {
        "auto_added": auto_added,
        "candidate_memory": candidate if action == "needs_confirm" else None,
    }
