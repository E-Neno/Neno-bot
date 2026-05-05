from app.config import SYSTEM_PROMPT
from app.services.chat.context_builder import load_chat_contexts
from app.services.memory_context_service import build_memory_context_message
from app.services.time_context_service import build_time_context_message


def build_chat_messages_preview_from_contexts(contexts: dict, message: str) -> dict:
    time_context_text = build_time_context_message(contexts["time_context"])
    memory_context_text = build_memory_context_message(contexts["memory_context"])
    recent_messages = [
        {"role": item["role"], "content": item["content"]}
        for item in contexts["history"]
    ]

    return {
        "system_prompt": SYSTEM_PROMPT,
        "relationship_context": contexts["relationship_context"],
        "time_context": time_context_text,
        "memory_context": memory_context_text,
        "memory_contexts": contexts["memory_context"]["memory_contexts"],
        "selected_memories": contexts["memory_context"]["selected_memories"],
        "recent_messages": recent_messages,
        "current_user_message": message,
        "final_messages": contexts["messages"],
        "counts": {
            "memory_count": contexts["memory_context"]["memory_count"],
            "recent_message_count": len(recent_messages),
            "final_message_count": len(contexts["messages"]),
        },
    }


def build_chat_messages_preview(session_id: str, message: str) -> dict:
    contexts = load_chat_contexts(session_id, message, readonly=True)
    return build_chat_messages_preview_from_contexts(contexts, message)
