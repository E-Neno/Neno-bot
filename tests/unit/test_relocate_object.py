"""移动东西（意图通道第一刀）：relocate op —— 她能把手边的东西挪到旁边房间，
物品换房间后持久化、前端快照自动渲染到新位置、口径一致。

设计：
- 提议权给 LLM（一条 WorldOp），裁决权留给 action_validator（不绕）。
- 静态物品的房间在不可变 JSON 里定义，relocate 用 WorldState.obj_room_overrides 覆盖；
  动态物品直接改 dyn_objects[name].room。
- 挪回定义房间则清掉覆盖，保持口径干净。
"""
from app.services.consciousness.world_model import (
    load_world_def, seed_world_state, apply_op,
    obj_room, objects_in_room, WorldOp, WorldState,
)
from app.services.consciousness.action_validator import validate_ops


def _setup():
    wd = load_world_def()
    st = seed_world_state(wd)
    return wd, st


# ── 校验（action_validator，不绕）────────────────────────────────────────────

def test_relocate_accepts_object_here_to_reachable_room():
    wd, st = _setup()
    st.location = "kitchen"  # mug 在厨房；家内房间互通 → 客厅可达
    op = WorldOp(op="relocate", object="mug", to_room="living_room")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []


def test_relocate_rejects_unknown_object():
    wd, st = _setup()
    st.location = "kitchen"
    op = WorldOp(op="relocate", object="dragon", to_room="living_room")
    _, rejected = validate_ops(wd, st, [op])
    assert "unknown_object" in rejected[0][1]


def test_relocate_rejects_object_not_in_current_room():
    wd, st = _setup()
    st.location = "kitchen"  # 在厨房，但 book 在客厅，够不着
    op = WorldOp(op="relocate", object="book", to_room="kitchen")
    _, rejected = validate_ops(wd, st, [op])
    assert "object_not_here" in rejected[0][1]


def test_relocate_rejects_unreachable_destination():
    wd, st = _setup()
    st.location = "bedroom"  # bed 在卧室；咖啡馆要出门，不可一步达
    op = WorldOp(op="relocate", object="bed", to_room="cafe")
    _, rejected = validate_ops(wd, st, [op])
    assert "not_reachable" in rejected[0][1]


def test_relocate_rejects_same_room():
    wd, st = _setup()
    st.location = "kitchen"
    op = WorldOp(op="relocate", object="mug", to_room="kitchen")
    _, rejected = validate_ops(wd, st, [op])
    assert "same_room" in rejected[0][1]


def test_relocate_rejects_unknown_room():
    wd, st = _setup()
    st.location = "kitchen"
    op = WorldOp(op="relocate", object="mug", to_room="dungeon")
    _, rejected = validate_ops(wd, st, [op])
    assert "unknown_room" in rejected[0][1]


# ── 应用 + 渲染口径（apply_op / obj_room / objects_in_room）──────────────────

def test_apply_relocate_static_object_changes_room_and_renders_there():
    wd, st = _setup()
    st.location = "kitchen"
    out = apply_op(wd, st, WorldOp(op="relocate", object="mug", to_room="living_room"))
    # 口径：物品归属新房间
    assert obj_room(wd, out, "mug") == "living_room"
    # 渲染：出现在客厅、不再出现在厨房（前端快照走 objects_in_room）
    assert "mug" in objects_in_room(wd, out, "living_room")
    assert "mug" not in objects_in_room(wd, out, "kitchen")
    # 纯函数：原 state 不变
    assert obj_room(wd, st, "mug") == "kitchen"
    assert "mug" in objects_in_room(wd, st, "kitchen")


def test_apply_relocate_dynamic_object_updates_its_room():
    wd, st = _setup()
    st.location = "balcony"
    st = apply_op(wd, st, WorldOp(op="create_object", object="tulips", category="plant",
                                  room="balcony", label="郁金香", cost=10))
    out = apply_op(wd, st, WorldOp(op="relocate", object="tulips", to_room="living_room"))
    assert obj_room(wd, out, "tulips") == "living_room"
    assert "tulips" in objects_in_room(wd, out, "living_room")
    assert "tulips" not in objects_in_room(wd, out, "balcony")


def test_relocate_back_to_origin_clears_override():
    wd, st = _setup()
    st.location = "kitchen"
    out = apply_op(wd, st, WorldOp(op="relocate", object="mug", to_room="living_room"))
    assert out.obj_room_overrides.get("mug") == "living_room"
    out2 = apply_op(wd, out, WorldOp(op="relocate", object="mug", to_room="kitchen"))
    assert "mug" not in out2.obj_room_overrides  # 回老家 → 覆盖清掉
    assert obj_room(wd, out2, "mug") == "kitchen"


def test_set_state_follows_relocated_object():
    """挪走后，物品在新房间才能被操作——set_state 的「在不在当前房间」认新口径。"""
    wd, st = _setup()
    st.location = "kitchen"
    st = apply_op(wd, st, WorldOp(op="relocate", object="mug", to_room="living_room"))
    st.location = "living_room"  # 她也去客厅
    op = WorldOp(op="set_state", object="mug", state=wd.legal_states("mug")[0])
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []


# ── 旧数据兼容 ──────────────────────────────────────────────────────────────

def test_old_state_data_gets_empty_overrides():
    st = WorldState.model_validate({
        "location": "bedroom",
        "object_states": {"bed": "made"},
    })
    assert st.obj_room_overrides == {}
