from __future__ import annotations

from typing import Any


def build_subscribe_frame(bot_id: str, secret: str, *, req_id: str) -> dict[str, Any]:
    return {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": req_id},
        "body": {"bot_id": bot_id, "secret": secret},
    }


def build_text_reply_frame(req_id: str, content: str) -> dict[str, Any]:
    return {
        "cmd": "aibot_respond_msg",
        "headers": {"req_id": req_id},
        "body": {"msgtype": "markdown", "markdown": {"content": content}},
    }


def normalize_callback(frame: dict[str, Any]) -> dict[str, Any]:
    if frame.get("cmd") != "aibot_msg_callback":
        raise ValueError("unsupported callback")

    body = frame.get("body") or {}
    user_id = str((body.get("from") or {}).get("userid") or "").strip()
    if not user_id:
        raise ValueError("callback missing userid")

    chat_type = "group" if body.get("chattype") == "group" else "private"
    group_id = str(body.get("chatid") or "").strip() or None
    session_id = (
        f"wecom:group:{group_id}" if chat_type == "group" and group_id
        else f"wecom:private:{user_id}"
    )

    msgtype = str(body.get("msgtype") or "text")
    if msgtype == "text":
        message = str((body.get("text") or {}).get("content") or "").strip()
    elif msgtype == "voice":
        message = str((body.get("voice") or {}).get("content") or "").strip()
    else:
        message = f"[企业微信消息：{msgtype}]"

    return {
        "platform": "wecom",
        "account_id": str(body.get("aibotid") or "").strip(),
        "user_id": user_id,
        "real_user_id": user_id,
        "chat_type": chat_type,
        "group_id": group_id,
        "session_id": session_id,
        "message": message,
        "message_type": msgtype,
        "external_message_id": str(body.get("msgid") or "").strip(),
        "req_id": str((frame.get("headers") or {}).get("req_id") or "").strip(),
    }
