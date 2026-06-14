from app.services.consciousness.world_model import (
    load_world_def,
    seed_world_state,
    WorldOp,
)
from app.services.consciousness.action_validator import validate_ops


def _setup():
    wd = load_world_def()
    st = seed_world_state(wd)
    st.location = "kitchen"  # 当前在厨房
    return wd, st


def test_accepts_legal_set_state_in_current_room():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="kettle", state="boiling")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op]
    assert rejected == []


def test_rejects_unknown_object():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="dragon", state="boiling")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert rejected[0][0] == op
    assert "unknown_object" in rejected[0][1]


def test_rejects_object_not_in_current_room():
    wd, st = _setup()  # 在厨房
    op = WorldOp(op="set_state", object="book", state="reading")  # book 在客厅
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "not_in_current_room" in rejected[0][1]


def test_rejects_illegal_state():
    wd, st = _setup()
    op = WorldOp(op="set_state", object="kettle", state="exploded")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "illegal_state" in rejected[0][1]


def test_rejects_move_to_unknown_room():
    wd, st = _setup()
    op = WorldOp(op="move", to_room="dungeon")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "unknown_room" in rejected[0][1]


# ── 刀③ 可达性守门 ──────────────────────────────────────────────────────────

def test_accepts_move_to_adjacent_room():
    wd, st = _setup()  # 在厨房；家内房间互通
    op = WorldOp(op="move", to_room="living_room")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []


def test_accepts_step_out_through_entryway():
    wd, st = _setup()
    st.location = "living_room"
    op = WorldOp(op="move", to_room="entryway")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []


def test_rejects_teleport_to_unreachable_outside():
    wd, st = _setup()
    st.location = "bedroom"  # 不能从卧室瞬移到咖啡馆，要先出门
    op = WorldOp(op="move", to_room="cafe")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == []
    assert "not_reachable" in rejected[0][1]


# ── 竖切6：开放世界守门 ─────────────────────────────────────────────────

def test_create_object_accepts_legal():
    wd, st = _setup()
    op = WorldOp(op="create_object", object="tulips", category="plant",
                 room="balcony", label="郁金香", cost=20)
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []


def test_create_rejects_unknown_category():
    wd, st = _setup()
    op = WorldOp(op="create_object", object="ufo", category="spaceship",
                 room="balcony", cost=1)
    _, rejected = validate_ops(wd, st, [op])
    assert "unknown_category" in rejected[0][1]


def test_create_rejects_existing_object():
    wd, st = _setup()
    op = WorldOp(op="create_object", object="kettle", category="appliance",
                 room="kitchen", cost=1)
    _, rejected = validate_ops(wd, st, [op])
    assert "object_exists" in rejected[0][1]


def test_create_rejects_insufficient_funds():
    wd, st = _setup()
    st.money = 5
    op = WorldOp(op="create_object", object="tulips", category="plant",
                 room="balcony", cost=50)
    _, rejected = validate_ops(wd, st, [op])
    assert "insufficient_funds" in rejected[0][1]


def test_create_rejects_unknown_room():
    wd, st = _setup()
    op = WorldOp(op="create_object", object="tulips", category="plant",
                 room="dungeon", cost=10)
    _, rejected = validate_ops(wd, st, [op])
    assert "unknown_room" in rejected[0][1]


def test_destroy_rejects_unknown_object():
    wd, st = _setup()
    op = WorldOp(op="destroy_object", object="dragon")
    _, rejected = validate_ops(wd, st, [op])
    assert "unknown_object" in rejected[0][1]


def test_destroy_accepts_existing():
    wd, st = _setup()
    op = WorldOp(op="destroy_object", object="mug")
    accepted, rejected = validate_ops(wd, st, [op])
    assert accepted == [op] and rejected == []
