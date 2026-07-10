from typing import Any, Literal

from pydantic import BaseModel, Field


AgentState = Literal[
    "idle",
    "observing",
    "executing",
    "paused",
    "awaiting_confirmation",
    "stopped",
    "failed",
]
AgentRisk = Literal["read_only", "low", "medium", "high"]


class AgentHello(BaseModel):
    type: Literal["hello"] = "hello"
    device_id: str
    client: str
    protocol: str = "phone-agent-v0"


class AgentCapabilities(BaseModel):
    accessibility: bool = False
    screenshot: bool = False
    notification: bool = False
    root_daemon: bool = False
    kernel_touch: bool = False


class AgentObservation(BaseModel):
    type: Literal["observation"] = "observation"
    device_id: str
    state: AgentState
    foreground_app: str | None = None
    screen: dict[str, int] = Field(default_factory=dict)
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)


class AgentActionRequest(BaseModel):
    type: Literal["action_request"] = "action_request"
    action_id: str
    tool: Literal["tap", "swipe", "type_text", "back", "home", "open_app", "screenshot", "stop"]
    risk: AgentRisk
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str
