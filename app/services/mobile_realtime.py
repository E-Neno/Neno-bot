from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app import config
from app.services.mobile_api_service import _message_attachments, _message_display_text
from app.storage.db import get_message_by_id


@dataclass
class _Client:
    websocket: WebSocket
    loop: asyncio.AbstractEventLoop


_clients: dict[int, _Client] = {}
_lock = threading.RLock()


async def register_mobile_client(websocket: WebSocket) -> None:
    with _lock:
        _clients[id(websocket)] = _Client(websocket=websocket, loop=asyncio.get_running_loop())


def unregister_mobile_client(websocket: WebSocket) -> None:
    with _lock:
        _clients.pop(id(websocket), None)


async def _send_to_client(client_id: int, payload: dict[str, Any]) -> None:
    with _lock:
        client = _clients.get(client_id)
    if client is None:
        return
    try:
        await client.websocket.send_json(payload)
    except Exception:
        with _lock:
            _clients.pop(client_id, None)


def publish_mobile_event(payload: dict[str, Any]) -> None:
    with _lock:
        clients = list(_clients.items())
    for client_id, client in clients:
        client.loop.call_soon_threadsafe(
            lambda cid=client_id: asyncio.create_task(_send_to_client(cid, payload))
        )


def _model_dump(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def publish_mobile_conversations() -> None:
    from app.services.mobile_api_service import list_mobile_conversations

    publish_mobile_event(
        {
            "type": "conversations",
            "conversations": [_model_dump(item) for item in list_mobile_conversations()],
        }
    )


def _message_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    role = row.get("role")
    if role not in {"user", "assistant"}:
        return None
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    world_time = metadata.get("world_time") if isinstance(metadata, dict) else None
    display_time = None
    if isinstance(world_time, dict):
        display_time = str(world_time.get("display_time") or "").strip() or None
    attachments = _message_attachments(row)
    return {
        "id": int(row["id"]),
        "role": role,
        "text": _message_display_text(row, attachments),
        "created_at": row.get("created_at"),
        "display_time": display_time,
        "attachments": [item.model_dump() for item in attachments],
        "pending": False,
    }


def publish_mobile_message(message_id: int | None) -> None:
    if message_id is None:
        return
    row = get_message_by_id(int(message_id))
    if not row or row.get("session_id") != config.MOBILE_DEFAULT_SESSION_ID:
        return
    payload = _message_payload(row)
    if payload is None:
        return
    publish_mobile_event(
        {
            "type": "message",
            "conversation_id": "neno",
            "message": payload,
        }
    )
    publish_mobile_conversations()
