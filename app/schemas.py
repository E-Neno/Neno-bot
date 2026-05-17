from typing import Any

from pydantic import BaseModel, Field, StrictBool, validator


class MediaAttachment(BaseModel):
    kind: str = Field(..., max_length=32)
    url: str | None = Field(default=None, max_length=2000)
    media_path: str | None = Field(default=None, max_length=1000)
    mime_type: str | None = Field(default=None, max_length=128)
    source: str | None = Field(default=None, max_length=64)
    text_hint: str | None = Field(default=None, max_length=500)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=2000)
    session_id: str = Field(default="default", max_length=128)
    attachments: list[MediaAttachment] = Field(default_factory=list)


class ConfigUpdateRequest(BaseModel):
    chat_model: str | None = None
    memory_model: str | None = None
    history_token_limit: int | None = None
    memory_limit: int | None = None


class ChatResponse(BaseModel):
    reply: str
    trace_id: str | None = None
    user_message_id: int | None = None
    assistant_message_id: int | None = None
    message_type: str | None = None
    source: str | None = None
    candidate_memory: dict[str, Any] | None = None
    candidate_memory_debug: dict[str, Any] | None = None
    candidate_memory_decision: dict[str, Any] | None = None
    auto_added: bool = False
    auto_added_memory: bool = False
    used_memories: list[dict[str, Any]] = Field(default_factory=list)
    relationship_state: dict[str, Any] | None = None
    relationship_context: str | None = None


class PlatformMessageRequest(BaseModel):
    platform: str | None = None
    account_id: str | None = Field(default=None, max_length=64)
    user_id: str | None = None
    real_user_id: str | None = None
    chat_type: str | None = None
    group_id: str | None = None
    message: str | None = Field(default=None, max_length=2000)
    attachments: list[MediaAttachment] = Field(default_factory=list)
    message_type: str | None = Field(default=None, max_length=32)


class PlatformMessageResponse(BaseModel):
    success: bool
    reply: str
    session_id: str


class PlatformRoutingOverrideRequest(BaseModel):
    platform: str = Field(..., max_length=16)
    account_id: str | None = Field(default=None, max_length=64)
    user_id: str = Field(..., max_length=128)
    chat_type: str = Field(..., max_length=16)
    group_id: str | None = Field(default=None, max_length=128)
    session_id: str = Field(..., max_length=128)
    operator: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=240)


class PlatformRoutingOverrideClearRequest(BaseModel):
    platform: str = Field(..., max_length=16)
    account_id: str | None = Field(default=None, max_length=64)
    user_id: str = Field(..., max_length=128)
    chat_type: str = Field(..., max_length=16)
    group_id: str | None = Field(default=None, max_length=128)
    operator: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=240)


class MemoryAddRequest(BaseModel):
    content: str = Field(..., max_length=2000)
    memory_type: str = Field(default="general", max_length=64)


class MemoryUpdateRequest(BaseModel):
    id: int
    content: str = Field(..., max_length=2000)
    memory_type: str = Field(default="general", max_length=64)


class MemoryAddResponse(BaseModel):
    success: bool
    message: str


class MemoryDisableRequest(BaseModel):
    memory_id: int


class MemoryDisableResponse(BaseModel):
    success: bool
    message: str


class MemoryActionRequest(BaseModel):
    id: int


class ProactiveGenerateRequest(BaseModel):
    platform: str | None = Field(default=None, max_length=16)


class ProactiveGenerateTestRequest(BaseModel):
    force: StrictBool = False


class ProactiveDismissRequest(BaseModel):
    id: int


class ProactiveSendQqRequest(BaseModel):
    id: int
    dry_run: StrictBool


class ProactiveSendRequest(BaseModel):
    id: int
    dry_run: StrictBool


class ProactiveRunOnceRequest(BaseModel):
    ignore_random: StrictBool = True
    ignore_recent_chat: StrictBool = False
    ignore_active_window: StrictBool = False
    force: StrictBool = False
    dry_run_only: StrictBool = True


class ProactiveConfigUpdateRequest(BaseModel):
    PROACTIVE_ENABLED: StrictBool | None = None
    PROACTIVE_MODE: str | None = Field(default=None, max_length=16)
    PROACTIVE_CHECK_INTERVAL_SECONDS: int | None = None
    PROACTIVE_DAILY_LIMIT: int | None = None
    PROACTIVE_MIN_INTERVAL_MINUTES: int | None = None
    PROACTIVE_RECENT_CHAT_SKIP_MINUTES: int | None = None
    PROACTIVE_HARD_COOLDOWN_MINUTES: int | None = None
    PROACTIVE_FAILURE_PAUSE_THRESHOLD: int | None = None
    PROACTIVE_ACTIVE_START: str | None = Field(default=None, max_length=5)
    PROACTIVE_ACTIVE_END: str | None = Field(default=None, max_length=5)
    PROACTIVE_RANDOM_PROBABILITY: float | None = None
    PROACTIVE_QQ_ALLOWED_TARGET_HASHES: str | None = Field(default=None, max_length=1000)
    PROACTIVE_AUTO_SEND: StrictBool | None = None
    PROACTIVE_AUTO_SEND_DRY_RUN: StrictBool | None = None
    PROACTIVE_AUTO_SEND_REQUIRE_ALLOWED_TARGET: StrictBool | None = None
    PROACTIVE_AUTO_SEND_MAX_PER_DAY: int | None = None
    NENO_BRIDGE_SEND_QQ_URL: str | None = Field(default=None, max_length=200)
    NENO_BRIDGE_SEND_WX_URL: str | None = Field(default=None, max_length=200)

    class Config:
        extra = "forbid"


class SessionRequest(BaseModel):
    session_id: str = Field(default="default", max_length=128)


class SessionMessageDeleteRequest(BaseModel):
    message_id: int = Field(..., ge=1)


class RelationshipUpdateRequest(BaseModel):
    session_id: str = Field(..., max_length=128)
    stage: int | None = Field(default=None, ge=0, le=4)
    conversation_count: int | None = Field(default=None, ge=0, le=999)
    familiarity_score: int | None = Field(default=None, ge=0, le=999)
    trust_score: int | None = Field(default=None, ge=0, le=999)
    emotional_depth_score: int | None = Field(default=None, ge=0, le=999)
    boundary_score: int | None = Field(default=None, ge=0, le=999)

    @validator("session_id")
    def session_id_must_not_be_blank(cls, value: str) -> str:
        session_id = value.strip()
        if not session_id:
            raise ValueError("session_id must not be blank")
        return session_id
