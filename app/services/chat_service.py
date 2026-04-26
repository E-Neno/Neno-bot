import json

from app.config import (
    CHAT_MODEL_NAME,
    HISTORY_LIMIT,
    MEMORY_LIMIT,
    MEMORY_MODEL_NAME,
    OPENROUTER_API_KEY,
    OPENROUTER_URL,
    SYSTEM_PROMPT,
)
from app.llm.openrouter_client import chat_with_openrouter
from app.services.memory_service import get_relevant_memories
from app.services.relationship_service import (
    apply_relationship_update,
    build_relationship_context,
    get_relationship_state_for_api,
)
from app.storage.db import add_message, get_recent_messages
from app.storage.relationship import ensure_relationship_state

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


def require_api_key() -> str:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return OPENROUTER_API_KEY


def build_memory_prompt(memories: list[dict]) -> str:
    if not memories:
        return ""

    lines = [f"- [{mem['memory_type']}] {mem['content']}" for mem in memories[:5]]
    return (
        "以下是关于用户的长期记忆，只在当前话题自然相关时参考；"
        "不要生硬复述，不要主动说“我记得”，把它们自然融入回复：\n"
        + "\n".join(lines)
    )


def build_chat_messages(
    history: list[dict],
    message: str,
    relationship_context: str | None = None,
) -> tuple[list[dict], list[dict]]:
    memories = get_relevant_memories(message, limit=MEMORY_LIMIT)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if relationship_context:
        messages.append({"role": "system", "content": relationship_context})

    memory_text = build_memory_prompt(memories)

    if memory_text:
        messages.append({"role": "system", "content": memory_text})

    messages.extend({"role": item["role"], "content": item["content"]} for item in history)
    messages.append({"role": "user", "content": message})
    used_memories = [
        {
            "id": memory.get("id"),
            "content": memory["content"],
            "memory_type": memory["memory_type"],
            "score": memory["score"],
        }
        for memory in memories[:5]
    ]
    return messages, used_memories


def request_memory_candidate(message: str) -> dict | None:
    prompt = MEMORY_EXTRACTION_PROMPT.format(message=message)
    messages = [
        {"role": "system", "content": "你是一个专门负责提取长期记忆的助手。"},
        {"role": "user", "content": prompt},
    ]

    try:
        result = chat_with_openrouter(
            api_key=require_api_key(),
            url=OPENROUTER_URL,
            model_name=MEMORY_MODEL_NAME,
            messages=messages,
            timeout=60,
        )
        data = json.loads(result)
    except Exception as exc:
        print("AI记忆提取失败:", exc)
        return None

    if data.get("content"):
        data["content"] = data["content"].strip().rstrip("。")

    if not data.get("should_store"):
        return None

    return data


def generate_chat_reply(messages: list[dict]) -> str:
    return chat_with_openrouter(
        api_key=require_api_key(),
        url=OPENROUTER_URL,
        model_name=CHAT_MODEL_NAME,
        messages=messages,
        timeout=60,
    )


def run_chat_turn(session_id: str, message: str) -> dict:
    history = get_recent_messages(session_id, limit=HISTORY_LIMIT)
    relationship_context = None
    relationship_state = None
    try:
        ensure_relationship_state(session_id)
        relationship_context = build_relationship_context(session_id)
    except Exception as exc:
        print("关系状态初始化失败:", exc)

    messages, used_memories = build_chat_messages(
        history=history,
        message=message,
        relationship_context=relationship_context,
    )
    candidate_memory = request_memory_candidate(message)

    reply = generate_chat_reply(messages)

    add_message(session_id, "user", message)
    add_message(session_id, "assistant", reply)

    try:
        relationship_state = apply_relationship_update(session_id, message)
    except Exception as exc:
        print("关系状态更新失败:", exc)
        try:
            relationship_state = get_relationship_state_for_api(session_id)
        except Exception:
            relationship_state = None

    return {
        "reply": reply,
        "candidate_memory": candidate_memory,
        "used_memories": used_memories,
        "relationship_state": relationship_state,
        "relationship_context": relationship_context,
    }
