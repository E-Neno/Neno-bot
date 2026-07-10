import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app import config
from app.mobile_schemas import MobileConversation, MobileMessage
from app.schemas import MediaAttachment
from app.services.chat.multimodal_input_service import MultimodalInputError, normalize_multimodal_message
from app.services.chat.context_builder import mask_session_id
from app.services.chat_service import run_chat_turn
from app.services.chat.voice_asr_service import VoiceASRError, transcribe_voice
from app.services.mobile_file_parser import MobileFileParseError, parse_file_attachment
from app.services.mobile_upload_service import public_mobile_upload_url
from app.services.visual_input_service import archive_current_turn_images
from app.storage.db import get_message_by_id, get_session_messages
from app.utils.logging_utils import log_event
from app.utils.logging_utils import new_trace_id


NENO_CONVERSATION_ID = "neno"
UTC8 = timezone(timedelta(hours=8))

DEFAULT_PRESENCE = "在线"


class MobileInputError(RuntimeError):
    pass


def utc8_now_iso() -> str:
    return datetime.now(timezone.utc).astimezone(UTC8).isoformat(timespec="seconds")


def _presence_from(energy_status: str | None, pending_count: int) -> str:
    """把她的真实世界状态映射成一句低干扰提示（纯函数，便于测试）。

    brief 要求：世界状态进 App 只能是「一句自然状态提示」，不是面板/仪表盘。
    优先级：睡着 > 有欠回复 > 在线。
    """
    if energy_status == "sleeping":
        return "睡着了"
    if pending_count > 0:
        return "稍后回复"
    return DEFAULT_PRESENCE


async def _read_presence_state() -> tuple[str | None, int]:
    from app.services.consciousness.config import ConsciousnessConfig
    from app.services.consciousness.state_store import StateStore
    from app.services.consciousness.world_model import load_world_def
    from app.services.consciousness.world_store import WorldStore

    cfg = ConsciousnessConfig()
    nstate = await StateStore(db=None, config=cfg).read()
    wstate = await WorldStore(load_world_def()).read()
    status = getattr(getattr(nstate, "energy", None), "status", None)
    pending = len(getattr(wstate, "pending_messages", None) or [])
    return status, pending


async def read_neno_presence() -> str:
    try:
        status, pending = await _read_presence_state()
        return _presence_from(status, pending)
    except Exception:  # noqa: BLE001 — 状态读不到就降级，不阻断
        return DEFAULT_PRESENCE


