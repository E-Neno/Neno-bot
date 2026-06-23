from fastapi import APIRouter, Depends, HTTPException, Query

from app.mobile_schemas import (
    MobileConversationListResponse,
    MobileMessagesResponse,
    MobileSendMessageRequest,
    MobileSendMessageResponse,
    MobileStatusResponse,
)
from app.security import require_mobile_token
from app.services.mobile_api_service import (
    get_mobile_status,
    list_mobile_conversations,
    list_mobile_messages,
    send_mobile_message,
)

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/status", response_model=MobileStatusResponse, dependencies=[Depends(require_mobile_token)])
def mobile_status():
    return MobileStatusResponse(**get_mobile_status())


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
    return MobileMessagesResponse(
        conversation_id=conversation_id,
        messages=list_mobile_messages(conversation_id, limit),
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MobileSendMessageResponse,
    dependencies=[Depends(require_mobile_token)],
)
def mobile_send_message(conversation_id: str, req: MobileSendMessageRequest):
    try:
        user_message, assistant_message = send_mobile_message(conversation_id, req.text)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MobileSendMessageResponse(
        conversation_id=conversation_id,
        user_message=user_message,
        assistant_message=assistant_message,
    )
