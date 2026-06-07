from app.services.consciousness.world_model import (
    load_world_def,
    seed_world_state,
    apply_op,
    WorldOp,
)


def test_world_def_loads_and_indexes():
    wd = load_world_def()
    assert wd.room_of("kettle") == "kitchen"
    assert "cold" in wd.legal_states("kettle")
    assert wd.default_state("kettle") == "cold"


def test_seed_state_uses_defaults():
    wd = load_world_def()
    st = seed_world_state(wd)
    assert st.object_states["plants"] == "fresh"
    assert st.location in wd.rooms


def test_apply_set_state_returns_changed_copy():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="set_state", object="kettle", state="boiling"))
    assert out.object_states["kettle"] == "boiling"
    assert st.object_states["kettle"] == "cold"  # 原对象不被改（纯函数）


def test_apply_move_changes_location():
    wd = load_world_def()
    st = seed_world_state(wd)
    out = apply_op(wd, st, WorldOp(op="move", to_room="balcony"))
    assert out.location == "balcony"