def neno_presence() -> str:
    """读她此刻真实状态，给出一句状态提示。任何读取失败都降级到「在线」，绝不让列表/聊天 500。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return DEFAULT_PRESENCE

    try:
        status, pending = asyncio.run(_read_presence_state())
        return _presence_from(status, pending)
    except Exception:  # noqa: BLE001 — 状态读不到就降级，不阻断
        return DEFAULT_PRESENCE


def get_mobile_status() -> dict[str, Any]:
    return {
        "server_time": utc8_now_iso(),
        "session_id_label": mask_session_id(config.MOBILE_DEFAULT_SESSION_ID),
    }


def _message_display_time(row: dict[str, Any]) -> str | None:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    world_time = metadata.get("world_time") if isinstance(metadata, dict) else None
    if isinstance(world_time, dict):
        value = str(world_time.get("display_time") or "").strip()
        if value:
            return value
    return None


def _message_attachments(row: dict[str, Any]) -> list[MediaAttachment]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    raw_items = metadata.get("attachments") if isinstance(metadata, dict) else None
    if not isinstance(raw_items, list):
        return []

    attachments: list[MediaAttachment] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            attachment = MediaAttachment.model_validate(raw)
        except Exception:
            continue
        if attachment.media_path and not attachment.url:
            stored_name = attachment.media_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
            if stored_name:
                attachment = attachment.model_copy(
                    update={"url": public_mobile_upload_url(attachment.kind, stored_name)}
                )
        attachments.append(attachment)
    return attachments


def _message_display_text(row: dict[str, Any], attachments: list[MediaAttachment]) -> str:
    content = str(row.get("content") or "")
    if row.get("role") != "user" or not attachments:
        return content

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    raw_input = str(metadata.get("raw_input") or "").strip() if isinstance(metadata, dict) else ""
    if raw_input:
        return raw_input
    return ""


def _attachment_conversation_preview(row: dict[str, Any], attachments: list[MediaAttachment]) -> str:
    if row.get("role") != "user" or not attachments:
        return str(row.get("content") or "")

    raw_input = _message_display_text(row, attachments).strip()
    if raw_input:
        return raw_input

    kinds = {item.kind for item in attachments}
    if "image" in kinds:
        return "发来一张图片"
    if "voice" in kinds:
        return "发来一段语音"
    if "file" in kinds:
        return "发来一个文件"
    return "发来一个附件"


def _to_mobile_message(row: dict[str, Any]) -> MobileMessage | None:
    role = row.get("role")
    if role not in {"user", "assistant"}:
        return None
    attachments = _message_attachments(row)
    return MobileMessage(
        id=int(row["id"]),
        role=role,
        text=_message_display_text(row, attachments),
        created_at=row.get("created_at"),
        display_time=_message_display_time(row),
        attachments=attachments,
        pending=False,
    )


def list_mobile_conversations() -> list[MobileConversation]:
    recent = get_session_messages(config.MOBILE_DEFAULT_SESSION_ID, limit=1)
    last = recent[0] if recent else {}
    last_attachments = _message_attachments(last)
    last_text = _attachment_conversation_preview(last, last_attachments)
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
            presence=neno_presence(),
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


def _attachment_dict(item: MediaAttachment) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def _message_type_for(attachments: list[MediaAttachment]) -> str:
    kinds = {item.kind for item in attachments}
    if "image" in kinds:
        return "image"
    if "voice" in kinds:
        return "voice"
    if "file" in kinds:
        return "file"
    return "text"


def normalize_mobile_message(
    *,
    text: str,
    attachments: list[MediaAttachment],
    trace_id: str,
    input_record: dict[str, Any],
) -> str:
    base_text = text.strip()
    if not attachments:
        return base_text

    image_attachment = next((item for item in attachments if item.kind == "image"), None)
    if image_attachment is not None:
        visual_projection = archive_current_turn_images(
            message=base_text,
            attachments=[image_attachment],
            session_id=config.MOBILE_DEFAULT_SESSION_ID,
            trace_id=trace_id,
            input_record=input_record,
        )
        if visual_projection is not None:
            return visual_projection
        try:
            normalized = normalize_multimodal_message(
                message=base_text,
                attachments=[image_attachment],
                trace_id=trace_id,
            )
        except MultimodalInputError as exc:
            _mark_mobile_input_failure(input_record, "vision", trace_id, exc)
            raise MobileInputError("这张图我刚刚没看清，你再发一次试试。") from exc
        input_record["pipeline"]["vision"]["success"] = True
        input_record["pipeline"]["normalization"] = {"status": "success", "failed_at": None}
        return normalized

    voice_attachment = next((item for item in attachments if item.kind == "voice"), None)
    if voice_attachment is not None and voice_attachment.media_path:
        try:
            transcript = transcribe_voice(voice_attachment.media_path, trace_id)
        except VoiceASRError as exc:
            _mark_mobile_input_failure(input_record, "asr", trace_id, exc)
            raise MobileInputError("这段语音我刚刚没听清，你再发一次试试。") from exc
        for item in input_record.get("attachments", []):
            if isinstance(item, dict) and item.get("kind") == "voice":
                item["text_hint"] = transcript
        input_record["pipeline"]["asr"]["success"] = True
        input_record["pipeline"]["normalization"] = {"status": "success", "failed_at": None}
        if base_text:
            return f"[用户发送了一段语音，转写如下]\n语音内容：{transcript}\n用户附带文字：{base_text}"
        return f"[用户发送了一段语音，转写如下]\n语音内容：{transcript}"

    file_attachment = next((item for item in attachments if item.kind == "file"), None)
    if file_attachment is not None:
        try:
            parsed = parse_file_attachment(file_attachment)
        except MobileFileParseError as exc:
            _mark_mobile_input_failure(input_record, "file", trace_id, exc)
            raise MobileInputError("这个文件我刚刚没读出来，你换个文件或发文字试试。") from exc
        input_record["pipeline"]["file"]["success"] = True
        input_record["pipeline"]["normalization"] = {"status": "success", "failed_at": None}
        if base_text:
            return f"{parsed}\n用户附带文字：{base_text}"
        return parsed

    return base_text


def _mark_mobile_input_failure(input_record: dict[str, Any], stage: str, trace_id: str, exc: Exception) -> None:
    if stage in input_record["pipeline"]:
        input_record["pipeline"][stage]["success"] = False
    input_record["pipeline"]["normalization"] = {"status": "failed", "failed_at": stage}
    log_event(
        "mobile",
        "mobile_input_normalization_failed",
        trace_id=trace_id,
        level="warning",
        stage=stage,
        message_type=input_record.get("message_type"),
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def send_mobile_message(
    conversation_id: str,
    text: str,
    attachments: list[MediaAttachment] | None = None,
) -> tuple[MobileMessage, MobileMessage | None]:
    if conversation_id != NENO_CONVERSATION_ID:
        raise ValueError("unsupported conversation")
    normalized_text = text.strip()
    normalized_attachments = attachments or []
    if not normalized_text and not normalized_attachments:
        raise ValueError("empty message")
    trace_id = new_trace_id()
    message_type = _message_type_for(normalized_attachments)
    input_record = {
        "source": "mobile",
        "message_type": message_type,
        "raw_input": text,
        "normalized_input": normalized_text,
        "attachments": [_attachment_dict(item) for item in normalized_attachments],
        "pipeline": {
            "vision": {"hit": message_type == "image", "success": None},
            "asr": {"hit": message_type == "voice", "success": None},
            "file": {"hit": message_type == "file", "success": None},
            "normalization": {
                "status": "pending" if normalized_attachments else "bypassed",
                "failed_at": None,
            },
        },
    }
    normalized_text = normalize_mobile_message(
        text=normalized_text,
        attachments=normalized_attachments,
        trace_id=trace_id,
        input_record=input_record,
    )
    input_record["normalized_input"] = normalized_text
    result = run_chat_turn(
        config.MOBILE_DEFAULT_SESSION_ID,
        normalized_text,
        trace_id=trace_id,
        input_record=input_record,
    )
    user_row = get_message_by_id(int(result["user_message_id"]))
    user_message = _to_mobile_message(user_row or {}) or MobileMessage(
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
        assistant_row = get_message_by_id(int(assistant_message_id))
        assistant_message = _to_mobile_message(assistant_row or {}) or assistant_message
    return user_message, assistant_message
