from datetime import datetime, timedelta, timezone
from typing import Any

from app import config
from app.mobile_schemas import MobileConversation, MobileMessage
from app.services.chat.context_builder import mask_session_id
from app.services.chat_service import run_chat_turn
from app.storage.db import get_session_messages
from app.utils.logging_utils import new_trace_id


NENO_CONVERSATION_ID = "neno"
UTC8 = timezone(timedelta(hours=8))


def utc8_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone(UTC8).isoformat(timespec="seconds")


def get_mobile_status() -> dict[str, Any]:
    return {
        "server_time": utc8_now_iso(),
        "session_id_label": mask_session_id(config.MOBILE_DEFAULT_SESSION_ID),
    }


def _to_mobile_message(row: dict[str, Any]) -> MobileMessage | None:
    role = row.get("role")
    if role not in {"user", "assistant"}:
        return None
    return MobileMessage(
        id=int(row["id"]),
        role=role,
        text=str(row.get("content") or ""),
        created_at=row.get("created_at"),
        pending=False,
    )


def list_mobile_conversations() -> list[MobileConversation]:
    recent = get_session_messages(config.MOBILE_DEFAULT_SESSION_ID, limit=1)
    last = recent[0] if recent else {}
    last_text = str(last.get("content") or "")
    return [
        MobileConversation(
            id=NENO_CONVERSATION_ID,
            title="Neno",
            subtitle="置顶联系人",
            last_message=last_text,
            last_message_at=last.get("created_at"),
            unread_count=0,
            pinned=True,
            kind="primary",
        ),
        MobileConversation(
            id="writing",
            title="写作助手",
            subtitle="工具联系人",
            kind="utility",
        ),
        MobileConversation(
            id="code",
            title="代码助手",
            subtitle="工具联系人",
            kind="utility",
        ),
    ]


def list_mobile_messages(conversation_id: str, limit: int) -> list[MobileMessage]:
    if conversation_id != NENO_CONVERSATION_ID:
        return []
    rows = get_session_messages(config.MOBILE_DEFAULT_SESSION_ID, limit=limit)
    messages = [_to_mobile_message(row) for row in rows]
    return [message for message in messages if message is not None]


def send_mobile_message(conversation_id: str, text: str) -> tuple[MobileMessage, MobileMessage | None]:
    if conversation_id != NENO_CONVERSATION_ID:
        raise ValueError("unsupported conversation")
    normalized_text = text.strip()
    trace_id = new_trace_id()
    result = run_chat_turn(
        config.MOBILE_DEFAULT_SESSION_ID,
        normalized_text,
        trace_id=trace_id,
        input_record={
            "source": "mobile",
            "message_type": "text",
            "raw_input": text,
            "normalized_input": normalized_text,
            "attachments": [],
        },
    )
    user_message = MobileMessage(
        id=int(result["user_message_id"]),
        role="user",
        text=normalized_text,
        created_at=None,
    )
    # 选择层选择不回、或在场门控把消息暂存时，没有助手回复：
    # assistant_message_id 为 None、reply 为空。此时返回 assistant_message=None，
    # 由客户端给出「她晚点回你」的软提示，绝不能 int(None) 崩成 500。
    assistant_message_id = result.get("assistant_message_id")
    reply = result.get("reply") or ""
    assistant_message: MobileMessage | None = None
    if assistant_message_id is not None and reply:
        assistant_message = MobileMessage(
            id=int(assistant_message_id),
            role="assistant",
            text=str(reply),
            created_at=None,
        )
    return user_message, assistant_message
