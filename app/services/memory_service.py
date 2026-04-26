import re

from app.storage import db

MEMORY_TYPE_HINTS = {
    "profile": ["叫", "名字", "是谁", "身份", "年龄", "生日", "哪里人", "住", "学校", "工作"],
    "preference": ["喜欢", "不喜欢", "讨厌", "爱吃", "想吃", "口味", "偏好", "颜色", "音乐", "电影"],
    "boundary": ["别", "不要", "禁止", "不能", "忌讳", "边界", "少提", "别问"],
    "routine": ["平时", "一般", "经常", "通常", "作息", "每天", "习惯", "周末"],
    "relationship": ["朋友", "家人", "妈妈", "爸爸", "对象", "恋人", "同事", "孩子", "女朋友", "男朋友"],
    "project": ["项目", "计划", "目标", "正在做", "开发", "写", "产品", "任务", "工作流"],
    "general": [],
}


def extract_keywords(text: str) -> list[str]:
    normalized = (text or "").lower().strip()
    if not normalized:
        return []

    phrases = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", normalized)
    chars = [char for char in normalized if "\u4e00" <= char <= "\u9fff"]
    keywords = phrases + chars
    return list(dict.fromkeys(keywords))


def score_memory_relevance(memory: dict, query: str, query_keywords: list[str]) -> int:
    score = 0
    memory_text = f"{memory['memory_type']} {memory['content']}".lower()

    for keyword in query_keywords:
        if keyword and keyword in memory_text:
            score += 3 if len(keyword) >= 2 else 1

    for hint in MEMORY_TYPE_HINTS.get(memory["memory_type"], []):
        if hint in query:
            score += 4

    if memory["memory_type"] in query:
        score += 5

    return score


def get_relevant_memories(query: str, limit: int = 5):
    active_memories = db.get_active_memories(limit=200)
    normalized_query = (query or "").lower()
    query_keywords = extract_keywords(normalized_query)

    scored_memories = []
    for memory in active_memories:
        score = score_memory_relevance(memory, normalized_query, query_keywords)
        if score > 0:
            scored_memories.append(
                {
                    "id": memory.get("id"),
                    "content": memory["content"],
                    "memory_type": memory["memory_type"],
                    "created_at": memory["created_at"],
                    "score": score,
                }
            )

    scored_memories.sort(key=lambda item: (-item["score"], item["created_at"]))
    return scored_memories[:limit]


def score_similarity(candidate: dict, content: str, memory_type: str | None, keywords: list[str]) -> int:
    score = 0
    candidate_text = candidate["content"].lower()

    if memory_type and candidate["memory_type"] == memory_type:
        score += 3

    for keyword in keywords:
        if keyword and keyword in candidate_text:
            score += 2 if len(keyword) >= 2 else 1

    return score


def find_similar_memories(content: str, memory_type: str | None = None, limit: int = 5):
    memories = db.list_memories("WHERE is_active = 1")
    keywords = extract_keywords(content)
    candidates = []

    for memory in memories:
        if memory["content"] == content:
            continue

        score = score_similarity(memory, content, memory_type, keywords)
        if score >= 4:
            candidates.append(
                {
                    "id": memory["id"],
                    "content": memory["content"],
                    "memory_type": memory["memory_type"],
                    "is_active": memory["is_active"],
                    "score": score,
                }
            )

    candidates.sort(key=lambda item: (-item["score"], -item["id"]))
    return candidates[:limit]
