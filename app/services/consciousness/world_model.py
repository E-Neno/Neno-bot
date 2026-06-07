from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_WORLD_JSON = Path(__file__).parent / "virtual_world.json"


class CategoryDef(BaseModel):
    states: list[str]
    default: str


class ObjectDef(BaseModel):
    category: str
    label: str


class WorldDef(BaseModel):
    """静态世界定义：房间、物品、类别→合法状态。封闭世界的白名单。"""

    version: int
    home: str
    categories: dict[str, CategoryDef]
    rooms: dict[str, dict]  # {"bedroom": {"objects": [...]}}
    objects: dict[str, ObjectDef]

    def legal_states(self, obj: str) -> list[str]:
        cat = self.objects[obj].category
        return self.categories[cat].states

    def default_state(self, obj: str) -> str:
        cat = self.objects[obj].category
        return self.categories[cat].default

    def room_of(self, obj: str) -> str | None:
        for room, spec in self.rooms.items():
            if obj in spec.get("objects", []):
                return room
        return None


class WorldState(BaseModel):
    """动态世界状态：存进 life_world_state 单行表。"""

    location: str = "bedroom"
    object_states: dict[str, str] = Field(default_factory=dict)
    updated_at: str = ""
    # 竖切5：跨天延续与防绕圈所需的轻量字段（旧 JSON 缺失自动补默认）
    recent_actions: list[dict] = Field(default_factory=list)  # 最近行动，截断到 ~8
    daily_plan: dict | None = None  # 序列化的 DailyPlan
    sim_minutes: int = 0  # 模拟时钟：当天累计分钟数
    # 竖切6：开放世界（动态物品 / 金钱 / 弃置）
    money: int = 120
    dyn_objects: dict[str, dict] = Field(default_factory=dict)  # {name:{category,room,label}}
    removed: list[str] = Field(default_factory=list)  # 被扔掉的静态物品 key（渲染跳过）
    gone_log: list[dict] = Field(default_factory=list)  # [{object,label,cause,when}]
    # 竖切7：最近一步快照（持久化，端点只读 DB 即可还原"她刚在干嘛"）
    last_tick: dict | None = None


WorldOpType = Literal["set_state", "move", "create_object", "destroy_object"]


class WorldOp(BaseModel):
    op: WorldOpType
    object: str = ""  # set_state / destroy_object / create_object(新物品 key)
    state: str = ""  # set_state 用
    to_room: str = ""  # move 用
    reason: str = ""
    # 竖切6：开放世界 create_object / destroy_object 用
    category: str = ""
    room: str = ""
    label: str = ""
    cost: int = 0
    cause: str = ""


class ActionPlan(BaseModel):
    action: str  # 如 "continue_reading"
    reasoning: str = ""
    world_ops: list[WorldOp] = Field(default_factory=list)
    micro_event: str | None = None


def load_world_def() -> WorldDef:
    data = json.loads(_WORLD_JSON.read_text(encoding="utf-8"))
    return WorldDef.model_validate(data)


def seed_world_state(world_def: WorldDef) -> WorldState:
    """所有物品取类别默认状态，location 取第一个房间。"""
    obj_states = {name: world_def.default_state(name) for name in world_def.objects}
    first_room = next(iter(world_def.rooms))
    return WorldState(location=first_room, object_states=obj_states)


def apply_op(world_def: WorldDef, state: WorldState, op: WorldOp) -> WorldState:
    """纯函数：返回应用 op 后的新 WorldState（不校验，校验在 validator）。"""
    new = state.model_copy(deep=True)
    if op.op == "set_state":
        new.object_states[op.object] = op.state
    elif op.op == "move":
        new.location = op.to_room
    elif op.op == "create_object":
        cat = op.category
        new.dyn_objects[op.object] = {
            "category": cat, "room": op.room, "label": op.label or op.object,
        }
        default = world_def.categories[cat].default if cat in world_def.categories else ""
        new.object_states[op.object] = default
        if op.object in new.removed:
            new.removed.remove(op.object)
        new.money -= int(op.cost or 0)
    elif op.op == "destroy_object":
        name = op.object
        label = _label_of(world_def, new, name)
        new.object_states.pop(name, None)
        if name in new.dyn_objects:
            new.dyn_objects.pop(name, None)
        elif name in world_def.objects and name not in new.removed:
            new.removed.append(name)
        from datetime import datetime, timezone
        new.gone_log.append({
            "object": name, "label": label,
            "cause": op.cause or "扔掉", "when": datetime.now(timezone.utc).isoformat(),
        })
    return new


# ── 开放世界访问器（静态 + 动态 + removed 统一口径）─────────────────────────

def _label_of(world_def: WorldDef, state: WorldState, name: str) -> str:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("label", name)
    if name in world_def.objects:
        return world_def.objects[name].label
    return name


def obj_exists(world_def: WorldDef, state: WorldState, name: str) -> bool:
    if name in state.removed:
        return False
    return name in state.dyn_objects or name in world_def.objects


def obj_category(world_def: WorldDef, state: WorldState, name: str) -> str | None:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("category")
    if name in world_def.objects:
        return world_def.objects[name].category
    return None


def obj_room(world_def: WorldDef, state: WorldState, name: str) -> str | None:
    if name in state.dyn_objects:
        return state.dyn_objects[name].get("room")
    return world_def.room_of(name)


def legal_states_of(world_def: WorldDef, state: WorldState, name: str) -> list[str]:
    cat = obj_category(world_def, state, name)
    if cat and cat in world_def.categories:
        return world_def.categories[cat].states
    return []


def objects_in_room(world_def: WorldDef, state: WorldState, room: str) -> list[str]:
    items = [
        o for o in world_def.rooms.get(room, {}).get("objects", [])
        if o not in state.removed
    ]
    items += [n for n, meta in state.dyn_objects.items() if meta.get("room") == room]
    return items


def room_count(world_def: WorldDef, state: WorldState, room: str) -> int:
    return len(objects_in_room(world_def, state, room))
