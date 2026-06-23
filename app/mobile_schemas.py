from typing import Literal

from pydantic import BaseModel, Field


class MobileFeatureFlags(BaseModel):
    attachments: bool = False
    notifications: bool = False
    quick_reply: bool = False


class MobileStatusResponse(BaseModel):
    success: bool = True
    server_time: str
    api: str = "mobile-v0"
    session_id_label: str
    features: MobileFeatureFlags = Field(default_factory=MobileFeatureFlags)


class MobileConversation(BaseModel):
    id: str
    title: str
    subtitle: str
    last_message: str = ""
    last_message_at: str | None = None
    unread_count: int = 0
    pinned: bool = False
    kind: Literal["primary", "utility"]


class MobileConversationListResponse(BaseModel):
    success: bool = True
    conversations: list[MobileConversation]


class MobileMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: str | None = None
    pending: bool = False


class MobileMessagesResponse(BaseModel):
    success: bool = True
    conversation_id: str
    messages: list[MobileMessage]


class MobileSendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class MobileSendMessageResponse(BaseModel):
    success: bool = True
    conversation_id: str
    user_message: MobileMessage
    assistant_message: MobileMessage | None = None
