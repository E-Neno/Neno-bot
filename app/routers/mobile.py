import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, WebSocketException, status
from fastapi.responses import FileResponse

from app.mobile_schemas import (
    MobileConversationListResponse,
    MobileMessagesResponse,
    MobileSendMessageRequest,
    MobileSendMessageResponse,
    MobileStatusResponse,
    MobileUploadResponse,
)
from app.security import require_mobile_token, validate_mobile_authorization
from app.services.mobile_realtime import register_mobile_client, unregister_mobile_client
from app.services.mobile_upload_service import MobileUploadError, resolve_mobile_upload_path, save_mobile_upload
from app.services.mobile_api_service import (
    NENO_CONVERSATION_ID,
    DEFAULT_PRESENCE,
    get_mobile_status,
    list_mobile_conversations,
    list_mobile_messages,
    MobileInputError,
    neno_presence,
    read_neno_presence,
    send_mobile_message,
)

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/status", response_model=MobileStatusResponse, dependencies=[Depends(require_mobile_token)])
def mobile_status():
    return MobileStatusResponse(**get_mobile_status())


@router.post("/uploads", response_model=MobileUploadResponse, dependencies=[Depends(require_mobile_token)])
async def mobile_upload(
    request: Request,
    kind: str = Query(..., max_length=16),
    filename: str | None = Query(default=None, max_length=160),
):
    content = await request.body()
    try:
        attachment = save_mobile_upload(
            content=content,
            kind=kind,
            filename=filename,
            mime_type=request.headers.get("content-type"),
        )
    except MobileUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MobileUploadResponse(attachment=attachment)


@router.get("/uploads/{kind}/{stored_name}", dependencies=[Depends(require_mobile_token)])
def mobile_upload_file(kind: str, stored_name: str):
    try:
        path = resolve_mobile_upload_path(kind, stored_name)
    except MobileUploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@router.websocket("/ws")
async def mobile_websocket(websocket: WebSocket):
    try:
        validate_mobile_authorization(websocket.headers.get("authorization"))
    except HTTPException as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc.detail)) from exc

    await websocket.accept()
    await register_mobile_client(websocket)
    await websocket.send_json({"type": "hello", "api": "mobile-v0"})
    await _send_presence_event(websocket)

    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                try:
                    await _send_presence_event(websocket)
                except WebSocketDisconnect:
                    break
                continue
            except WebSocketDisconnect:
                break

            try:
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                await _send_presence_event(websocket)
            except WebSocketDisconnect:
                break
    finally:
        unregister_mobile_client(websocket)


async def _send_presence_event(websocket: WebSocket):
    await websocket.send_json(
        {
            "type": "presence",
            "conversation_id": NENO_CONVERSATION_ID,
            "presence": await read_neno_presence(),
        }
    )


@router.get(
    "/conversations",
    response_model=MobileConversationListResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_conversations():
    return MobileConversationListResponse(conversations=list_mobile_conversations())


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MobileMessagesResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=100),
):
    presence = neno_presence() if conversation_id == NENO_CONVERSATION_ID else DEFAULT_PRESENCE
    return MobileMessagesResponse(
        conversation_id=conversation_id,
        messages=list_mobile_messages(conversation_id, limit),
        presence=presence,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MobileSendMessageResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_send_message(conversation_id: str, req: MobileSendMessageRequest):
    try:
        user_message, assistant_message = send_mobile_message(conversation_id, req.text, req.attachments)
    except MobileInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MobileSendMessageResponse(
        conversation_id=conversation_id,
        user_message=user_message,
        assistant_message=assistant_message,
    )
