# app/services/consciousness/models.py
"""Pydantic models for the consciousness layer."""
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


# ── Energy ──────────────────────────────────────────────
class EnergyState(BaseModel):
    value: float = 80.0          # 0-100
    status: str = "awake"        # awake / sleeping
    description: str = "精力还不错"


# ── Mood (2-dimensional) ───────────────────────────────
class MoodState(BaseModel):
    valence: float = 0.3         # -1 (negative) ~ 1 (positive)
    arousal: float = 0.5         # 0 (calm) ~ 1 (excited)
    label: str = "平静"           # human-readable mood word
    description: str = "没什么特别的感觉"
    baseline_valence: float = 0.3
    baseline_arousal: float = 0.5


# ── Desire (expression desire) ─────────────────────────
class DesireState(BaseModel):
    value: float = 0.0           # 0-100
    last_express_at: Optional[str] = None
    decay_duration_minutes: int = 120


# ── World perception snapshot ──────────────────────────
class WeatherSnapshot(BaseModel):
    text: str = ""
    temp: Optional[int] = None
    condition: str = ""
    rain: bool = False


class WorldState(BaseModel):
    weather: Optional[WeatherSnapshot] = None
    hot_topics: list[str] = Field(default_factory=list)
    time_context: str = ""
    last_perception_at: Optional[str] = None


# ── Last interaction snapshot ──────────────────────────
class LastInteraction(BaseModel):
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    summary: Optional[str] = None
    at_time: Optional[str] = None


# ── Living World state ─────────────────────────────────
class NeedState(BaseModel):
    connection: float = 0.0
    novelty: float = 0.0
    quiet: float = 0.0
    order: float = 0.0

    @field_validator("connection", "novelty", "quiet", "order", mode="after")
    @classmethod
    def _clamp_need(cls, value: float) -> float:
        return _clamp(value, 0.0, 100.0)


class LifeResidue(BaseModel):
    topic: str = ""
    mood: str = ""
    intensity: float = 0.0

    @field_validator("intensity", mode="after")
    @classmethod
    def _clamp_intensity(cls, value: float) -> float:
        return _clamp(value, 0.0, 1.0)


class LifeState(BaseModel):
    mode: str = "idle"
    attention: str = "ambient"
    need: NeedState = Field(default_factory=NeedState)
    current_activity: str = "quiet_observing"
    last_transition_at: Optional[str] = None
    residue: LifeResidue = Field(default_factory=LifeResidue)


# ── Today's experience ─────────────────────────────────
class Experience(BaseModel):
    time: str                     # HH:MM
    content: str
    topic_hash: str = ""
    mood_impact: float = 0.0


# ── Full state ─────────────────────────────────────────
class NenoState(BaseModel):
    version: int = 2
    revision: int = 0
    updated_at: Optional[str] = None
    energy: EnergyState = Field(default_factory=EnergyState)
    mood: MoodState = Field(default_factory=MoodState)
    desire: DesireState = Field(default_factory=DesireState)
    world: WorldState = Field(default_factory=WorldState)
    last_interaction: LastInteraction = Field(default_factory=LastInteraction)
    life: LifeState = Field(default_factory=LifeState)
    today_experiences: list[Experience] = Field(default_factory=list)


# ── Event (from world engine) ──────────────────────────
class Event(BaseModel):
    topic_hash: str
    priority: int                 # 0=P0 ... 3=P3
    content: str
    tags: list[str] = Field(default_factory=list)
    mood_impact: float = 0.0
    source: str = ""              # perception / virtual / user


# ── Decision (from brain) ──────────────────────────────
class Decision(BaseModel):
    should_share: bool = False
    target_user_id: Optional[str] = None
    fragments: list[str] = Field(default_factory=list)
    reason: str = ""


# ── State mutation (queued write) ──────────────────────
class StateMutation(BaseModel):
    """A partial state update to be applied via the single-writer queue."""
    energy: Optional[EnergyState] = None
    mood: Optional[MoodState] = None
    desire: Optional[DesireState] = None
    world: Optional[WorldState] = None
    life: Optional[LifeState] = None
    life_residue: Optional[LifeResidue] = None
    today_experiences_append: Optional[Experience] = None
    today_experiences_clear: bool = False
    desire_clear: bool = False
    experience: Optional[Experience] = None
    clear_experiences: bool = False
    trace_id: str = ""
    reason: str = ""
    mood_valence_delta: float = 0.0
    desire_pulse: float = 0.0
