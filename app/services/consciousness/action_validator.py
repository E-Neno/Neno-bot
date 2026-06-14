from __future__ import annotations

from .world_model import (
    WorldDef, WorldState, WorldOp,
    obj_exists, obj_room, legal_states_of, room_count, reachable_rooms,
)

ROOM_CAP = 30  # 单房间软上限，防止开放世界无限膨胀


def validate_ops(
    world_def: WorldDef,
    state: WorldState,
    ops: list[WorldOp],
) -> tuple[list[WorldOp], list[tuple[WorldOp, str]]]:
    """逐条校验。返回 (accepted, rejected[(op, reason)])。"""
    accepted: list[WorldOp] = []
    rejected: list[tuple[WorldOp, str]] = []
    for op in ops:
        reason = _check(world_def, state, op)
        if reason is None:
            accepted.append(op)
        else:
            rejected.append((op, reason))
    return accepted, rejected


def _check(world_def: WorldDef, state: WorldState, op: WorldOp) -> str | None:
    if op.op == "set_state":
        if not obj_exists(world_def, state, op.object):
            return "unknown_object"
        if obj_room(world_def, state, op.object) != state.location:
            return "not_in_current_room"
        if op.state not in legal_states_of(world_def, state, op.object):
            return "illegal_state"
        return None

    if op.op == "move":
        if op.to_room not in world_def.rooms:
            return "unknown_room"
        # 刀③：只能去当前房间一步可达的地方（出门要过玄关，不能从公园瞬移回冰箱）
        if op.to_room not in reachable_rooms(world_def, state, state.location):
            return "not_reachable"
        return None

    if op.op == "create_object":
        if op.category not in world_def.categories:
            return "unknown_category"
        if obj_exists(world_def, state, op.object):
            return "object_exists"
        if op.room not in world_def.rooms:
            return "unknown_room"
        if int(op.cost or 0) > state.money:
            return "insufficient_funds"
        if room_count(world_def, state, op.room) >= ROOM_CAP:
            return "room_full"
        return None

    if op.op == "destroy_object":
        if not obj_exists(world_def, state, op.object):
            return "unknown_object"
        return None

    return "unknown_op"
